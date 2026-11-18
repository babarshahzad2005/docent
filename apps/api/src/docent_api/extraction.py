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
import zipfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

import pypdfium2
import pypdfium2.raw as pdfium_c

from docent_api.chunking import Block

MAX_PAGES = 300  # per Document (PRD, Constraints)
MAX_UNPACKED_BYTES = 200 * 1024 * 1024  # a .docx is a zip; refuse ones that unpack to more
HEADING_SIZE_RATIO = 1.15
MAX_HEADING_CHARS = 150
MAX_HEADING_LEVELS = 6
BOLD_WEIGHT = 600
_EDGE_LINES = 2  # lines at the top and bottom of a page where running headers sit
_SOFT_HYPHEN = 2  # PDFium's marker for a hyphen it inserted at a line break
_CARRIAGE_RETURN, _LINE_FEED = 13, 10
_PAGE_NUMBER = re.compile(
    r"(page\s+)?\d+(\s*(of|/)\s*\d+)?|[-\u2013\u2014]\s*\d+\s*[-\u2013\u2014]", re.IGNORECASE
)
_SENTENCE_END = re.compile("[.!?:;\u2026\u201d\u2019\"')]$")
_BOLD_AT_BODY_SIZE = -1.0  # key in the level map for bold headings at body size
_LETTER = re.compile(r"[^\W\d_]")


_PASSWORD_PDF = (
    "This PDF is password-protected. Save a copy without the password (in most PDF readers, "
    "print it to PDF) and upload that."
)
_DAMAGED_PDF = (
    "This PDF is damaged or incomplete, so it can\u2019t be read. Check that it opens on your "
    "computer, save a fresh copy, and upload that."
)
_SCANNED_PDF = (
    "This PDF is made of pictures of pages (a scan or photos), so it has no text Docent can "
    "read. Upload a version with selectable text, or run it through text recognition (OCR) "
    "first."
)
_OLD_OR_LOCKED_WORD = (
    "This is an old-format Word file (.doc) or a password-protected one. Open it in Word, "
    "remove any password, and save it as .docx."
)
_FPDF_ERR_PASSWORD = 4
_FEW_CHARACTERS = 40  # a page with less text than this is "only a picture" if it has one
_MAX_WORD_PAGES = MAX_PAGES
_COMPOUND_FILE = bytes.fromhex("D0CF11E0A1B11AE1")  # .doc and encrypted .docx start with this


class UnreadableDocument(Exception):
    """The file can't be read as it is; the message tells the User what to do."""


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
        locked = getattr(error, "err_code", None) == _FPDF_ERR_PASSWORD
        raise UnreadableDocument(_PASSWORD_PDF if locked else _DAMAGED_PDF) from error
    try:
        if len(document) > MAX_PAGES:
            raise UnreadableDocument(
                f"This PDF has {len(document)} pages; the limit is {MAX_PAGES} per document. "
                "Split it into smaller files and upload those."
            )
        pages: list[list[_Line]] = []
        pictures = 0
        for index in range(len(document)):
            page = document[index]
            try:
                pages.append(_page_lines(page, index + 1))
                if sum(len(line.text) for line in pages[-1]) < _FEW_CHARACTERS:
                    pictures += _picture_count(page)
            finally:
                page.close()
    finally:
        document.close()
    if pictures * 2 >= len(pages):
        # Half or more of the pages are only pictures: a scan, perhaps with a stamped line.
        raise UnreadableDocument(_SCANNED_PDF)
    pages = _without_running_headers(pages)
    lines = [line for page in pages for line in page]
    body_size = _body_size(lines)
    levels = _heading_levels(lines, body_size)
    return list(_blocks(pages, body_size, levels))


def _page_lines(page: pypdfium2.PdfPage, number: int) -> list[_Line]:
    textpage = None
    try:
        textpage = page.get_textpage()
        fonts = _Fonts(textpage)
        lines: list[_Line] = []
        line = _Line(number)
        join_next = False
        for index in range(textpage.count_chars()):
            code = pdfium_c.FPDFText_GetUnicode(textpage.raw, index)
            if code == _SOFT_HYPHEN:
                join_next = True
                continue
            if code == _CARRIAGE_RETURN:
                continue
            if code == _LINE_FEED:
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
        if textpage is not None:
            textpage.close()


def _picture_count(page: pypdfium2.PdfPage) -> int:
    """1 if the page has a picture on it, else 0."""
    images = page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=8)
    return 1 if any(True for _ in images) else 0


class _Fonts:
    """Whether characters are bold, from the font's weight or its name ("Arial-BoldMT")."""

    def __init__(self, textpage: pypdfium2.PdfTextPage) -> None:
        self._raw = textpage.raw
        self._buffer = ctypes.create_string_buffer(256)
        self._flags = ctypes.c_int()

    def is_bold(self, index: int) -> bool:
        if pdfium_c.FPDFText_GetFontWeight(self._raw, index) >= BOLD_WEIGHT:
            return True
        needed = pdfium_c.FPDFText_GetFontInfo(
            self._raw, index, self._buffer, len(self._buffer), ctypes.byref(self._flags)
        )
        if needed > len(self._buffer):  # PDFium writes nothing when the name doesn't fit
            self._buffer = ctypes.create_string_buffer(needed)
            pdfium_c.FPDFText_GetFontInfo(
                self._raw, index, self._buffer, len(self._buffer), ctypes.byref(self._flags)
            )
        name = self._buffer.value.lower()
        return b"bold" in name or b"black" in name or b"heavy" in name


