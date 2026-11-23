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

LICENCE_URLS = {
    "Open Government Licence v3.0": (
        "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"
    ),
    "CC BY-SA 4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
}
OGL_STATEMENT = (
    "Contains public sector information licensed under the Open Government Licence v3.0."
)


def fetch_all() -> None:
    """Download every source, convert it, and record when it was checked and its dates."""
    listing = json.loads(SOURCES.read_text(encoding="utf-8"))
    DOCUMENTS.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    names = [source["file"] for source in listing["documents"]]
    if len(names) != len(set(names)):
        raise SystemExit("Two sources share a file name; seeding matches Documents by name.")
    fetched: dict[str, bytes] = {}
    for source in listing["documents"]:
        source["licence_url"] = LICENCE_URLS[source["licence"]]
        kind = source["kind"]
        if kind == "govuk":
            fetched[source["file"]] = govuk_markdown(source).encode("utf-8")
        elif kind == "gitlab":
            raw = _get(source["raw"]).decode("utf-8")
            fetched[source["file"]] = handbook_markdown(raw, source).encode("utf-8")
        elif kind == "download":
            fetched[source["file"]] = _get(source["source"])
        elif kind != "local":
            raise SystemExit(f"unknown kind {kind!r} for {source['file']}")
        print(f"  {source['file']}")
    # Everything downloaded: only now are files and the source list changed.
    for source in listing["documents"]:
        data = fetched.get(source["file"])
        if data is None:
            continue
        source["checked_on"] = today
        target = DOCUMENTS / source["file"]
        changed = not target.exists() or target.read_bytes() != data
        if not source.get("pin_effective_date") and (changed or "effective_date" not in source):
            # Live pages state the rules as they stand: dated when their text last changed.
            source["effective_date"] = today
        if changed:
            target.write_bytes(data)
    SOURCES.write_text(
        json.dumps(listing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"Fetched {len(names)} sources into {DOCUMENTS}")


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


_FENCE = re.compile(r"(```.*?```)", re.S)


def handbook_markdown(raw: str, source: dict[str, Any]) -> str:
    """A GitLab Handbook page as plain Markdown, without its site's markup.

    Code blocks are kept as they are; everywhere else Hugo shortcodes, heading anchors,
    images, HTML tags, and link targets are removed, and diagrams drawn in code are dropped.
    """
    title = source["title"]
    match = re.match(r"^---\n(.*?)\n---\n", raw, re.S)
    if match:
        found = re.search(r'^title:\s*"?(.+?)"?\s*$', match.group(1), re.M)
        title = found.group(1) if found else title
        raw = raw[match.end() :]
    pieces = []
    for piece in _FENCE.split(raw):
        if piece.startswith("```"):
            if not piece.startswith("```mermaid"):
                pieces.append(piece)
            continue
        pieces.append(_clean_handbook_text(piece))
    text = re.sub(r"\n{3,}", "\n\n", "".join(pieces)).strip()
    return _footer(f"# {title}\n\n{text}", source)


def _clean_handbook_text(text: str) -> str:
    text = re.sub(r"\{\{[<%][^{}]*?[%>]\}\}", "", text)  # shortcodes, never past a brace
    text = re.sub(r"[ \t]*\{#[^}\n]+\}", "", text)  # heading anchors, "## Title {#title}"
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)  # images
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)  # links keep their words
    text = re.sub(r"<(https?://[^>\s]+)>", r"\1", text)  # autolinks keep their address
    text = re.sub(r"</?[a-zA-Z][^>\n]*>", "", text)
    # What's left of the site's HTML layout is indented text; only list items keep their indent.
    lines = []
    for line in html.unescape(text).split("\n"):
        if not line.strip():
            lines.append("")
        elif line.startswith("    ") and not re.match(r"\s*([-*+]|\d+\.)\s", line):
            lines.append(line.strip())
        else:
            lines.append(line.rstrip())
    return "\n".join(lines)


def _footer(markdown: str, source: dict[str, Any]) -> str:
    licence = source["licence"]
    statement = f" {OGL_STATEMENT}" if licence.startswith("Open Government") else ""
    return (
        f"{markdown.rstrip()}\n\n---\n\nSource: {source['source']}\n\n"
        f"{source['credit'].rstrip('.')}. Licence: {licence} ({LICENCE_URLS[licence]}).{statement} "
        "Adapted for Docent's Demo Collection: converted to Markdown, with formatting simplified "
        "and images, links, and diagrams removed.\n"
    )


