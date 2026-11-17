"""Extraction quality on real-world files (tests/extraction/files, see SOURCES.md)."""

import io
import re
import sys
import time
from pathlib import Path

import pypdfium2
import pytest

from docent_api import extraction
from docent_api.chunking import Block, Chunk, chunk_blocks, clean_text
from docent_api.extraction import UnreadableDocument, _Line, extract_docx, extract_pdf

EXTRACTION = Path(__file__).parent / "extraction"
FILES = EXTRACTION / "files"
sys.path.insert(0, str(EXTRACTION))

from expectations import CHECKS, DPR, HOLIDAY, STAFFING, Check, passes  # noqa: E402


def pdf_blocks(name: str) -> list[Block]:
    return extract_pdf((FILES / name).read_bytes())


def pages(blocks: list[Block]) -> list[str]:
    """Each page's text, headings included, in reading order."""
    count = max((b.page or 0) for b in blocks)
    return ["\n".join(b.text for b in blocks if b.page == page) for page in range(1, count + 1)]


def chunk_with(chunks: list[Chunk], text: str) -> Chunk:
    return next(chunk for chunk in chunks if text in chunk.content)


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: f"{c.file}:{c.page}:{c.kind}")
def test_text_is_whole_in_order_and_on_its_page(check: Check) -> None:
    assert passes(check, pages(pdf_blocks(check.file)))


def test_passages_carry_their_headings_and_page() -> None:
    chunks = chunk_blocks(pdf_blocks(HOLIDAY))

    beckie = chunk_with(chunks, "Beckie’s statutory leave entitlement is 28.0 days")

    assert beckie.page == 9
    path = list(beckie.heading_path)
    assert path[0] == "HOLIDAY ENTITLEMENT"  # the cover title stays above every chapter
    assert path.index("1 Calculating Leave for a Full Leave Year") < path.index("Days per Week")


def test_heading_levels_follow_the_document() -> None:
    chunks = chunk_blocks(pdf_blocks(STAFFING))

    acas = chunk_with(chunks, "Acas Helpline on 0300 123 1100")

    assert (acas.page, acas.heading_path) == (4, ("Introduction", "About this guidance"))


def test_running_headers_and_page_numbers_are_dropped() -> None:
    blocks = pdf_blocks(HOLIDAY)

    assert not [b for b in blocks if b.text == str(b.page)]
    assert not [b for b in blocks if b.text == "Holiday Entitlement Guidance"]


def test_words_hyphenated_at_line_ends_are_rejoined() -> None:
    text = "\n".join(pages(pdf_blocks(DPR)))

    assert "a very reasonable strategy" in text
    assert "\x02" not in text


def test_every_pdf_passage_names_a_page() -> None:
    for name in (DPR, HOLIDAY, STAFFING):
        assert all(chunk.page for chunk in chunk_blocks(pdf_blocks(name)))


def test_a_300_page_pdf_is_read_well_inside_a_batch() -> None:
    source = pypdfium2.PdfDocument(FILES / STAFFING)
    long = pypdfium2.PdfDocument.new()
    while len(long) < 300:
        long.import_pages(source, list(range(min(len(source), 300 - len(long)))))
    buffer = io.BytesIO()
    long.save(buffer)

    start = time.perf_counter()
    blocks = extract_pdf(buffer.getvalue())
    seconds = time.perf_counter() - start

    assert max(b.page or 0 for b in blocks) == 300
    assert seconds < 60  # a batch has about 200 seconds; locally this takes about 10


def test_a_broken_pdf_is_unreadable() -> None:
    with pytest.raises(UnreadableDocument, match="damaged or incomplete"):
        extract_pdf(b"%PDF-1.7 this is not really a PDF")


BAD = FILES / "bad"


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("password.pdf", "This PDF is password-protected."),
        ("damaged.pdf", "This PDF is damaged or incomplete"),
        ("scanned.pdf", "This PDF is made of pictures of pages"),
    ],
)
def test_each_kind_of_bad_pdf_has_its_own_reason(name: str, reason: str) -> None:
    with pytest.raises(UnreadableDocument) as raised:
        extract_pdf((BAD / name).read_bytes())

    assert str(raised.value).startswith(reason)


@pytest.mark.parametrize("name", ["old.doc renamed.docx", "locked.docx"])
def test_old_or_locked_word_files_have_their_own_reason(name: str) -> None:
    # An old .doc renamed to .docx and a password-protected .docx are both Compound Files.
    with pytest.raises(UnreadableDocument, match="old-format Word file"):
        extract_docx((BAD / "old-word.doc").read_bytes())


def pdf_of(*sources: tuple[Path, int]) -> bytes:
    """A PDF made of the given (file, page index) pages, in order."""
    document = pypdfium2.PdfDocument.new()
    for path, index in sources:
        document.import_pages(pypdfium2.PdfDocument(path), [index])
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_a_mostly_scanned_pdf_counts_as_scanned() -> None:
    scan, text = BAD / "scanned.pdf", FILES / "fit-note-checklist.pdf"

    with pytest.raises(UnreadableDocument, match="made of pictures of pages"):
        extract_pdf(pdf_of((scan, 0), (scan, 0), (text, 0)))
    assert extract_pdf(pdf_of((text, 0), (text, 0), (scan, 0)))  # mostly text: read it


