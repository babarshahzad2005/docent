# PDFs are read with PDFium (pypdfium2); Word documents with python-docx

Docent extracts PDF text with [pypdfium2](https://github.com/pypdfium2-team/pypdfium2), the Python binding for Google's PDFium (Apache-2.0 or BSD-3-Clause), and Word `.docx` text with [python-docx](https://github.com/python-openxml/python-docx) (MIT). PDFium won on the extraction test set: it passed every check, including all three two-column checks, and it was about ten times faster than the runner-up.

Some candidates were ruled out before testing:
- **PyMuPDF and other AGPL libraries**, because Docent is MIT-licensed.
- **Layout-model pipelines such as Docling**, because they need PyTorch, which doesn't fit a Vercel function (ADR 0008).

## PDF measurements

Taken on 2026-11-17 with `apps/api/tests/extraction/compare_parsers.py`. The test set is four real-world PDFs, listed in `tests/extraction/files/SOURCES.md`: 68 pages of GOV.UK guidance and an ACL two-column paper.

Each candidate extracted plain text, which was scored against 13 checks in `tests/extraction/expectations.py`:
- passages whole and on the right page
- columns read down, not across
- table rows kept together
- footnotes kept out of sentences

Words hyphenated at a line end were rejoined for every candidate, each in the best way it allows. PDFium marks the hyphens it inserts with a control character, so only those are joined. The others print a plain hyphen, so any word broken that way is joined, which also wrongly merges real hyphenated words ("open-domain" becomes "opendomain").

Times are for raw text extraction on a modest laptop (Intel i5-7300U). The 300-page document repeats the longest file.

| Parser | Checks passed | Two columns | Tables | 68 pages | 300 pages |
| --- | --- | --- | --- | --- | --- |
| **pypdfium2 5.15** | **13/13** | **3/3** | **3/3** | **0.4 s** | **1.1 s** |
| pypdf 7.1 | 12/13 | 2/3 | 3/3 | 2.7 s | 10.7 s |
| pdfminer.six 20260107 | 9/13 | 2/3 | 0/3 | 5.9 s | 30.1 s |
| pdfplumber 0.11 | 8/13 | 0/3 | 1/3 | 9.7 s | 47.0 s |

pypdf comes close on correctness. PDFium is chosen for the remaining reading-order failure, for its exact hyphen marks, and because its speed leaves room for the layout analysis below.

## What Docent adds on top

A PDF carries no paragraph or heading markup, so `docent_api/extraction.py` rebuilds it from the layout:

- **Headings.**
  - A heading is a line printed at least 15% larger than the body text, or a line entirely in bold.
  - Size is measured from the glyph boxes, because one of the test PDFs reports every character's font size as 1 and scales it on the page.
  - Larger sizes are higher levels.
  - A size used for only one line after the first page (a chart label) doesn't count.
  - A heading that wraps across lines stays one heading.
- **Running headers and footers.** Lines repeated word for word at a page edge on at least half the pages are dropped, so they don't split passages. So are page numbers ("7", "Page 7 of 25"), but only when most pages have one; a lone number at the bottom of one page stays.
- **Paragraphs** end after a short line that finishes a sentence, or at a wider than usual vertical gap.
- **Pages.** Passages never cross a page break, so every PDF passage records the page it came from, which Citations will show.
- **Clean text.** Control characters (PDFium returns them for glyphs with no text equivalent, as in equations) are dropped, because Postgres can't store some of them. Characters split into two UTF-16 halves are rejoined.
- **Limits.** PDFs over 300 pages are refused with a message that says to split them (PRD, Constraints).

With these steps the extractor passes all 13 checks, plus structural checks in `tests/test_extraction.py`, which runs in CI. The structural checks cover heading paths, dropped running headers, rejoined hyphens and clean text. Docent's full extraction of a 300-page PDF takes about 9 seconds on the same laptop, well inside one ingestion batch's 200 seconds.

## Word documents

Word documents already carry structure. The Title and Heading 1–9 styles (including custom styles based on them) give heading levels. Tables are read row by row, with cells joined by " | ", in document order. Content controls and nested tables are read too. Text boxes, headers, footers and footnotes are not, because they sit outside the document's main flow. A `.docx` that would unpack to more than 200 MB is refused.

Three readers were compared with `tests/extraction/compare_docx_readers.py` on the two Word files in the test set, plus one with a content control and a nested table:

| Reader | Heading levels | Table rows | Content controls | Nested tables |
| --- | --- | --- | --- | --- |
| **python-docx 1.2** (MIT) | yes | yes | yes | yes |
| mammoth 1.13 (BSD-2-Clause) | yes | yes | yes | yes |
| docx2python 3.7 | no (through the adapter used) | yes | yes | yes |

mammoth is as capable on these checks. It converts to HTML, though, while python-docx gives direct access to styles (including their inheritance) and to table cells, which is what Docent's rules use.

**Caveat:** openly licensed real-world `.docx` files are scarce, so the Word files were built with python-docx itself, from the GOV.UK text, using Word's built-in styles. They exercise the structure Docent reads, but not the quirks of documents made in Word. Real-world Word files join the test set when the Demo Collection is assembled (#36).

## Consequences

- Scanned PDFs (images of text) have nothing to extract. They fail with a message saying to upload a version with selectable text. OCR is a v1 non-goal (PRD).
- Heading detection is a heuristic. It fits typical reports and guidance. A document that sets headings at body size in regular weight reads as one long section, which still retrieves, just with less context.
- Complex tables are read row by row as text, so merged headers and nested tables lose their grid.
- pypdfium2 ships PDFium as a native library of about 6 MB, which fits a Vercel function. PDFium bundles FreeType, libjpeg-turbo, OpenJPEG, Little CMS and zlib, all under permissive licences. PDFium parses untrusted files in the same process as the API, so its version is kept current through Dependabot.
