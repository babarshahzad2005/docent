"""Compares PDF text extractors on the real-world files in `files/` (the numbers in ADR 0011).

    uv run --with pypdf --with pdfplumber --with pypdfium2 \
        python tests/extraction/compare_parsers.py

Each candidate extracts every page as plain text; the result is scored against
`expectations.CHECKS`, and timed on all four files and on a 300-page document made by repeating
the longest one. Candidates must be licensed for use in an MIT project, so AGPL libraries such as
PyMuPDF are not considered.
"""

import io
import re
import sys
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from expectations import CHECKS, STAFFING, passes  # noqa: E402

FILES = HERE / "files"


def pypdf_pages(data: bytes) -> list[str]:
    import pypdf

    return [page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(data)).pages]


def pdfplumber_pages(data: bytes) -> list[str]:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def pdfminer_pages(data: bytes) -> list[str]:
    from pdfminer.high_level import extract_text

    pages = extract_text(io.BytesIO(data)).split("\f")
    return pages[:-1] if pages and not pages[-1].strip() else pages


def pypdfium2_pages(data: bytes) -> list[str]:
    import pypdfium2

    document = pypdfium2.PdfDocument(data)
    try:
        pages = [document[i].get_textpage().get_text_bounded() for i in range(len(document))]
    finally:
        document.close()
    # PDFium marks a word hyphenated at a line end with \x02; rejoin it, as Docent does.
    return [re.sub(r"\x02\r?\n?", "", page) for page in pages]


CANDIDATES: dict[str, Callable[[bytes], list[str]]] = {
    "pypdf": pypdf_pages,
    "pdfplumber": pdfplumber_pages,
    "pdfminer.six": pdfminer_pages,
    "pypdfium2": pypdfium2_pages,
}


def long_document(pages: int = 300) -> bytes:
    import pypdf

    source = pypdf.PdfReader(FILES / STAFFING)
    writer = pypdf.PdfWriter()
    while len(writer.pages) < pages:
        for page in source.pages:
            if len(writer.pages) < pages:
                writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def main() -> None:
    files = {path.name: path.read_bytes() for path in sorted(FILES.glob("*.pdf"))}
    big = long_document()
    total_pages = 0
    print("| Parser | Checks passed | Columns | Tables | Seconds, 4 files | Seconds, 300 pages |")
    print("| --- | --- | --- | --- | --- | --- |")
    for name, extract in CANDIDATES.items():
        start = time.perf_counter()
        extracted = {file: extract(data) for file, data in files.items()}
        small_seconds = time.perf_counter() - start
        total_pages = sum(len(pages) for pages in extracted.values())
        start = time.perf_counter()
        extract(big)
        big_seconds = time.perf_counter() - start
        results = [(check, passes(check, extracted[check.file])) for check in CHECKS]
        by_kind = Counter(check.kind for check, ok in results if ok)
        totals = Counter(check.kind for check, _ in results)
        failed = [f"{c.file}:{c.page}" for c, ok in results if not ok]
        print(
            f"| {name} | {sum(ok for _, ok in results)}/{len(results)} "
            f"| {by_kind['columns']}/{totals['columns']} | {by_kind['table']}/{totals['table']} "
            f"| {small_seconds:.2f} | {big_seconds:.1f} |"
            + (f" failed: {', '.join(failed)}" if failed else "")
        )
    print(f"\n{total_pages} pages in the test set; median of one run each.")


if __name__ == "__main__":
    main()
