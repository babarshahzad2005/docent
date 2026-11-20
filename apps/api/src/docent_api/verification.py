"""Checking an answer's Citations against their passages (ADR 0007).

The answer model writes its answer, then a `Quotes:` line and, for each Citation, the exact
words it relies on: `[2] "words copied from passage 2"`. The reader never sees the quotes;
they are held back while the answer streams (`QuoteFilter`). Once it has finished, `verify`
checks each Citation against its passage:

- a Citation is verified when a quote given for its passage occurs in that passage, allowing
  for differences in case, whitespace, punctuation, and quotation marks, and for "…" between
  quoted parts. Quotes pair with Citations in order; a Citation left without a quote of its
  own (models often quote a passage once, however often they cite it) may use any quote
  given for that passage, but a quote that fails is never rescued by another;
- a quote shorter than three words can't verify anything (it would match almost any passage);
- a Claim (a sentence, or a list item) keeps its verified Citations and loses the others; a
  Claim left with none is removed, with the reason. Sentences that cite nothing are kept;
- an answer the model wrote with no markers at all has its verified quotes tied to the
  sentences they match first (`_attach_citations`, #58), so a correct answer isn't hidden
  for a missing marker.

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
_QUOTE = re.compile(r"\[(\d{1,2})\][ \t]*[:\-]?[ \t]*[\"“”](.+?)[\"“”][ \t]*(?=\n|\[|$)")
_ELLIPSIS = re.compile(r"\s*(?:…|\.\.\.)\s*")
# The line that starts the quotes: "Quotes:", and the forms models drift into ("**Quotes**",
# "### Quotes", "Quote:", "Sources:"), alone on its line or followed by the first quote.
_HEADING = re.compile(
    r"(?:^|\n)[ \t]*(?:#{1,6}[ \t]*)?\**[ \t]*"
    r"(?:(?:quotes?|sources?)[ \t]*\**[ \t]*:?|disagreements?[ \t]*\**[ \t]*:)"
    r"[ \t]*\**[ \t]*(?=\n|\[\d|$)",
    re.IGNORECASE,
)
_HEADING_WORDS = (
    "quotes:",
    "quote:",
    "sources:",
    "source:",
    "disagreements:",
    "disagreement:",
)
_LIST_ITEM = re.compile(r"[ \t]*(?:[-*]|\d{1,2}[.)])[ \t]+")


class QuoteFilter:
    """Passes the answer through as it streams, and holds back the quotes after it.

    Text is held only while the line it is on could still become the quotes heading, so the
    answer itself streams without a noticeable delay.
    """

    def __init__(self) -> None:
        self.raw = ""
        self.shown = 0  # characters of `raw` passed through
        self.closed = False  # the quotes have begun

    def feed(self, text: str) -> str:
        self.raw += text.replace("\r\n", "\n")
        if self.closed:
            return ""
        start = _quotes_start(self.raw)
        if start is not None:
            self.closed = True
            # The blank lines before the heading belong to it, not to the answer.
            visible = self.raw[self.shown : max(start, self.shown)].rstrip()
            self.shown = max(start, self.shown)
            return visible
        line_start = self.raw.rfind("\n") + 1
        line = self.raw[line_start:].strip()
        tail = line.lstrip("#* \t").lower()
        # "**" or "##" so far could still become the heading, as could "Quo".
        could_be_heading = bool(line) and (
            not tail or any(word.startswith(tail) for word in _HEADING_WORDS)
        )
        safe = max(line_start if could_be_heading else len(self.raw), self.shown)
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
    match = _HEADING.search(raw)
    return None if match is None else match.start()


def split_answer(raw: str) -> tuple[str, list[tuple[int, str]]]:
    """The answer text, and its quotes as (passage number, quote) in order."""
    raw = raw.replace("\r\n", "\n")
    start = _quotes_start(raw)
    if start is None:
        return raw.strip(), []
    quotes = [(int(m.group(1)), m.group(2).strip()) for m in _QUOTE.finditer(raw, start)]
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
    text: str  # the Claim, without its Citation markers
    reason: str
    original: str  # the Claim as it streamed, so the reader's copy can fade it out


@dataclass
class Verification:
    answer: str  # what the reader sees: unsupported Claims and Citations removed
    claims: list[Claim]
    removed: list[Removed]
    # The model wrote no Citation markers, so its verified quotes were tied to the sentences
    # they match (_attach_citations); recorded in the Answer Log.
    attached: bool = False

    @property
    def checked(self) -> int:
        """Citations left in the answer, each checked and verified."""
        return sum(c.verified for claim in self.claims if claim.kept for c in claim.citations)

    def log(self) -> dict[str, Any]:
        """The record kept in the Answer Log."""
        return {
            "claims": [asdict(claim) for claim in self.claims if claim.citations],
            "removed": len(self.removed),
            "verified": self.checked,
            "citations_attached": self.attached,
        }


# Why a Claim was removed, as the reader sees it ("…was removed: <reason>").
NOT_FOUND = "the cited passage doesn’t say this"
NO_QUOTE = "Docent couldn’t tie it to the cited passage"
TOO_SHORT = "too little of the cited passage was given to check it"
NO_PASSAGE = "it cited a source that wasn’t found"


def verify(answer: str, quotes: Sequence[tuple[int, str]], passages: Sequence[str]) -> Verification:
    """Check every Citation in `answer` against its quotes and passage (1-based numbers)."""
    answer, quotes, attached = _attach_citations(answer, quotes, passages)
    given: dict[int, list[str]] = {}
    for number, quote in quotes:
        given.setdefault(number, []).append(quote)
    next_quote = dict.fromkeys(given, 0)
    claims: list[Claim] = []
    removed: list[Removed] = []
    pieces: list[str] = []
    line_start = True  # the next Claim begins a line
    for sentence, separator in _claims(answer):
        claim = Claim(sentence)
        for match in _CITATION.finditer(sentence):
            number = int(match.group(1))
            # Its own quote (in order of use). Only a Citation left without one, because the
            # model quoted the passage once for several Citations, may use the others; a quote
            # that fails is never rescued by another.
            candidates = given.get(number, [])
            first = next_quote.get(number, 0)
            if first < len(candidates):
                next_quote[number] = first + 1
                ordered = [candidates[first]]
            else:
                ordered = candidates
            claim.citations.append(_check(number, ordered, passages))
        claims.append(claim)
        if claim.citations and not any(c.verified for c in claim.citations):
            claim.kept = False
            reason = claim.citations[0].reason or NOT_FOUND
            removed.append(Removed(_plain(sentence), reason, sentence.strip()))
            # A whole line removed takes its line break with it; mid-line, keep the break.
            pieces.append("" if line_start else ("\n" if "\n" in separator else ""))
        else:
            pieces.append(_keep_verified(sentence, claim.citations) + separator)
        line_start = "\n" in separator or (line_start and not pieces[-1])
    return Verification(_tidy("".join(pieces)), claims, removed, attached)


# Words too common to tie a sentence to a quote. "not" and "no" aren't here: they change
# what a sentence says.
_COMMON = frozenset(
    {
        "a",
        "about",
        "also",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "can",
        "do",
        "does",
        "each",
        "for",
        "from",
        "get",
        "has",
        "have",
        "if",
        "in",
        "is",
        "it",
        "its",
        "may",
        "must",
        "of",
        "on",
        "only",
        "or",
        "per",
        "than",
        "that",
        "the",
        "their",
        "there",
        "they",
        "this",
        "to",
        "up",
        "was",
        "were",
        "what",
        "when",
        "which",
        "who",
        "will",
        "with",
        "you",
        "your",
    }
)
_NUMBER = re.compile(r"\d[\d_]*")
# What may follow a sentence's last word: its punctuation, closing quotes and brackets, emphasis.
_TRAILING = re.compile(r"[\s.!?…:;,)\]\"'”’*_]*$")
ATTACH_MIN_SHARED = 2


def _content_words(text: str) -> set[str]:
    return {w for w in _words(text).split() if w not in _COMMON and (len(w) > 2 or w.isdigit())}


def _attach_citations(
    answer: str, quotes: Sequence[tuple[int, str]], passages: Sequence[str]
) -> tuple[str, list[tuple[int, str]], bool]:
    """An answer written without any Citation markers, with each verified quote's passage
    number added to the sentence that quote matches best (#58), and the quotes in the order
    of the markers so each one is checked against the quote it was attached for.

    Models sometimes give correct quotes but leave the markers out, which would leave nothing
    to check. A quote is attached to a sentence only if the quote is in its passage, the two
    share at least two content words, and every number in the sentence is in the quote too
    (so "52 weeks" is never cited by a passage saying "28 weeks"). Answers that cite
    anything, or whose quotes match no sentence, are left as they are.
    """
    unchanged = (answer, list(quotes), False)
    if _CITATION.search(answer) or not quotes:
        return unchanged
    verified = [
        (number, quote)
        for number, quote in quotes
        if 1 <= number <= len(passages)
        and _quote_fails(quote, _words(passages[number - 1])) is None
    ]
    claims = _claims(answer)
    if not verified or not claims:
        return unchanged
    words = [_content_words(sentence) for sentence, _ in claims]
    numbers = [set(_NUMBER.findall(_words(sentence))) for sentence, _ in claims]
    attached: list[list[tuple[int, str]]] = [[] for _ in claims]
    for number, quote in verified:
        quoted = _content_words(quote)
        quoted_numbers = set(_NUMBER.findall(_words(quote)))

        def fit(
            i: int, quoted: set[str] = quoted, quoted_numbers: set[str] = quoted_numbers
        ) -> tuple[int, float]:
            if not numbers[i] <= quoted_numbers:
                return (0, 0.0)  # the sentence states a number the quote doesn't
            shared = len(quoted & words[i])
            return (shared, shared / max(len(words[i]), 1))

        # Most shared words; on a tie, the sentence they make up most of.
        best = max(range(len(claims)), key=fit)
        if fit(best)[0] >= ATTACH_MIN_SHARED and number not in [n for n, _ in attached[best]]:
            attached[best].append((number, quote))
    if not any(attached):
        return unchanged
    pieces = []
    ordered: list[tuple[int, str]] = []
    for (sentence, separator), cites in zip(claims, attached, strict=True):
        if cites:
            markers = "".join(f"[{n}]" for n, _ in cites)
            cut = _TRAILING.search(sentence)
            at = cut.start() if cut else len(sentence)
            sentence = f"{sentence[:at]} {markers}{sentence[at:]}"
            ordered.extend(cites)
        pieces.append(sentence + separator)
    return "".join(pieces), ordered, True


def _check(number: int, quotes: list[str], passages: Sequence[str]) -> CitationCheck:
    if not 1 <= number <= len(passages):
        return CitationCheck(number, quotes[0] if quotes else None, False, NO_PASSAGE)
    if not quotes:
        return CitationCheck(number, None, False, NO_QUOTE)
    passage = _words(passages[number - 1])
    failure: CitationCheck | None = None
    for quote in quotes:
        reason = _quote_fails(quote, passage)
        if reason is None:
            return CitationCheck(number, quote, True)
        failure = failure or CitationCheck(number, quote, False, reason)
    assert failure is not None
    return failure


def _quote_fails(quote: str, passage: str) -> str | None:
    """Why `quote` doesn't verify against the normalised `passage`; None if it does."""
    parts = [part for part in (_words(p) for p in _ELLIPSIS.split(quote)) if part]
    if sum(len(part.split()) for part in parts) < MIN_QUOTE_WORDS:
        return TOO_SHORT
    position = 0
    for part in parts:
        found = _find_words(passage, part, position)
        if found < 0:
            return NOT_FOUND
        position = found + len(part)
    return None


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
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)  # 1,000 → 1000
    text = re.sub(r"(?<=\d)\.(?=\d)", "_", text)  # 12.21 stays one number, distinct from 1221
    text = text.replace("&", " and ")
    text = text.replace("%", " % ")  # 50 % and 50% match
    # Currency signs are dropped, so "£12.21" and "12.21" match; the number must still match.
    text = re.sub(r"[^\w%]+", " ", text)
    return " ".join(text.split())