class _HtmlToMarkdown(HTMLParser):
    """GOV.UK's body HTML as Markdown: headings, paragraphs, numbered and nested lists, and
    tables (as Markdown tables). Entities are decoded once, by the parser."""

    def __init__(self, shift: int) -> None:
        super().__init__(convert_charrefs=True)
        self.shift = shift
        self.blocks: list[str] = []
        self.text: list[str] = []
        self.prefix = ""
        self.lists: list[list[int | None]] = []  # [counter] per open list; None = bullets
        self.item_open = False
        self.table: list[list[str]] | None = None
        self.cell: list[str] | None = None
        self.skip = 0

    # Blocks

    def _emit(self) -> None:
        words = " ".join("".join(self.text).split())
        self.text = []
        if not words:
            return  # keep the prefix (an item's number) for the text still to come
        self.blocks.append(self.prefix + words)
        if self.item_open:  # further paragraphs of the same item line up under its text
            self.prefix = "   " * len(self.lists)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "svg"):
            self.skip += 1
        elif self.cell is not None:
            if tag in ("li", "p", "br") and "".join(self.cell).strip():
                self.cell.append("; " if tag == "li" else " ")
        elif re.fullmatch(r"h[1-6]", tag):
            self._emit()
            self.prefix = "#" * min(6, int(tag[1]) + self.shift) + " "
        elif tag in ("ul", "ol"):
            self._emit()
            self.lists.append([0 if tag == "ol" else None])
        elif tag == "li" and self.lists:
            self._emit()
            counter = self.lists[-1]
            depth = "   " * (len(self.lists) - 1)
            if counter[0] is None:
                self.prefix = f"{depth}- "
            else:
                counter[0] += 1
                self.prefix = f"{depth}{counter[0]}. "
            self.item_open = True
        elif tag in ("p", "div"):
            self._emit()
        elif tag == "table":
            self._emit()
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.table.append([])
        elif tag in ("td", "th") and self.table is not None:
            self.cell = []
        elif tag == "br":
            self.text.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "svg"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("td", "th") and self.cell is not None and self.table:
            words = " ".join("".join(self.cell).split()).replace("|", "\\|")
            self.table[-1].append(words)
            self.cell = None
        elif self.cell is not None:
            return
        elif re.fullmatch(r"h[1-6]", tag) or tag in ("p", "div"):
            self._emit()
            if not self.item_open:
                self.prefix = ""
        elif tag == "li":
            self._emit()
            self.item_open = False
            self.prefix = ""
        elif tag in ("ul", "ol") and self.lists:
            self._emit()
            self.lists.pop()
            self.item_open = bool(self.lists)
            self.prefix = "   " * len(self.lists) if self.lists else ""
            if not self.lists:
                self.blocks.append("")
        elif tag == "table" and self.table is not None:
            self._table(self.table)
            self.table = None

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        (self.cell if self.cell is not None else self.text).append(data)

    def _table(self, rows: list[list[str]]) -> None:
        rows = [row for row in rows if any(row)]
        if not rows:
            return
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
        lines += ["| " + " | ".join(row) + " |" for row in rows[1:]]
        self.blocks.append("\n".join(lines))

    def markdown(self) -> str:
        self._emit()
        out: list[str] = []
        for block in self.blocks:
            # List items sit together; other blocks are separated by a blank line.
            is_item = bool(re.match(r"\s*(- |\d+\. )", block)) or block.startswith("   ")
            if out and not (is_item and out[-1] != "" and _is_list_line(out[-1])):
                out.append("")
            out.append(block)
        return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def _is_list_line(line: str) -> bool:
    return bool(re.match(r"\s*(- |\d+\. )", line)) or line.startswith("   ")


def html_to_markdown(body: str, shift: int) -> str:
    parser = _HtmlToMarkdown(shift)
    parser.feed(body)
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
                # Public from the start: anyone can try it without signing in (#95).
                "insert into app.collections (name, is_demo, public) values (%s, true, true) "
                "returning id",
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
            _update_details(conn, current["id"], source)
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
                 effective_date, source_url, source_credit, source_licence_url)
            values (%(id)s, %(collection)s, %(name)s, %(size)s, %(path)s, 'queued', %(hash)s,
                    %(effective)s, %(url)s, %(credit)s, %(licence_url)s)
            """,
            {
                "id": document_id,
                "collection": collection_id,
                "name": source["file"],
                "size": len(data),
                "path": path,
                "hash": digest,
                **_details(source),
            },
        )


def _details(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "effective": source.get("effective_date") or date.today().isoformat(),
        "url": source["source"],
        "credit": _credit(source),
        "licence_url": LICENCE_URLS[source["licence"]],
    }


def _update_details(conn: Connection[DictRow], document_id: UUID, source: dict[str, Any]) -> None:
    """The same file, but its date, source, or credit may have changed in the source list."""
    with conn.transaction():
        conn.execute(
            """
            update app.documents
            set effective_date = %(effective)s, source_url = %(url)s,
                source_credit = %(credit)s, source_licence_url = %(licence_url)s
            where id = %(id)s
            """,
            {"id": document_id, **_details(source)},
        )


def _credit(source: dict[str, Any]) -> str:
    """The credit shown with a Demo Document, as its licence asks."""
    credit = f"{source['credit'].rstrip('.')}. Licence: {source['licence']}."
    if source["licence"].startswith("Open Government"):
        credit += f" {OGL_STATEMENT}"
    else:
        credit += " Adapted: converted to Markdown, images and links removed."
    return credit


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
