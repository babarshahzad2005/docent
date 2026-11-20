"""When Documents disagree (#48): the notice naming each version, newest first.

The prompt gives each passage its Document's Effective Date and asks the model to answer from
the later one when Documents disagree (answers.SYSTEM_PROMPT). After its quotes the model
then lists what each disagreeing passage says:

    Disagreements:
    [4] "12.07% of hours worked"
    [7] "at least 5.6 weeks"

Like the quotes, the list never reaches the reader. Each value is checked against its passage
(it must be in it, as quoted), and a notice is shown only when values from two or more
Documents survive: a table of each value, its Document, and its Effective Date, newest first
(DESIGN.md: Conflict notice). It is recorded with the message and in the Answer Log.
"""

import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from docent_api.retrieval import Passage
from docent_api.verification import _ELLIPSIS, _find_words, _words

DISAGREEMENTS_HEADING = "Disagreements:"

INSTRUCTIONS = f"""- If you said the documents disagree, after the quotes write a line with only \
"{DISAGREEMENTS_HEADING}". Then, for each passage that disagrees, one line with its number \
and the short answer it gives, copied exactly from it, in double quotes, like:
[4] "12.07% of hours worked\""""

_HEADING = re.compile(
    r"(?:^|\n)[ \t]*(?:#{1,6}[ \t]*)?\**[ \t]*disagreements?[ \t]*\**[ \t]*:?[ \t]*\**[ \t]*"
    r"(?=\n|\[\d|$)",
    re.IGNORECASE,
)
_ENTRY = re.compile(r"\[(\d{1,2})\][ \t]*[:\-]?[ \t]*[\"“”](.+?)[\"“”][ \t]*(?=\n|\[|$)")
# What ends the list: the quotes, if the model put them after it.
_NEXT_SECTION = re.compile(r"\n[ \t]*(?:#{1,6}[ \t]*)?\**[ \t]*(?:quotes?|sources?)\b", re.I)


@dataclass(frozen=True)
class Version:
    """One Document's side of a disagreement."""

    number: int  # the passage, as numbered in the answer's sources
    value: str
    document_name: str
    effective_date: str | None  # ISO date


def split_disagreements(raw: str) -> tuple[str, list[tuple[int, str]]]:
    """The reply without its disagreements list, and the list as (passage number, value)."""
    match = _HEADING.search(raw)
    if match is None:
        return raw, []
    end_match = _NEXT_SECTION.search(raw, match.end())
    end = end_match.start() if end_match else len(raw)
    entries = [
        (int(m.group(1)), m.group(2).strip()) for m in _ENTRY.finditer(raw[match.start() : end])
    ]
    return raw[: match.start()] + raw[end:], entries


def notice(entries: Sequence[tuple[int, str]], passages: Sequence[Passage]) -> list[Version] | None:
    """The versions to show, newest first, or None when fewer than two Documents' values
    check out against their passages."""
    versions: dict[Any, Version] = {}
    for number, value in entries:
        if not 1 <= number <= len(passages) or not value.strip():
            continue
        passage = passages[number - 1]
        if not _says(passage.content, value):
            continue  # not what the passage says
        if passage.document_id in versions:
            continue  # one row per Document: its first value
        versions[passage.document_id] = Version(
            number,
            value,
            passage.document_name,
            passage.effective_date.isoformat() if passage.effective_date else None,
        )
    if len(versions) < 2:
        return None
    return sorted(
        versions.values(), key=lambda v: (v.effective_date or "", -v.number), reverse=True
    )


def _says(passage: str, value: str) -> bool:
    """Whether the passage contains the value, as quoted: "…" may join parts in order."""
    text = _words(passage)
    parts = [part for part in (_words(p) for p in _ELLIPSIS.split(value)) if part]
    position = 0
    for part in parts:
        found = _find_words(text, part, position)
        if found < 0:
            return False
        position = found + len(part)
    return bool(parts)


def as_records(versions: list[Version] | None) -> list[dict[str, Any]] | None:
    return [asdict(v) for v in versions] if versions else None