def _claims(answer: str) -> list[tuple[str, str]]:
    """The answer as Claims (sentences, or list items), each with the whitespace after it.

    A sentence ends at . ! or ? (after any Citations) followed by a space and a capital,
    digit, or quote, so "e.g. in the U.K. is" stays whole; a list item's number ("1.") is
    not a sentence. A line break ends a Claim when the line ends a sentence or a Citation,
    or the next line is blank or a list item; otherwise the sentence carries on.
    """
    out: list[tuple[str, str]] = []
    position = 0
    for match in re.finditer(
        r"(?<=[.!?])((?:[ \t]*\[\d{1,2}\])*)([ \t]+)(?=[A-Z0-9\"“‘(*])|\n", answer
    ):
        if match.group(0) == "\n":
            line = answer[position : match.start()]
            after = answer[match.end() :]
            ends = re.search(r"[.!?:\]]\s*$", line) or not line.strip()
            if not (ends or not after.strip() or after.startswith("\n") or _LIST_ITEM.match(after)):
                continue  # the sentence carries on onto the next line
            out.append((line, "\n"))
            position = match.end()
            continue
        end = match.start() + len(match.group(1))
        if _LIST_ITEM.fullmatch(answer[answer.rfind("\n", 0, end) + 1 : end] + " "):
            continue  # "1. " starts a list item; it doesn't end a sentence
        out.append((answer[position:end], match.group(2)))
        position = match.end()
    if position < len(answer):
        out.append((answer[position:], ""))
    # Separators of consecutive line breaks collapse into the Claim before them.
    merged: list[tuple[str, str]] = []
    for sentence, separator in out:
        if not sentence and merged:
            merged[-1] = (merged[-1][0], merged[-1][1] + separator)
        else:
            merged.append((sentence, separator))
    return merged


def _keep_verified(sentence: str, checks: list[CitationCheck]) -> str:
    """The Claim without the markers of Citations that failed their check."""
    results = iter(checks)

    def keep(match: re.Match[str]) -> str:
        check = next(results, None)
        return match.group(0) if check is None or check.verified else ""

    return _CITATION.sub(keep, sentence)


def _plain(sentence: str) -> str:
    """A Claim as words alone: no Citation markers, list marker, or space before punctuation."""
    text = " ".join(_CITATION.sub("", sentence).split())
    text = re.sub(r" ([.,;:!?])", r"\1", text)
    return _LIST_ITEM.sub("", text, count=1) if _LIST_ITEM.match(text) else text


def _tidy(text: str) -> str:
    text = re.sub(r"[ \t]+([.,;:!?])", r"\1", text)  # a space left before punctuation
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line for line in text.split("\n") if not _LIST_ITEM.fullmatch(line + " ")]
    return "\n".join(line.rstrip() for line in lines).strip()
