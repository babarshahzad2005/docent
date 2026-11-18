"""The Demo Collection: openly licensed workplace guidance that every User can ask (PRD).

    uv run docent-demo fetch   # download the sources into evals/demo/documents (maintainers)
    uv run docent-demo seed    # put them in the Demo Collection of the configured database

The sources are listed, with their licences and credits, in `evals/demo/sources.json`. Fetching
turns GOV.UK pages (from its content API) and GitLab Handbook pages into Markdown, keeping
their text and structure; PDFs and Word files are kept as published. The fetched files are
committed, so the Demo Collection and the Eval Set built on it (#46) stay the same until a
maintainer fetches again.

Seeding is repeatable: a file already in the collection with the same content is left alone,
a changed one is replaced, and one no longer listed is deleted. New Documents are queued for
ingestion like any upload.
"""

import argparse
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import Connection
from psycopg.rows import DictRow, dict_row

from docent_api.documents import FILE_TYPES, remove_files
from docent_api.settings import get_settings
from docent_api.storage import FileStore, SupabaseFileStore

REPO = Path(__file__).resolve().parents[4]
DEMO = REPO / "evals" / "demo"
SOURCES = DEMO / "sources.json"
DOCUMENTS = DEMO / "documents"
_USER_AGENT = "docent-demo-fetch/1.0"


# --- Fetching -----------------------------------------------------------------------------


def fetch_all() -> None:
    sources = json.loads(SOURCES.read_text(encoding="utf-8"))
    DOCUMENTS.mkdir(parents=True, exist_ok=True)
    for source in sources["documents"]:
        target = DOCUMENTS / source["file"]
        kind = source["kind"]
        if kind == "govuk":
            target.write_text(govuk_markdown(source), encoding="utf-8", newline="\n")
        elif kind == "gitlab":
            raw = _get(source["raw"]).decode("utf-8")
            target.write_text(handbook_markdown(raw, source), encoding="utf-8", newline="\n")
        elif kind == "download":
            target.write_bytes(_get(source["source"]))
        elif kind != "local":
            raise SystemExit(f"unknown kind {kind!r} for {source['file']}")
        print(f"  {source['file']}")
    print(f"Fetched {len(sources['documents'])} sources into {DOCUMENTS}")


def _get(url: str, attempts: int = 3) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data: bytes = response.read()
                return data
        except (urllib.error.URLError, TimeoutError):
            if attempt == attempts:
                raise
            time.sleep(2 * attempt)
    raise AssertionError("unreachable")


def govuk_markdown(source: dict[str, Any]) -> str:
    """A GOV.UK guide or publication as Markdown, from its content API."""
    path = source["source"].removeprefix("https://www.gov.uk/")
    page = json.loads(_get(f"https://www.gov.uk/api/content/{path}"))
    details = page.get("details", {})
    sections = [f"# {page['title']}"]
    if page.get("description"):
        sections.append(page["description"])
    if details.get("parts"):
        for part in details["parts"]:
            sections.append(f"## {part['title']}")
            sections.append(html_to_markdown(part["body"], shift=1))
    else:
        sections.append(html_to_markdown(details.get("body", ""), shift=0))
    return _footer("\n\n".join(sections), source)


def handbook_markdown(raw: str, source: dict[str, Any]) -> str:
    """A GitLab Handbook page as plain Markdown: front matter, shortcodes, and HTML removed."""
    title = source["title"]
    match = re.match(r"^---\n(.*?)\n---\n", raw, re.S)
    if match:
        found = re.search(r'^title:\s*"?(.+?)"?\s*$', match.group(1), re.M)
        title = found.group(1) if found else title
        raw = raw[match.end() :]
    text = re.sub(r"```mermaid.*?```", "", raw, flags=re.S)  # diagrams drawn in code
    text = re.sub(r"\{\{[<%].*?[%>]\}\}", "", text, flags=re.S)  # Hugo shortcodes
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)  # images
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)  # links keep their words
    text = re.sub(r"</?[a-zA-Z][^>]*>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return _footer(f"# {title}\n\n{text}", source)


def _footer(markdown: str, source: dict[str, Any]) -> str:
    return (
        f"{markdown.rstrip()}\n\n---\n\nSource: {source['source']}\n\n"
        f"{source['credit'].rstrip('.')}. Licence: {source['licence']}. Converted to Markdown "
        "for Docent's Demo Collection: images, links, and diagrams were removed; the text is "
        "otherwise unchanged.\n"
    )


class _HtmlToMarkdown(HTMLParser):
    """GOV.UK's body HTML (headings, paragraphs, lists, tables, links) as Markdown."""

    def __init__(self, shift: int) -> None:
        super().__init__(convert_charrefs=True)
        self.shift = shift
        self.out: list[str] = []
        self.line: list[str] = []
        self.lists: list[str] = []
        self.cells: list[str] | None = None
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "svg"):
            self.skip += 1
        elif re.fullmatch(r"h[1-6]", tag):
            self._flush()
            level = min(6, int(tag[1]) + self.shift)
            self.line.append("#" * level + " ")
        elif tag in ("ul", "ol"):
            self._flush()
            self.lists.append(tag)
        elif tag == "li":
            self._flush()
            self.line.append("  " * (len(self.lists) - 1) + "- ")
        elif tag == "tr":
            self._flush()
            self.cells = []
        elif tag in ("td", "th") and self.cells is not None:
            self.line = []
        elif tag == "br":
            self.line.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "svg"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("p", "li", "div") or re.fullmatch(r"h[1-6]", tag):
            self._flush()
        elif tag in ("ul", "ol"):
            self._flush()
            if self.lists:
                self.lists.pop()
            self.out.append("")
        elif tag in ("td", "th") and self.cells is not None:
            self.cells.append(" ".join("".join(self.line).split()))
            self.line = []
        elif tag == "tr" and self.cells is not None:
            if any(self.cells):
                self.out.append(" | ".join(self.cells))
            self.cells = None
        elif tag == "table":
            self.out.append("")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.line.append(data)

    def _flush(self) -> None:
        if self.cells is not None:
            return
        text = " ".join("".join(self.line).split())
        self.line = []
        if text and text not in ("-", "#"):
            self.out.append(text)
            if not text.startswith("- ") and not text.lstrip().startswith("- "):
                self.out.append("")

    def markdown(self) -> str:
        self._flush()
        return re.sub(r"\n{3,}", "\n\n", "\n".join(self.out)).strip()


