"""Extraction quality on real-world files (tests/extraction/files, see SOURCES.md)."""

import io
import sys
import time
from pathlib import Path

import pypdfium2
import pytest

from docent_api.chunking import Block, Chunk, chunk_blocks
from docent_api.extraction import UnreadableDocument, extract_docx, extract_pdf

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
    with pytest.raises(UnreadableDocument, match="couldn't be opened"):
        extract_pdf(b"%PDF-1.7 this is not really a PDF")


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
    with pytest.raises(UnreadableDocument, match="Word document couldn't be opened"):
        extract_docx(b"PK this is not a real docx")
