"""Checking an answer's Citations against their passages (ADR 0007).

The answer model writes its answer, then a `Quotes:` line and, for each Citation in order,
the exact words it relies on: `[2] "words copied from passage 2"`. The reader never sees the
quotes; they are held back while the answer streams (`QuoteFilter`). Once it has finished,
`verify` checks each quote against its passage:

- a Citation is verified when its quote occurs in the cited passage, allowing for differences
  in case, whitespace, punctuation, and quotation marks, and for "…" between quoted parts;
- a quote shorter than three words can't verify anything (it would match almost any passage);
- a sentence keeps its verified Citations and loses the others; a sentence left with none is
  removed, with the reason. Sentences that cite nothing are kept as they are.

Quote matching proves the passage contains the words, not that it fully supports the claim;
the offline faithfulness eval measures that gap.
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

QUOTES_HEADING = "Quotes:"
MIN_QUOTE_WORDS = 3

INSTRUCTIONS = f"""- After the answer, write a line with only "{QUOTES_HEADING}". Then, for every \
citation in your answer, in the same order, write one line with its number and the exact \
words from that passage that support the sentence, in double quotes, like:
[2] "words copied exactly from passage 2"
  Copy the words exactly, at least a few words and at most one sentence. Use "…" to leave \
words out of the middle of a quote. Write no quotes when you reply that you couldn't find \
the answer."""

_CITATION = re.compile(r"\[(\d{1,2})\]")
_QUOTE_LINE = re.compile(r"^\s*[-*]?\s*\[(\d{1,2})\]\s*[:\-]?\s*[\"“”](.+)[\"“”]\s*$")
_ELLIPSIS = re.compile(r"\s*(?:…|\.\.\.)\s*")
# A sentence ends at . ! or ? followed by a space (after any citations), or at a line break.
_SENTENCE_END = re.compile(r"(?<=[.!?])((?:\s*\[\d{1,2}\])*)[ \t]+|\n")


class QuoteFilter:
    """Passes the answer through as it streams, and holds back the quotes after it.

    Text is held only while it could be the start of the `Quotes:` line, so the answer
    itself streams without delay.
    """

    def __init__(self) -> None:
        self.raw = ""
        self.shown = 0  # characters of `raw` passed through
        self.closed = False  # the quotes have begun

    def feed(self, text: str) -> str:
        self.raw += text
        if self.closed:
            return ""
        start = _quotes_start(self.raw)
        if start is not None:
            self.closed = True
            visible = self.raw[self.shown : start]
            self.shown = start
            return visible
        # Hold back the last line while it could still become the heading.
        line_start = self.raw.rfind("\n") + 1
        tail = self.raw[line_start:].strip().lower()
        safe = line_start if tail and QUOTES_HEADING.lower().startswith(tail) else len(self.raw)
        safe = max(safe, self.shown)
        visible = self.raw[self.shown : safe]
        self.shown = safe
        return visible

    def finish(self) -> str:
        """Whatever was still held back, if it turned out to be answer text."""
        if self.closed:
            return ""
        visible = self.raw[self.shown :]
        self.shown = len(self.raw)
        return visible


def _quotes_start(raw: str) -> int | None:
    match = re.search(
        rf"(?:^|\n)[ \t]*\**{re.escape(QUOTES_HEADING)}\**[ \t]*(?:\n|$)", raw, re.IGNORECASE
    )
    if match is None:
        return None
    return match.start()


def split_answer(raw: str) -> tuple[str, list[tuple[int, str]]]:
    """The answer text, and its quotes as (passage number, quote) in order."""
    start = _quotes_start(raw)
    if start is None:
        return raw.strip(), []
    quotes = []
    for line in raw[start:].splitlines()[1:]:
        match = _QUOTE_LINE.match(line)
        if match:
            quotes.append((int(match.group(1)), match.group(2).strip()))
    return raw[:start].strip(), quotes


@dataclass
class CitationCheck:
    number: int
    quote: str | None
    verified: bool
    reason: str | None = None  # why it wasn't verified


@dataclass
class Claim:
    text: str
    citations: list[CitationCheck] = field(default_factory=list)
    kept: bool = True


@dataclass
class Removed:
    text: str  # the claim, without its Citation markers
    reason: str
    original: str  # the sentence as it streamed, so the reader's copy can fade it out


@dataclass
class Verification:
    answer: str  # what the reader sees: unsupported claims and Citations removed
    claims: list[Claim]
    removed: list[Removed]

    @property
    def checked(self) -> int:
        """Citations in the answer that were checked and verified."""
        return sum(c.verified for claim in self.claims if claim.kept for c in claim.citations)

    def log(self) -> dict[str, Any]:
        """The record kept in the Answer Log."""
        return {
            "claims": [asdict(claim) for claim in self.claims if claim.citations],
            "removed": len(self.removed),
            "verified": self.checked,
        }