def html_to_markdown(body: str, shift: int) -> str:
    parser = _HtmlToMarkdown(shift)
    parser.feed(html.unescape(body) if "&lt;" in body else body)
    return parser.markdown()


# --- Seeding ------------------------------------------------------------------------------


@dataclass(frozen=True)
class SeedResult:
    added: int
    replaced: int
    unchanged: int
    removed: int


def demo_collection(conn: Connection[DictRow]) -> UUID:
    """The Demo Collection's id, creating it the first time."""
    with conn.transaction():
        row = conn.execute("select id from app.collections where is_demo").fetchone()
        if row is None:
            row = conn.execute(
                "insert into app.collections (name, is_demo) values (%s, true) returning id",
                (json.loads(SOURCES.read_text(encoding="utf-8"))["collection"],),
            ).fetchone()
        assert row is not None
        # Everyone already signed up gets it now; later Users get it at sign-up (library.py).
        conn.execute(
            """
            insert into app.memberships (collection_id, user_id, role)
            select %s, id, 'viewer' from app.users
            on conflict (collection_id, user_id) do nothing
            """,
            (row["id"],),
        )
        return UUID(str(row["id"]))


def seed(conn: Connection[DictRow], store: FileStore, documents: Path = DOCUMENTS) -> SeedResult:
    sources = json.loads(SOURCES.read_text(encoding="utf-8"))["documents"]
    collection_id = demo_collection(conn)
    existing = {
        row["name"]: row
        for row in conn.execute(
            "select id, name, content_hash from app.documents where collection_id = %s",
            (collection_id,),
        ).fetchall()
    }
    conn.commit()
    added = replaced = unchanged = 0
    for source in sources:
        path = REPO / source["path"] if source["kind"] == "local" else documents / source["file"]
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        name = source["file"]
        if Path(name).suffix.lower() not in FILE_TYPES:
            raise SystemExit(f"{name}: not a type Docent reads")
        current = existing.pop(name, None)
        if current is not None and current["content_hash"] == digest:
            unchanged += 1
            continue
        if current is not None:
            _remove(conn, store, current["id"])
            replaced += 1
        else:
            added += 1
        _add(conn, store, collection_id, source, data, digest)
    for leftover in existing.values():
        _remove(conn, store, leftover["id"])
    return SeedResult(added, replaced, unchanged, len(existing))


def _add(
    conn: Connection[DictRow],
    store: FileStore,
    collection_id: UUID,
    source: dict[str, Any],
    data: bytes,
    digest: str,
) -> None:
    document_id = uuid4()
    path = f"{collection_id}/{document_id}{Path(source['file']).suffix.lower()}"
    store.upload(path, data)
    with conn.transaction():
        conn.execute(
            """
            insert into app.documents
                (id, collection_id, name, size_bytes, storage_path, status, content_hash,
                 effective_date, source_url, source_credit)
            values (%(id)s, %(collection)s, %(name)s, %(size)s, %(path)s, 'queued', %(hash)s,
                    %(effective)s, %(url)s, %(credit)s)
            """,
            {
                "id": document_id,
                "collection": collection_id,
                "name": source["file"],
                "size": len(data),
                "path": path,
                "hash": digest,
                "effective": source.get("effective_date") or date.today().isoformat(),
                "url": source["source"],
                "credit": f"{source['credit'].rstrip('.')}. Licence: {source['licence']}.",
            },
        )


def _remove(conn: Connection[DictRow], store: FileStore, document_id: UUID) -> None:
    """Delete a Demo Document the same way Users' deletions work (documents.py): the row first,
    then its file, which a later batch removes if storage can't now."""
    with conn.transaction():
        row = conn.execute(
            "delete from app.documents where id = %s returning storage_path", (document_id,)
        ).fetchone()
        if row is None:
            return
        conn.execute(
            "insert into app.storage_deletions (path) values (%s) on conflict (path) do nothing",
            (row["storage_path"],),
        )
    remove_files(conn, store, [row["storage_path"]])


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch or seed the Demo Collection.")
    parser.add_argument("command", choices=["fetch", "seed"])
    command = parser.parse_args().command
    if command == "fetch":
        fetch_all()
        return
    settings = get_settings()
    if not settings.database_url or not settings.supabase_secret_key:
        raise SystemExit("Set DATABASE_URL, SUPABASE_URL and SUPABASE_SECRET_KEY first.")
    store = SupabaseFileStore(settings.supabase_url, settings.supabase_secret_key)
    with psycopg.connect(
        settings.database_url, prepare_threshold=None, row_factory=dict_row
    ) as conn:
        result = seed(conn, store)
    print(
        f"Demo Collection: {result.added} added, {result.replaced} replaced, "
        f"{result.unchanged} unchanged, {result.removed} removed. New Documents are queued; "
        "the scheduler indexes them."
    )
    sys.exit(0)
