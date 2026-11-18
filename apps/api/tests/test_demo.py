"""The Demo Collection: converting its sources, seeding it, and who can do what with it."""

import json
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from docent_api import demo
from docent_api.auth import AuthUser
from docent_api.demo import demo_collection, handbook_markdown, html_to_markdown, seed
from docent_api.documents import NotAllowed, delete_document, list_documents, start_upload
from docent_api.library import ensure_user, list_collections
from docent_api.storage import SignedUpload

SOURCES = json.loads(demo.SOURCES.read_text(encoding="utf-8"))["documents"]


class MemoryStore:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def signed_upload(self, path: str) -> SignedUpload:
        return SignedUpload("documents", path, "token")

    def download(self, path: str) -> bytes:
        return self.files[path]

    def upload(self, path: str, data: bytes) -> None:
        self.files[path] = data

    def delete(self, paths: Sequence[str]) -> None:
        for path in paths:
            self.files.pop(path, None)


# --- The sources --------------------------------------------------------------------------


def test_the_sources_are_complete_licensed_and_present() -> None:
    assert 30 <= len(SOURCES) <= 50
    assert {s["licence"] for s in SOURCES} == {"Open Government Licence v3.0", "CC BY-SA 4.0"}
    suffixes = {Path(s["file"]).suffix for s in SOURCES}
    assert {".md", ".pdf", ".docx"} <= suffixes
    assert sum(s["file"].endswith(".docx") and s["kind"] == "download" for s in SOURCES) >= 2
    for source in SOURCES:
        path = (
            demo.REPO / source["path"]
            if source["kind"] == "local"
            else demo.DOCUMENTS / source["file"]
        )
        assert path.is_file(), source["file"]
        assert source["source"].startswith("https://") and source["credit"]


def test_the_conflicting_versions_are_both_included() -> None:
    dated = {s["file"]: s.get("effective_date") for s in SOURCES}

    assert dated["holiday-entitlement-guidance-2019.pdf"] == "2019-11-01"
    assert dated["govuk-holiday-pay-and-entitlement-reforms-from-1-january-2024.md"] == "2024-01-01"


def test_govuk_html_becomes_markdown_with_its_structure() -> None:
    body = (
        "<h2>Entitlement</h2><p>Most workers get <strong>5.6 weeks</strong>.</p>"
        "<ul><li>agency workers</li><li>part-year workers</li></ul>"
        "<table><tr><th>Year</th><th>Rate</th></tr><tr><td>2025</td><td>£12.21</td></tr></table>"
    )

    markdown = html_to_markdown(body, shift=1)

    assert markdown.splitlines()[0] == "### Entitlement"
    assert "Most workers get 5.6 weeks." in markdown
    assert "- agency workers\n- part-year workers" in markdown
    assert "Year | Rate\n2025 | £12.21" in markdown


def test_handbook_pages_lose_their_site_markup_and_keep_their_words() -> None:
    raw = (
        '---\ntitle: "Time Off Types"\n---\n'
        "## PTO\n\n{{< note >}}Read [the policy](https://x.test/p) first.{{< /note >}}\n\n"
        '```mermaid\nflowchart TD\n  a{{"Ask?"}}\n```\n\n![chart](c.png)<br>Take time off.\n'
    )

    markdown = handbook_markdown(raw, SOURCES[12])

    assert markdown.startswith("# Time Off Types\n\n## PTO")
    assert "Read the policy first." in markdown and "Take time off." in markdown
    for leftover in ("{{", "mermaid", "](", "<br>", "c.png"):
        assert leftover not in markdown
    assert "Licence: CC BY-SA 4.0" in markdown


# --- Seeding and access -------------------------------------------------------------------


def make_user(conn: Connection[DictRow], email: str) -> AuthUser:
    user = AuthUser(id=uuid4(), email=email)
    ensure_user(conn, user)
    conn.commit()
    return user


def test_seeding_fills_the_collection_once_and_credits_every_document(
    conn: Connection[DictRow],
) -> None:
    early = make_user(conn, "early@example.com")
    store = MemoryStore()

    first = seed(conn, store)
    again = seed(conn, store)

    assert (first.added, first.unchanged) == (len(SOURCES), 0)
    assert (again.added, again.replaced, again.unchanged, again.removed) == (0, 0, len(SOURCES), 0)
    assert len(store.files) == len(SOURCES)
    rows = conn.execute(
        "select name, status, source_url, source_credit, effective_date from app.documents"
    ).fetchall()
    conn.commit()
    assert all(
        r["status"] == "queued" and r["source_url"] and "Licence:" in r["source_credit"]
        for r in rows
    )
    reforms = next(r for r in rows if "reforms" in r["name"])
    assert str(reforms["effective_date"]) == "2024-01-01"
    # Users who signed up before the collection existed get it too.
    assert [(c.name, c.is_demo, c.role) for c in list_collections(conn, early.id)][1] == (
        "Demo Collection",
        True,
        "viewer",
    )


def test_a_changed_source_is_replaced_and_a_dropped_one_removed(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = MemoryStore()
    seed(conn, store)
    documents = tmp_path / "documents"
    documents.mkdir()
    for path in demo.DOCUMENTS.iterdir():
        (documents / path.name).write_bytes(path.read_bytes())
    (documents / "govuk-statutory-sick-pay.md").write_text("# Statutory Sick Pay\n\nChanged.\n")
    kept = [s for s in SOURCES if s["file"] != "gitlab-benefits.md"]
    listing = tmp_path / "sources.json"
    listing.write_text(json.dumps({"collection": "Demo Collection", "documents": kept}))
    monkeypatch.setattr(demo, "SOURCES", listing)

    result = seed(conn, store, documents)

    assert (result.replaced, result.removed) == (1, 1)
    names = {r["name"] for r in conn.execute("select name from app.documents").fetchall()}
    conn.commit()
    assert "gitlab-benefits.md" not in names and len(names) == len(kept)


def test_new_users_can_ask_the_demo_collection_but_not_change_it(
    conn: Connection[DictRow],
) -> None:
    store = MemoryStore()
    seed(conn, store)
    demo_id = demo_collection(conn)
    user = make_user(conn, "new@example.com")

    collections = list_collections(conn, user.id)
    one = next(d for d in list_documents(conn, user.id) if d.collection_id == demo_id)

    assert [c.name for c in collections] == ["Personal", "Demo Collection"]
    assert one.source_credit
    with pytest.raises(NotAllowed):
        start_upload(conn, store, user.id, demo_id, "mine.md", 10)
    with pytest.raises(NotAllowed):
        delete_document(conn, store, user.id, one.id)
