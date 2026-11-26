"""Visitors' rate limits (#94; FLOWS, Publish): per network address each hour, all Visitors
together each day, and no raw address stored."""

from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import Connection
from psycopg.rows import DictRow, dict_row

from docent_api import main
from docent_api.auth import AuthUser
from docent_api.collection_settings import create_collection
from docent_api.db import get_connection
from docent_api.library import ensure_user
from docent_api.limits import RateLimited, check_api_key, check_visitor, visitor_bucket
from docent_api.public import set_public
from docent_api.settings import get_settings


@pytest.fixture(autouse=True)
def _limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "visitor_questions_per_hour", 3)
    monkeypatch.setattr(get_settings(), "visitor_questions_per_day", 100)


def asks(conn: Connection[DictRow], address: str, times: int) -> None:
    for _ in range(times):
        check_visitor(conn, address)


def test_a_visitor_gets_so_many_questions_an_hour(conn: Connection[DictRow]) -> None:
    asks(conn, "203.0.113.5", 3)

    with pytest.raises(RateLimited) as refused:
        check_visitor(conn, "203.0.113.5")

    assert 0 < refused.value.retry_after <= 3600
    assert "Try again in" in refused.value.message
    check_visitor(conn, "198.51.100.7")  # someone else is unaffected


def test_the_next_hour_starts_afresh(conn: Connection[DictRow]) -> None:
    asks(conn, "203.0.113.5", 3)
    conn.execute("update app.rate_limits set window_start = window_start - interval '1 hour'")
    conn.commit()

    check_visitor(conn, "203.0.113.5")


def test_a_refused_question_doesnt_count(conn: Connection[DictRow]) -> None:
    asks(conn, "203.0.113.5", 3)
    for _ in range(5):
        with pytest.raises(RateLimited):
            check_visitor(conn, "203.0.113.5")

    row = conn.execute(
        "select hits from app.rate_limits where bucket = %s", (visitor_bucket("203.0.113.5"),)
    ).fetchone()
    conn.commit()
    assert row == {"hits": 3}


def test_all_visitors_together_have_a_daily_cap(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "visitor_questions_per_day", 4)
    for n in range(4):
        check_visitor(conn, f"203.0.113.{n}")

    with pytest.raises(RateLimited) as refused:
        check_visitor(conn, "203.0.113.99")

    assert "tomorrow" in refused.value.message
    assert 0 < refused.value.retry_after <= 24 * 3600


def test_no_address_is_stored(conn: Connection[DictRow]) -> None:
    asks(conn, "203.0.113.5", 1)
    asks(conn, "2001:db8:1:2::77", 1)

    stored = " ".join(
        row["bucket"] for row in conn.execute("select bucket from app.rate_limits").fetchall()
    )
    conn.commit()
    assert "203.0.113" not in stored
    assert "2001:db8" not in stored


def test_one_ipv6_network_is_one_visitor() -> None:
    assert visitor_bucket("2001:db8:1:2::1") == visitor_bucket("2001:db8:1:2:ffff::9")
    assert visitor_bucket("2001:db8:1:2::1") != visitor_bucket("2001:db8:1:3::1")


def test_old_windows_are_cleaned_up(conn: Connection[DictRow]) -> None:
    conn.execute(
        "insert into app.rate_limits (bucket, window_start) "
        "values ('visitor:old', now() - interval '3 days')"
    )
    conn.commit()

    check_visitor(conn, "203.0.113.5")

    assert (
        conn.execute("select 1 from app.rate_limits where bucket = 'visitor:old'").fetchone()
        is None
    )
    conn.commit()


def test_the_api_refuses_with_retry_after_and_only_counts_public_questions(
    database_url: str, conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_answers import QUOTES, ScriptedModel, WordsEmbedder

    owner = AuthUser(id=uuid4(), email=f"owner-{uuid4().hex[:6]}@example.com")
    ensure_user(conn, owner)
    public = create_collection(conn, owner.id, "Handbook").id
    private = create_collection(conn, owner.id, "Private").id
    set_public(conn, owner.id, public, True)
    conn.commit()

    def connection() -> Iterator[Connection[DictRow]]:
        with psycopg.connect(database_url, row_factory=dict_row) as own:
            yield own

    monkeypatch.setattr(main, "embedder", WordsEmbedder)
    monkeypatch.setattr(main, "answer_generator", lambda: ScriptedModel(["x [1].", QUOTES]))
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(
        database_url, min_size=0, max_size=2, kwargs={"row_factory": dict_row}, open=True
    )
    monkeypatch.setattr("docent_api.answers.get_pool", lambda: pool)
    main.app.dependency_overrides[get_connection] = connection
    try:
        client = TestClient(main.app)
        question = {"question": "Leave?"}
        for _ in range(5):  # a Collection that isn't public: refused, never counted
            assert client.post(f"/public/{private}/answers", json=question).status_code == 404
        for _ in range(3):
            assert client.post(f"/public/{public}/answers", json=question).status_code == 200

        refused = client.post(f"/public/{public}/answers", json=question)

        assert refused.status_code == 429
        assert 0 < int(refused.headers["retry-after"]) <= 3600
        assert "Try again in" in refused.json()["detail"]
    finally:
        main.app.dependency_overrides.clear()
        pool.close()


def test_each_api_key_gets_so_many_questions_an_hour(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "api_key_questions_per_hour", 2)
    key, other = uuid4(), uuid4()
    check_api_key(conn, key)
    check_api_key(conn, key)

    with pytest.raises(RateLimited) as refused:
        check_api_key(conn, key)

    assert "This API key has asked 2 questions this hour" in refused.value.message
    check_api_key(conn, other)  # each key has its own count
    with pytest.raises(RateLimited):
        check_api_key(conn, key)  # a refused question didn't count, but the limit still holds


def test_the_web_app_may_call_it_from_the_browser() -> None:
    client = TestClient(main.app)
    origin = get_settings().web_origins.split(",")[0]
    preview = "https://docent-git-feat-x-babarshahzad2005-8329s-projects.vercel.app"

    allowed = client.options(
        "/public/x/answers",
        headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
    )
    other = client.options(
        "/public/x/answers",
        headers={"Origin": "https://elsewhere.example", "Access-Control-Request-Method": "POST"},
    )

    assert allowed.headers.get("access-control-allow-origin") == origin
    previewed = client.options(
        "/public/x/answers",
        headers={"Origin": preview, "Access-Control-Request-Method": "POST"},
    )
    assert previewed.headers.get("access-control-allow-origin") == preview
    assert "access-control-allow-origin" not in other.headers