NO_QUOTE = "no quote was given for it"
NOT_FOUND = "its quote isn’t in the cited passage"
TOO_SHORT = "its quote is too short to check"
NO_PASSAGE = "it cites a passage that doesn’t exist"


def verify(answer: str, quotes: Sequence[tuple[int, str]], passages: Sequence[str]) -> Verification:
    """Check every Citation in `answer` against its quote and passage (1-based numbers)."""
    unused: dict[int, list[str]] = {}
    for number, given in quotes:
        unused.setdefault(number, []).append(given)
    claims: list[Claim] = []
    removed: list[Removed] = []
    pieces: list[str] = []
    for sentence, separator in _sentences(answer):
        claim = Claim(sentence)
        for match in _CITATION.finditer(sentence):
            number = int(match.group(1))
            queue = unused.get(number)
            quote = queue.pop(0) if queue else None
            claim.citations.append(_check(number, quote, passages))
        claims.append(claim)
        if claim.citations and not any(c.verified for c in claim.citations):
            claim.kept = False
            reason = claim.citations[0].reason or NOT_FOUND
            removed.append(Removed(_without_citations(sentence), reason, sentence.strip()))
            pieces.append(_drop_separator(separator))
            continue
        pieces.append(_keep_verified(sentence, claim.citations) + separator)
    text = _tidy("".join(pieces))
    return Verification(text, claims, removed)


def _check(number: int, quote: str | None, passages: Sequence[str]) -> CitationCheck:
    if not 1 <= number <= len(passages):
        return CitationCheck(number, quote, False, NO_PASSAGE)
    if quote is None:
        return CitationCheck(number, None, False, NO_QUOTE)
    parts = [part for part in (_words(p) for p in _ELLIPSIS.split(quote)) if part]
    if sum(len(part.split()) for part in parts) < MIN_QUOTE_WORDS:
        return CitationCheck(number, quote, False, TOO_SHORT)
    passage = _words(passages[number - 1])
    position = 0
    for part in parts:
        found = _find_words(passage, part, position)
        if found < 0:
            return CitationCheck(number, quote, False, NOT_FOUND)
        position = found + len(part)
    return CitationCheck(number, quote, True)


def _find_words(text: str, words: str, start: int) -> int:
    """Where `words` begins in `text` at word boundaries, from `start`; -1 if absent."""
    match = re.compile(rf"(?:^| ){re.escape(words)}(?= |$)").search(text, start)
    if match is None:
        return -1
    return match.start() + (1 if match.group().startswith(" ") else 0)


def _words(text: str) -> str:
    """Lowercase words and numbers only, single-spaced: what quote matching compares."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub("[‘’`´]", "'", text)  # noqa: RUF001 (apostrophes)
    text = re.sub(r"(?<=\w)'(?=\w)", "", text)  # don't → dont, worker’s → workers
    text = re.sub(r"(?<=\d)[.,](?=\d)", "", text)  # 12.21 → 1221, 1,000 → 1000
    text = re.sub(r"[^\w£$€%]+", " ", text)
    return " ".join(text.split())


def _sentences(answer: str) -> list[tuple[str, str]]:
    """The answer as (sentence, the whitespace after it), keeping citations with their
    sentence."""
    out: list[tuple[str, str]] = []
    position = 0
    for match in _SENTENCE_END.finditer(answer):
        if match.group(0) == "\n":
            end, after = match.start(), match.end()
            out.append((answer[position:end], "\n"))
        else:
            citations = match.group(1) or ""
            end = match.start() + len(citations)
            out.append((answer[position:end], answer[end : match.end()]))
            after = match.end()
        position = after
    if position < len(answer):
        out.append((answer[position:], ""))
    return [(sentence, separator) for sentence, separator in out if sentence or separator]


def _keep_verified(sentence: str, checks: list[CitationCheck]) -> str:
    """The sentence without the markers of Citations that failed their check."""
    results = iter(checks)

    def keep(match: re.Match[str]) -> str:
        check = next(results, None)
        return match.group(0) if check is None or check.verified else ""

    return _CITATION.sub(keep, sentence)


def _without_citations(sentence: str) -> str:
    text = " ".join(_CITATION.sub("", sentence).split())
    return re.sub(r" ([.,;:!?])", r"\1", text).lstrip("-* ")


def _drop_separator(separator: str) -> str:
    return "\n" if "\n" in separator else ""


def _tidy(text: str) -> str:
    text = re.sub(r"[ \t]+([.,;:!?])", r"\1", text)  # a space left before punctuation
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line for line in text.split("\n") if line.strip() not in ("-", "*")]
    return "\n".join(line.rstrip() for line in lines).strip()
