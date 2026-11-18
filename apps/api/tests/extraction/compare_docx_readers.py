"""Compares Word (.docx) readers on what Docent needs (the Word numbers in ADR 0011).

    uv run --with mammoth --with docx2python python tests/extraction/compare_docx_readers.py

Each reader turns a document into lines, marking headings with their level ("# Title"), and is
checked for: heading levels from Word's styles, table rows kept as rows, text inside content
controls, and text inside nested tables. The documents are the two in `files/` plus one built
in memory with a content control and a nested table (see test_extraction.py).
"""

import io
import re
import sys
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

from test_extraction import docx_with_content_control_and_nested_table  # noqa: E402

from docent_api.extraction import extract_docx  # noqa: E402

FILES = HERE / "files"


def docent_lines(data: bytes) -> list[str]:
    return [
        ("#" * (block.heading_level or 0) + " " if block.heading_level else "") + block.text
        for block in extract_docx(data)
    ]


def mammoth_lines(data: bytes) -> list[str]:
    import mammoth

    html = mammoth.convert_to_html(io.BytesIO(data)).value
    lines = []
    for tag, body in re.findall(r"<(h\d|p|tr)>(.*?)</\1>", html):
        cells = re.findall(r"<td>(.*?)</td>", body)
        text = " | ".join(re.sub(r"<[^>]+>", "", c) for c in cells) if cells else body
        text = re.sub(r"<[^>]+>", "", text)
        lines.append(("#" * int(tag[1]) + " " if tag.startswith("h") else "") + text)
    return lines


def docx2python_lines(data: bytes) -> list[str]:
    from docx2python import docx2python

    with docx2python(io.BytesIO(data), html=True) as result:
        lines = []
        for table in result.body:
            for row in table:
                cells = ["".join(paragraphs).strip() for paragraphs in row]
                text = " | ".join(c for c in cells if c)
                match = re.match(r"<h(\d)>(.*)</h\1>", text)
                if match:
                    text = "#" * int(match.group(1)) + " " + match.group(2)
                lines.append(re.sub(r"<[^>]+>", "", text))
        return lines


READERS: dict[str, Callable[[bytes], list[str]]] = {
    "python-docx (Docent)": docent_lines,
    "mammoth": mammoth_lines,
    "docx2python": docx2python_lines,
}

CHECKS = {
    "heading levels": ("holiday-guidance.docx", "## Days per Week"),
    "table rows": ("holiday-guidance.docx", "Beckie | 6 | 28.0 days"),
    "content controls": ("built", "Inside a content control"),
    "nested tables": ("built", "Nested"),
    # Real-world files (#36)
    "bold headings": ("reservist-hr-policy-template.docx", "# 1. Introduction"),
    "form table": (
        "early-years-employment-reference-template.docx",
        "Dates employed | From [DD/MM/YYYY] to [DD/MM/YYYY]",
    ),
}


def main() -> None:
    documents = {
        "holiday-guidance.docx": (FILES / "holiday-guidance.docx").read_bytes(),
        "built": docx_with_content_control_and_nested_table(),
        **{
            name: (FILES / name).read_bytes()
            for name in (
                "reservist-hr-policy-template.docx",
                "early-years-employment-reference-template.docx",
            )
        },
    }
    print("| Reader | " + " | ".join(CHECKS) + " |")
    print("| --- |" + " --- |" * len(CHECKS))
    for name, read in READERS.items():
        texts = {doc: "\n".join(read(data)) for doc, data in documents.items()}
        marks = ["yes" if wanted in texts[doc] else "no" for doc, wanted in CHECKS.values()]
        print(f"| {name} | " + " | ".join(marks) + " |")


if __name__ == "__main__":
    main()
