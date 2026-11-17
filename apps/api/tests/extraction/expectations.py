"""What correct text extraction looks like for the real-world files in `files/`.

Each check is a passage a reader of the document would find on a given page. Text is compared
after collapsing whitespace, so line breaks inside a passage don't matter, but words must be
whole, in reading order, and on the right page. The checks are chosen to catch the common
failures: columns read across instead of down, table rows broken apart, footnotes or running
headers spliced into sentences, and text attributed to the wrong page.

Used by `compare_parsers.py` (choosing a parser, ADR 0011) and `test_extraction.py` (CI).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

DPR = "dense-passage-retrieval.pdf"
HOLIDAY = "holiday-entitlement-guidance.pdf"
FIT_NOTE = "fit-note-checklist.pdf"
STAFFING = "staffing-guidance-for-schools.pdf"


@dataclass(frozen=True)
class OnPage:
    """`text` appears, whole, on `page` (1-based)."""

    file: str
    page: int
    text: str
    kind: str = "text"


@dataclass(frozen=True)
class InOrder:
    """Each of `texts` appears on `page`, in this order."""

    file: str
    page: int
    texts: tuple[str, ...]
    kind: str = "reading order"


Check = OnPage | InOrder

CHECKS: tuple[Check, ...] = (
    # Two columns: a sentence that wraps inside the left column, then the right column.
    OnPage(
        DPR,
        1,
        "Although reducing open-domain QA to machine reading is a very reasonable strategy",
        "columns",
    ),
    OnPage(
        DPR, 1, "Retrieval in open-domain QA is usually implemented using TF-IDF or BM25", "columns"
    ),
    InOrder(
        DPR,
        1,
        (
            "Open-domain question answering relies on efficient passage retrieval",
            "1 Introduction",
            "indicating the needs of improving retrieval",
            "Retrieval in open-domain QA is usually implemented",
        ),
        "columns",
    ),
    # Tables: each row's cells stay together and in order.
    OnPage(DPR, 4, "Natural Questions 79,168 58,880 8,757 3,610", "table"),
    OnPage(DPR, 5, "None BM25 59.1 66.9 55.0 70.9 68.8 73.7 76.7 71.1 84.1 80.0", "table"),
    OnPage(DPR, 5, "Single DPR 78.4 79.4 73.2 79.8 63.2 85.4 85.0 81.4 89.1 77.2", "table"),
    # Plain guidance prose across many pages.
    OnPage(
        HOLIDAY,
        4,
        "Holiday legislation grants almost all workers 5.6 weeks paid annual leave a year.",
    ),
    OnPage(HOLIDAY, 9, "Therefore, Beckie’s statutory leave entitlement is 28.0 days."),
    OnPage(HOLIDAY, 15, "Therefore, Kirsty’s statutory leave entitlement is 84 hours."),
    # Footnotes come after the body text, not inside it.
    InOrder(
        HOLIDAY,
        12,
        (
            "Workers in the first 12 months in a job",
            "If a worker leaves prior to the end of the leave year",
            "6 The legislation does not state whether the start of a month",
        ),
    ),
    # A checklist laid out with tick boxes.
    InOrder(
        FIT_NOTE,
        1,
        (
            "Fit Note: Checklist for Employers",
            "Check if your employee ‘may be fit for work,’ discuss their fit note with them",
            "Consider taking a copy of the fit note for your records",
            "If you receive an old template (Med3 2017)",
        ),
        "layout",
    ),
    # A long document.
    OnPage(
        STAFFING,
        4,
        "An index of Acas’s employer advice is available and any employer can contact the Acas "
        "Helpline on 0300 123 1100",
    ),
    OnPage(
        STAFFING,
        22,
        "Teachers’ performance must be assessed against their objectives and the relevant "
        "standards.",
    ),
)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def passes(check: Check, pages: Sequence[str]) -> bool:
    """Whether `pages` (one string per page) satisfy `check`."""
    if check.page > len(pages):
        return False
    page = normalize(pages[check.page - 1])
    if isinstance(check, OnPage):
        return normalize(check.text) in page
    position = 0
    for text in check.texts:
        wanted = normalize(text)
        found = page.find(wanted, position)
        if found < 0:
            return False
        position = found + len(wanted)
    return True