def _without_running_headers(pages: list[list[_Line]]) -> list[list[_Line]]:
    """Drop running headers and footers from the top and bottom lines of each page.

    A running header is a line repeated word for word at a page edge on at least half the
    pages. Page numbers ("7", "Page 7 of 25", "- 7 -") differ on every page, so they go only
    when most pages have one at an edge; a lone number there (the end of a table) stays.
    Lines that merely look alike ("Question 1", "Question 2") are kept.
    """
    edge = _EDGE_LINES
    counts: Counter[str] = Counter()
    numbered = 0
    for lines in pages:
        edge_lines = lines[:edge] + lines[-edge:]
        counts.update({line.text.lower() for line in edge_lines})
        numbered += any(_PAGE_NUMBER.fullmatch(line.text) for line in edge_lines)
    threshold = max(3, len(pages) // 2)
    repeated = {text for text, count in counts.items() if count >= threshold}
    drop_numbers = numbered >= threshold

    def is_running(line: _Line) -> bool:
        if line.text.lower() in repeated:
            return True
        return drop_numbers and _PAGE_NUMBER.fullmatch(line.text) is not None

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
    """The text of a Word document as headings, paragraphs, and table rows, in order.

    Content controls (common in templates) and nested tables are read too. Text boxes,
    headers, footers, and footnotes are not: they sit outside the document's main flow.
    """
    from docx import Document as open_docx

    _check_unpacked_size(data)
    try:
        document = open_docx(io.BytesIO(data))
    except Exception as error:  # python-docx raises several unrelated types for bad files
        raise UnreadableDocument(
            "This Word document couldn’t be opened. Check that it opens in Word and is saved "
            "as .docx."
        ) from error
    body = document.element.body
    return list(_docx_blocks(body, document._body))


def _word_page_count(data: bytes) -> int | None:
    """The page count Word saved in the file's properties, if it saved one."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            properties = archive.read("docProps/app.xml").decode("utf-8", "replace")
    except (KeyError, zipfile.BadZipFile):
        return None
    match = re.search(r"<Pages>(\d+)</Pages>", properties)
    return int(match.group(1)) if match else None


def _check_unpacked_size(data: bytes) -> None:
    if data.startswith(_COMPOUND_FILE):
        raise UnreadableDocument(_OLD_OR_LOCKED_WORD)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            unpacked = sum(info.file_size for info in archive.infolist())
    except zipfile.BadZipFile as error:
        raise UnreadableDocument(
            "This Word document couldn’t be opened. Check that it opens in Word and is saved "
            "as .docx."
        ) from error
    pages = _word_page_count(data)
    if pages is not None and pages > _MAX_WORD_PAGES:
        raise UnreadableDocument(
            f"This Word document has {pages} pages; the limit is {_MAX_WORD_PAGES} per document. "
            "Split it into smaller files and upload those."
        )
    if unpacked > MAX_UNPACKED_BYTES:
        raise UnreadableDocument(
            "This Word document is too large to read once unpacked. Save it without embedded "
            "media, or split it into smaller files."
        )


def _docx_blocks(element: Any, parent: Any) -> Iterator[Block]:
    """Blocks in document order, looking inside content controls."""
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for child in element.iterchildren():
        if child.tag == qn("w:p"):
            paragraph = Paragraph(child, parent)
            level = _docx_heading_level(paragraph)
            # A heading's tabs and line breaks (after its number, say) are layout, not words.
            text = paragraph.text if level is None else " ".join(paragraph.text.split())
            yield Block(text, level)
        elif child.tag == qn("w:tbl"):
            yield from (Block(row) for row in _table_rows(Table(child, parent)))
        elif child.tag == qn("w:sdt"):
            content = child.find(qn("w:sdtContent"))
            if content is not None:
                yield from _docx_blocks(content, parent)


def _cell_text(cell: Any) -> str:
    """All of a cell's text, including any table nested inside it."""
    return " ".join(block.text for block in _docx_blocks(cell._tc, cell) if block.text.strip())


def _docx_heading_level(paragraph: Any) -> int | None:
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
    return 1 if _looks_like_bold_heading(paragraph) else None


def _looks_like_bold_heading(paragraph: Any) -> bool:
    """Many documents made in Word mark headings with bold text instead of heading styles:
    a short paragraph that is bold throughout and doesn't end like a sentence."""
    text = paragraph.text.strip()
    if not text or len(text) > _MAX_BOLD_HEADING or text[-1] in ".!?:;,":
        return False
    style_bold = bool(getattr(getattr(paragraph.style, "font", None), "bold", False))
    runs = [run for run in paragraph.runs if run.text.strip()]
    return bool(runs) and all(run.bold is True or (run.bold is None and style_bold) for run in runs)


_MAX_BOLD_HEADING = 100


def _table_rows(table: Any) -> Iterator[str]:
    """Each row's cells joined in order; a merged cell appears once."""
    for row in table.rows:
        cells: list[str] = []
        seen: list[Any] = []
        for cell in row.cells:
            if any(cell._tc is element for element in seen):
                continue
            seen.append(cell._tc)
            text = re.sub(r"\s+", " ", _cell_text(cell)).strip()
            if text:
                cells.append(text)
        if cells:
            yield " | ".join(cells)
