"""Splitting a Document's text into chunks: passages small enough to retrieve and cite.

Chunks follow the Document's structure. Each one stays inside a single section and carries the
headings above it, so a passage like "Up to 10 days carry over" keeps the context "Leave policy
> Carry-over" that makes it findable and understandable on its own. Paragraphs are packed
together up to a target size and split only when a single paragraph is too long.
"""

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass

TARGET_CHARS = 1000
MAX_CHARS = 1600

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t#]*$")
_FENCE = re.compile(r"^[ \t]{0,3}(```|~~~)")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    heading_path: tuple[str, ...]
    content: str

    @property
    def text_for_embedding(self) -> str:
        """The passage with its headings, which is what retrieval should match against."""
        if not self.heading_path:
            return self.content
        return " > ".join(self.heading_path) + "\n\n" + self.content

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text_for_embedding.encode()).hexdigest()


@dataclass(frozen=True)
class _Section:
    heading_path: tuple[str, ...]
    text: str


def chunk_markdown(text: str) -> list[Chunk]:
    """Chunks of a Markdown Document, following its `#` headings."""
    return _pack(_markdown_sections(_strip_front_matter(_normalize(text))))


def chunk_plain_text(text: str) -> list[Chunk]:
    """Chunks of a plain text Document, which has paragraphs but no headings."""
    return _pack([_Section((), _normalize(text))])


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")


def _strip_front_matter(text: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[end + 5 :]
    return text


def _markdown_sections(text: str) -> list[_Section]:
    sections: list[_Section] = []
    path: list[tuple[int, str]] = []
    lines: list[str] = []
    in_fence = False

    def flush() -> None:
        sections.append(_Section(tuple(title for _, title in path), "\n".join(lines)))
        lines.clear()

    for line in text.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
        heading = None if in_fence else _HEADING.match(line)
        if heading is None:
            lines.append(line)
            continue
        flush()
        level, title = len(heading.group(1)), heading.group(2).strip()
        while path and path[-1][0] >= level:
            path.pop()
        path.append((level, title))
    flush()
    return sections


def _pack(sections: list[_Section]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section in sections:
        for content in _pack_paragraphs(_pieces(section.text)):
            chunks.append(Chunk(len(chunks), section.heading_path, content))
    return chunks


def _pieces(text: str) -> Iterator[str]:
    """Paragraphs no longer than MAX_CHARS, splitting long ones at sentences, then words."""
    for paragraph in re.split(r"\n[ \t]*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= MAX_CHARS:
            yield paragraph
            continue
        yield from _pack_paragraphs(_short(_SENTENCE_END.split(paragraph)), separator=" ")


def _short(sentences: list[str]) -> Iterator[str]:
    for sentence in sentences:
        while len(sentence) > MAX_CHARS:
            cut = sentence.rfind(" ", 0, MAX_CHARS)
            cut = cut if cut > 0 else MAX_CHARS
            yield sentence[:cut].strip()
            sentence = sentence[cut:].strip()
        if sentence:
            yield sentence


def _pack_paragraphs(pieces: Iterator[str], separator: str = "\n\n") -> Iterator[str]:
    """Join consecutive pieces until the next would pass the target size."""
    current = ""
    for piece in pieces:
        candidate = f"{current}{separator}{piece}" if current else piece
        if current and (len(current) >= TARGET_CHARS or len(candidate) > MAX_CHARS):
            yield current
            current = piece
        else:
            current = candidate
    if current:
        yield current
