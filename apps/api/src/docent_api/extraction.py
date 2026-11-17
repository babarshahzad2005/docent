"""Reading PDF and Word Documents into blocks of text with headings and page numbers.

PDFs are read with PDFium (pypdfium2), chosen in ADR 0011 for keeping columns and tables in
reading order and for speed (about 300 pages a second). A PDF has no paragraph or heading
markup, so they are reconstructed from the text's layout:

- Headings are lines set larger than the body text, or entirely in bold. Larger sizes are higher
  levels. A heading that wraps onto several lines is one heading.
- Running headers and footers (a title or page number repeated at the top or bottom of most
  pages) are dropped, so they don't interrupt passages.
- Words hyphenated at a line end, which PDFium marks, are joined back together.
- Lines are joined into paragraphs, broken where a line ends a sentence well short of the
  margin or the vertical gap is wider than usual.

Word documents carry their own structure: Heading styles give headings, and tables are read row
by row in document order. Word has no fixed pages, so their blocks have no page number.
"""

import ctypes
import io
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import pairwise

import pypdfium2
import pypdfium2.raw as pdfium_c

from docent_api.chunking import Block

HEADING_SIZE_RATIO = 1.15
MAX_HEADING_CHARS = 150
MAX_HEADING_LEVELS = 6
BOLD_WEIGHT = 600
_SOFT_HYPHEN = 2  # PDFium's marker for a hyphen it inserted at a line break
_SENTENCE_END = re.compile("[.!?:;\u2026\u201d\u2019\"')]$")
_BOLD_AT_BODY_SIZE = -1.0  # key in the level map for bold headings at body size
_LETTER = re.compile(r"[^\W\d_]")


class UnreadableDocument(Exception):
    """The file can't be opened as the type it claims to be; the message is for the User."""


