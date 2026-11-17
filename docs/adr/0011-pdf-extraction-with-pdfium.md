# PDFs are read with PDFium (pypdfium2); Word documents with python-docx

Docent extracts PDF text with [pypdfium2](https://github.com/pypdfium2-team/pypdfium2), the Python binding for Google's PDFium (Apache-2.0 or BSD-3-Clause), and Word `.docx` text with [python-docx](https://github.com/python-openxml/python-docx) (MIT). PDFium won on the extraction test set by a wide margin: it was the only candidate to read two-column pages in the right order, it kept every table row intact, and it was about ten times faster than the next one. Libraries under the AGPL, such as PyMuPDF, were excluded because Docent is MIT-licensed, and layout-model pipelines such as Docling were excluded because they need PyTorch, which doesn't fit a Vercel function (ADR 0008).

## Measurements

Taken on 2026-11-17 with `tests/extraction/compare_parsers.py` against four real-world PDFs: 68 pages of GOV.UK guidance and an ACL two-column paper, listed in `tests/extraction/files/SOURCES.md`. Each candidate extracted plain text, which was scored against 13 checks in `tests/extraction/expectations.py`: passages whole and on the right page, columns read down, table rows kept together, and footnotes kept out of sentences. Times are from a modest laptop (Intel i5-7300U). The 300-page document repeats the longest file.

| Parser | Checks passed | Two columns | Tables | 68 pages | 300 pages |
| --- | --- | --- | --- | --- | --- |
| **pypdfium2 5.15** | **13/13** | **3/3** | **3/3** | **0.4 s** | **1.0 s** |
| pypdf 7.1 | 10/13 | 0/3 | 3/3 | 2.5 s | 9.3 s |
| pdfminer.six 20260107 | 7/13 | 0/3 | 0/3 | 5.5 s | 31.8 s |
| pdfplumber 0.11 | 8/13 | 0/3 | 1/3 | 9.2 s | 45.6 s |

PDFium's raw output needs one clean-up step: it marks a word hyphenated at a line end with a control character (`\x02`), so Docent can rejoin "rea-sonable" without also joining real hyphens such as "open-domain". The other candidates leave a plain hyphen, which can't be told apart from a real one. That is part of why they fail the two-column checks.

## What Docent adds on top

A PDF carries no paragraph or heading markup, so `docent_api/extraction.py` rebuilds it from the layout:

- **Headings** are lines printed at least 15% larger than the body text, or entirely in bold. Size is measured from the glyph boxes, because one of the test PDFs reports every character's font size as 1 and scales it on the page. Larger sizes are higher levels. A size used on only one line after the first page (a chart label) doesn't count, and a heading that wraps across lines stays one heading.
- **Running headers and footers** are lines repeated at the top or bottom of at least half the pages, plus bare page numbers there. They are dropped so they don't split passages.
- **Paragraphs** end after a short line that finishes a sentence, or at a wider than usual vertical gap.
- **Pages:** passages never cross a page break, so every PDF passage records the page it came from, which Citations will show.

With these steps the extractor passes all 13 checks plus structural checks (heading paths, dropped running headers, rejoined hyphens) in `tests/test_extraction.py`, which runs in CI. It reads a 300-page PDF in about 9 seconds on the same laptop, well inside one ingestion batch's 200 seconds.

Word documents already carry structure: the Title and Heading 1–9 styles give heading levels, and tables are read row by row with cells joined by " | ", in document order. The two Word test files were built with Word's own styles from the GOV.UK text, because openly licensed real-world `.docx` files are scarce.

## Consequences

- Scanned PDFs (images of text) have nothing to extract and fail with "No text was found". OCR is a v1 non-goal (PRD).
- Heading detection is a heuristic. It fits typical reports and guidance; documents that set headings at body size in regular weight will read as one long section, which still retrieves, just with less context.
- Complex tables are read row by row as text; merged headers and nested tables lose their grid.
- pypdfium2 ships PDFium as a native library of about 6 MB, which fits a Vercel function.
