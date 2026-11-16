from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import Connection
from psycopg.rows import DictRow, dict_row

from docent_api.auth import AuthUser, current_user
from docent_api.db import get_connection
from docent_api.library import ensure_user, list_collections
from docent_api.main import app


def count(conn: Connection[DictRow], table: str, user: AuthUser) -> int:
    column = {"users": "id", "collections": "personal_owner_id", "memberships": "user_id"}[table]
    row = conn.execute(
        f"select count(*) as n from app.{table} where {column} = %s", (user.id,)
    ).fetchone()
    assert row is not None
    return int(row["n"])


@pytest.fixture
def user() -> AuthUser:
    return AuthUser(id=uuid4(), email="reader@example.com")


def test_first_sign_in_creates_the_user_and_their_personal_collection(
    conn: Connection[DictRow], user: AuthUser
) -> None:
    ensure_user(conn, user)

    collections = list_collections(conn, user.id)
    assert [(c.name, c.is_personal, c.role) for c in collections] == [("Personal", True, "owner")]
    assert count(conn, "users", user) == 1


def test_signing_in_again_creates_nothing_new(conn: Connection[DictRow], user: AuthUser) -> None:
    ensure_user(conn, user)
    ensure_user(conn, user)

    assert count(conn, "users", user) == 1
    assert count(conn, "collections", user) == 1
    assert count(conn, "memberships", user) == 1


def test_simultaneous_first_requests_create_one_personal_collection(
    database_url: str, conn: Connection[DictRow], user: AuthUser
) -> None:
    def sign_in() -> None:
        with psycopg.connect(database_url, row_factory=dict_row) as own:
            ensure_user(own, user)

    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in [pool.submit(sign_in) for _ in range(4)]:
            future.result()

    assert count(conn, "collections", user) == 1
    assert count(conn, "memberships", user) == 1


def test_a_changed_email_is_updated(conn: Connection[DictRow], user: AuthUser) -> None:
    ensure_user(conn, user)
    ensure_user(conn, AuthUser(id=user.id, email="new@example.com"))

    row = conn.execute("select email from app.users where id = %s", (user.id,)).fetchone()
    assert row is not None and row["email"] == "new@example.com"


@pytest.fixture
def client(database_url: str, user: AuthUser) -> Iterator[TestClient]:
    def connection() -> Iterator[Connection[DictRow]]:
        with psycopg.connect(database_url, row_factory=dict_row) as own:
            yield own

    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_connection] = connection
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_database_health_answers(client: TestClient) -> None:
    response = client.get("/health/database")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_me_returns_the_signed_in_user_and_their_personal_collection(
    client: TestClient, conn: Connection[DictRow], user: AuthUser
) -> None:
    response = client.get("/me")

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "reader@example.com"
    assert [(c["name"], c["is_personal"], c["role"]) for c in body["collections"]] == [
        ("Personal", True, "owner")
    ]