def test_a_pdf_with_no_text_and_no_pictures_is_not_called_a_scan() -> None:
    document = pypdfium2.PdfDocument.new()
    document.new_page(612, 792)
    buffer = io.BytesIO()
    document.save(buffer)

    assert extract_pdf(buffer.getvalue()) == []  # ingestion reports "No text was found"


def test_word_documents_over_the_page_limit_are_refused() -> None:
    import zipfile

    source = (FILES / "staffing-guidance.docx").read_bytes()
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source)) as old, zipfile.ZipFile(out, "w") as new:
        for item in old.infolist():
            data = old.read(item.filename)
            if item.filename == "docProps/app.xml":
                data = re.sub(rb"<Pages>\d+</Pages>", b"<Pages>301</Pages>", data)
                if b"<Pages>" not in data:
                    data = data.replace(b"</Properties>", b"<Pages>301</Pages></Properties>")
            new.writestr(item, data)

    with pytest.raises(UnreadableDocument, match="301 pages; the limit is 300"):
        extract_docx(out.getvalue())


# --- Word ---------------------------------------------------------------------------------


def test_word_headings_tables_and_order() -> None:
    chunks = chunk_blocks(extract_docx((FILES / "holiday-guidance.docx").read_bytes()))

    table = chunk_with(chunks, "Beckie | 6 | 28.0 days")

    assert table.heading_path == (
        "Holiday Entitlement",
        "1 Calculating Leave for a Full Leave Year",
        "Days per Week",
    )
    assert table.content.index("Andrew | 4 | 22.4 days") < table.content.index(
        "Therefore, Beckie’s statutory leave entitlement"
    )
    assert table.page is None
    last = chunk_with(chunks, "pro-rated to their time in employment")
    assert last.heading_path[-1].startswith("2 Calculating Leave for Somebody Starting")


def test_word_lists_and_merged_cells() -> None:
    blocks = extract_docx((FILES / "staffing-guidance.docx").read_bytes())
    texts = [b.text for b in blocks]

    assert "Teachers have to be given a written appraisal report." in texts
    assert texts.count("Applies to all staff") == 1
    assert "Childcare disqualification | Staff in relevant childcare" in texts


def test_a_broken_word_document_is_unreadable() -> None:
    with pytest.raises(UnreadableDocument, match="Word document couldn\u2019t be opened"):
        extract_docx(b"PK this is not a real docx")


def test_text_is_cleaned_for_storage() -> None:
    assert clean_text("a\x00b\x01c\td\ne") == "abc\td\ne"
    assert clean_text("\ud835\udc65 + 1") == "\U0001d465 + 1"  # a split maths letter, rejoined
    assert clean_text("lone \ud835 half") == "lone \ufffd half"


def test_pdf_passages_have_no_control_characters() -> None:
    chunks = chunk_blocks(pdf_blocks(DPR))  # its equations produce unmapped glyphs

    assert not [c for c in chunks if re.search(r"[\x00-\x08\x0b-\x1f]", c.content)]


def line(text: str, page: int) -> _Line:
    return _Line(page, chars=list(text), sizes=[10.0] * len(text))


def test_similar_lines_at_page_tops_are_not_mistaken_for_running_headers() -> None:
    pages = [
        [
            line("Guide to leave", n),
            line(f"Question {n}", n),
            line(f"Body text {n}.", n),
            line(str(n), n),
        ]
        for n in range(1, 7)
    ]

    kept = extraction._without_running_headers(pages)

    assert [ln.text for ln in kept[0]] == ["Question 1", "Body text 1."]


def test_a_lone_number_at_a_page_edge_stays_when_pages_arent_numbered() -> None:
    pages = [
        [line("Body text.", n), line("Total", n), line("42" if n == 2 else "end", n)]
        for n in range(1, 7)
    ]

    kept = extraction._without_running_headers(pages)

    assert "42" in [ln.text for ln in kept[1]]


def test_pdfs_over_the_page_limit_are_refused() -> None:
    document = pypdfium2.PdfDocument.new()
    for _ in range(extraction.MAX_PAGES + 1):
        document.new_page(612, 792)
    buffer = io.BytesIO()
    document.save(buffer)

    with pytest.raises(UnreadableDocument, match="301 pages; the limit is 300"):
        extract_pdf(buffer.getvalue())


def docx_with_content_control_and_nested_table() -> bytes:
    from docx import Document
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    document = Document()
    document.add_heading("Policy", level=1)
    control = parse_xml(
        f"<w:sdt {nsdecls('w')}><w:sdtContent><w:p><w:r>"
        "<w:t>Inside a content control</w:t></w:r></w:p></w:sdtContent></w:sdt>"
    )
    document.element.body.insert(1, control)
    outer = document.add_table(rows=1, cols=2)
    outer.cell(0, 0).text = "Outer"
    inner = outer.cell(0, 1).add_table(rows=1, cols=2)
    inner.cell(0, 0).text = "Nested"
    inner.cell(0, 1).text = "cells"
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_word_content_controls_and_nested_tables_are_read() -> None:
    texts = [b.text for b in extract_docx(docx_with_content_control_and_nested_table())]

    assert texts.index("Policy") < texts.index("Inside a content control")
    assert any("Outer" in t and "Nested" in t and "cells" in t for t in texts)


def test_word_documents_that_unpack_too_large_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extraction, "MAX_UNPACKED_BYTES", 1000)

    with pytest.raises(UnreadableDocument, match="too large to read once unpacked"):
        extract_docx((FILES / "holiday-guidance.docx").read_bytes())