@dataclass
class _Line:
    page: int
    chars: list[str] = field(default_factory=list)
    sizes: list[float] = field(default_factory=list)
    bold: list[bool] = field(default_factory=list)
    left: float = float("inf")
    right: float = float("-inf")
    top: float = float("-inf")
    bottom: float = float("inf")

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self.chars)).strip()

    @property
    def size(self) -> float:
        return round(sorted(self.sizes)[len(self.sizes) // 2] * 2) / 2 if self.sizes else 0.0

    @property
    def is_bold(self) -> bool:
        return bool(self.bold) and sum(self.bold) >= 0.9 * len(self.bold)

    @property
    def height(self) -> float:
        return max(self.top - self.bottom, 0.0)


# --- PDF ----------------------------------------------------------------------------------


def extract_pdf(data: bytes) -> list[Block]:
    """The text of a PDF as headings and paragraphs, each with its 1-based page number."""
    try:
        document = pypdfium2.PdfDocument(data)
    except pypdfium2.PdfiumError as error:
        raise UnreadableDocument(
            "This PDF couldn't be opened. Check that it opens on your computer and isn't "
            "password-protected."
        ) from error
    try:
        pages = [_page_lines(document[index], index + 1) for index in range(len(document))]
    finally:
        document.close()
    pages = _without_running_headers(pages)
    lines = [line for page in pages for line in page]
    body_size = _body_size(lines)
    levels = _heading_levels(lines, body_size)
    return list(_blocks(pages, body_size, levels))


def _page_lines(page: pypdfium2.PdfPage, number: int) -> list[_Line]:
    textpage = page.get_textpage()
    fonts = _Fonts(textpage)
    try:
        lines: list[_Line] = []
        line = _Line(number)
        join_next = False
        for index in range(textpage.count_chars()):
            code = pdfium_c.FPDFText_GetUnicode(textpage.raw, index)
            if code == _SOFT_HYPHEN:
                join_next = True
                continue
            if code == 13:
                continue
            if code == 10:
                if join_next:
                    join_next = False
                    continue
                lines.append(line)
                line = _Line(number)
                continue
            join_next = False
            character = chr(code)
            line.chars.append(character)
            if character.isspace():
                continue
            # The glyph box's height is the size as printed; the font size alone ignores scaling.
            _, low, _, high = textpage.get_charbox(index, loose=True)
            line.sizes.append(high - low)
            line.bold.append(fonts.is_bold(index))
            left, bottom, right, top = textpage.get_charbox(index)
            line.left, line.right = min(line.left, left), max(line.right, right)
            line.top, line.bottom = max(line.top, top), min(line.bottom, bottom)
        lines.append(line)
        return [line for line in lines if line.text]
    finally:
        textpage.close()
        page.close()


class _Fonts:
    """Whether characters are bold, from the font's weight or its name ("Arial-BoldMT")."""

    def __init__(self, textpage: pypdfium2.PdfTextPage) -> None:
        self._raw = textpage.raw
        self._buffer = ctypes.create_string_buffer(128)
        self._flags = ctypes.c_int()

    def is_bold(self, index: int) -> bool:
        if pdfium_c.FPDFText_GetFontWeight(self._raw, index) >= BOLD_WEIGHT:
            return True
        pdfium_c.FPDFText_GetFontInfo(
            self._raw, index, self._buffer, len(self._buffer), ctypes.byref(self._flags)
        )
        name = self._buffer.value.lower()
        return b"bold" in name or b"black" in name or b"heavy" in name


def _repeat_key(text: str) -> str:
    return re.sub(r"\d+", "#", text.lower())


def _without_running_headers(pages: list[list[_Line]]) -> list[list[_Line]]:
    """Drop lines repeated at the top or bottom of most pages, and bare page numbers there."""
    edge = 2
    counts: Counter[str] = Counter()
    for lines in pages:
        counts.update({_repeat_key(line.text) for line in lines[:edge] + lines[-edge:]})
    threshold = max(3, len(pages) // 2)
    repeated = {key for key, count in counts.items() if count >= threshold}

    def is_running(line: _Line) -> bool:
        return _repeat_key(line.text) in repeated or line.text.isdigit()

    cleaned = []
    for lines in pages:
        head = [line for line in lines[:edge] if not is_running(line)]
        tail = [line for line in lines[edge:][-edge:] if not is_running(line)]
        middle = lines[edge : max(edge, len(lines) - edge)]
        cleaned.append(head + middle + tail if len(lines) > edge else head)
    return cleaned


def _body_size(lines: list[_Line]) -> float:
    sizes: Counter[float] = Counter()
    for line in lines:
        sizes[line.size] += len(line.text)
    return sizes.most_common(1)[0][0] if sizes else 0.0


def _looks_like_heading(line: _Line, body_size: float) -> bool:
    text = line.text
    letters = len(_LETTER.findall(text))
    if len(text) > MAX_HEADING_CHARS or letters < 3 or body_size <= 0:
        return False
    if line.size >= body_size * HEADING_SIZE_RATIO:
        return True
    return line.is_bold and line.size >= body_size * 0.95 and not _SENTENCE_END.search(text)


def _heading_levels(lines: list[_Line], body_size: float) -> dict[float, int]:
    """Heading level by size: the largest size used for headings inside the Document is 1.

    Sizes used only on the first page (a cover title) are level 1 too, so they don't push the
    Document's own headings down a level. A size used for just one line after the first page
    (a chart label, a pull quote) isn't a heading size at all. Bold headings at body size come
    after every larger size.
    """
    inside: Counter[float] = Counter()
    cover: set[float] = set()
    for line in lines:
        if _looks_like_heading(line, body_size) and line.size >= body_size * HEADING_SIZE_RATIO:
            if line.page == 1:
                cover.add(line.size)
            else:
                inside[line.size] += 1
    sizes = sorted((size for size, count in inside.items() if count >= 2), reverse=True)
    levels = {size: min(index + 1, MAX_HEADING_LEVELS) for index, size in enumerate(sizes)}
    for size in cover - levels.keys():
        levels[size] = 1
    levels[_BOLD_AT_BODY_SIZE] = min(len(sizes) + 1, MAX_HEADING_LEVELS)
    return levels


def _level(line: _Line, body_size: float, levels: dict[float, int]) -> int | None:
    """The line's heading level, or None if it's body text."""
    if not _looks_like_heading(line, body_size):
        return None
    if line.size >= body_size * HEADING_SIZE_RATIO:
        return levels.get(line.size)
    return levels[_BOLD_AT_BODY_SIZE]


class _PageReader:
    """Groups one page's lines into heading and paragraph Blocks."""

    def __init__(self, lines: list[_Line], body_size: float, levels: dict[float, int]) -> None:
        self.lines = lines
        self.body_size = body_size
        self.levels = levels
        self.margin = max(line.right for line in lines)
        self.typical_gap = _typical_gap(lines)
        self.heading: list[_Line] = []
        self.heading_level: int | None = None
        self.paragraph: list[_Line] = []

    def blocks(self) -> Iterator[Block]:
        for line in self.lines:
            level = _level(line, self.body_size, self.levels)
            if level is None:
                yield from self._end_heading()
                if self.paragraph and _ends_paragraph(
                    self.paragraph[-1], line, self.margin, self.typical_gap
                ):
                    yield from self._end_paragraph()
                self.paragraph.append(line)
                continue
            yield from self._end_paragraph()
            if not self._continues_heading(line):
                yield from self._end_heading()
            self.heading_level = level
            self.heading.append(line)
        yield from self._end_heading()
        yield from self._end_paragraph()

    def _continues_heading(self, line: _Line) -> bool:
        """A heading wrapped onto the next line: same size, no more than a line apart."""
        if not self.heading:
            return False
        previous = self.heading[-1]
        return previous.size == line.size and _gap(previous, line) <= self.typical_gap + line.height

    def _end_heading(self) -> Iterator[Block]:
        if self.heading:
            text = " ".join(line.text for line in self.heading)
            yield Block(text, self.heading_level, self.heading[0].page)
            self.heading = []

    def _end_paragraph(self) -> Iterator[Block]:
        if self.paragraph:
            yield Block(
                " ".join(line.text for line in self.paragraph), None, self.paragraph[0].page
            )
            self.paragraph = []


def _blocks(
    pages: list[list[_Line]], body_size: float, levels: dict[float, int]
) -> Iterator[Block]:
    for lines in pages:
        if lines:
            yield from _PageReader(lines, body_size, levels).blocks()


def _gap(above: _Line, below: _Line) -> float:
    return above.bottom - below.top


def _typical_gap(lines: list[_Line]) -> float:
    gaps = sorted(gap for above, below in pairwise(lines) if (gap := _gap(above, below)) >= 0)
    return gaps[len(gaps) // 2] if gaps else 0.0


def _ends_paragraph(previous: _Line, line: _Line, margin: float, typical_gap: float) -> bool:
    """A new paragraph starts after a short line that ends a sentence, or a wide gap."""
    short = previous.right < margin - 0.15 * max(margin - previous.left, 1.0)
    if short and _SENTENCE_END.search(previous.text):
        return True
    gap = _gap(previous, line)
    return gap > max(typical_gap * 1.8, previous.height * 0.8) or line.top > previous.top + 1


# --- Word ---------------------------------------------------------------------------------


def extract_docx(data: bytes) -> list[Block]:
    """The text of a Word document as headings, paragraphs, and table rows, in order."""
    from docx import Document as open_docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = open_docx(io.BytesIO(data))
    except Exception as error:  # python-docx raises several unrelated types for bad files
        raise UnreadableDocument(
            "This Word document couldn't be opened. Check that it opens in Word and is saved "
            "as .docx."
        ) from error
    blocks: list[Block] = []
    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            blocks.append(Block(item.text, _docx_heading_level(item)))
        elif isinstance(item, Table):
            blocks.extend(Block(row) for row in _table_rows(item))
    return blocks


def _docx_heading_level(paragraph: object) -> int | None:
    """Title is level 0 (above every heading); Heading 1 to 9 are levels 1 to 9."""
    style = getattr(paragraph, "style", None)
    while style is not None:
        name = (style.name or "").strip().lower()
        if name == "title":
            return 0
        match = re.fullmatch(r"heading (\d)", name)
        if match:
            return int(match.group(1))
        style = style.base_style
    return None


def _table_rows(table: object) -> Iterator[str]:
    """Each row's cells joined in order; a merged cell appears once."""
    for row in getattr(table, "rows", []):
        cells: list[str] = []
        seen: set[int] = set()
        for cell in row.cells:
            if id(cell._tc) in seen:
                continue
            seen.add(id(cell._tc))
            text = re.sub(r"\s+", " ", cell.text).strip()
            if text:
                cells.append(text)
        if cells:
            yield " | ".join(cells)
