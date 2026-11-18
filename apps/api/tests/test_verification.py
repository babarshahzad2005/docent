"""Citation verification by quote matching (ADR 0007): supported, unsupported, partly quoted,
and paraphrased claims, and the quotes held back while the answer streams."""

import pytest

from docent_api.verification import (
    NO_PASSAGE,
    NO_QUOTE,
    NOT_FOUND,
    TOO_SHORT,
    QuoteFilter,
    split_answer,
    verify,
)

HOLIDAY = (
    "Most workers who work a 5-day week must receive at least 28 days’ paid annual leave a "
    "year. This is the equivalent of 5.6 weeks of holiday."
)
SICK_PAY = (
    "Statutory Sick Pay (SSP) is £118.75 a week. It's paid for up to 28 weeks. You must be "
    "classed as an employee and have done some work for your employer."
)
PASSAGES = [HOLIDAY, SICK_PAY]


def check(answer: str, *quotes: tuple[int, str]):  # type: ignore[no-untyped-def]
    return verify(answer, list(quotes), PASSAGES)


def test_a_claim_whose_quote_is_in_its_passage_is_verified() -> None:
    result = check(
        "Workers on a 5-day week get at least 28 days a year [1].",
        (1, "must receive at least 28 days’ paid annual leave a year"),
    )

    assert result.answer == "Workers on a 5-day week get at least 28 days a year [1]."
    assert result.removed == [] and result.checked == 1


def test_case_whitespace_punctuation_and_quote_marks_do_not_matter() -> None:
    result = check(
        "SSP is £118.75 a week [2].",
        (2, "statutory sick pay (ssp)   is £118.75 a week"),
    )
    assert result.checked == 1
    result = check("It lasts 28 weeks [2].", (2, "It’s paid for up to 28 weeks"))
    assert result.checked == 1


def test_an_unsupported_claim_is_removed_with_its_reason() -> None:
    result = check(
        "You get 28 days [1]. SSP lasts 40 weeks [2].",
        (1, "at least 28 days’ paid annual leave"),
        (2, "paid for up to 40 weeks"),
    )

    assert result.answer == "You get 28 days [1]."
    assert [(r.text, r.reason) for r in result.removed] == [("SSP lasts 40 weeks.", NOT_FOUND)]


def test_a_paraphrased_quote_does_not_verify() -> None:
    result = check(
        "Five-day workers get 5.6 weeks [1].",
        (1, "five-day workers are owed 5.6 weeks of holiday"),
    )

    assert result.checked == 0 and result.removed[0].reason == NOT_FOUND


def test_a_partial_quote_with_an_ellipsis_verifies_when_its_parts_are_in_order() -> None:
    supported = check(
        "You must be an employee who has worked [2].",
        (2, "You must be classed as an employee … done some work for your employer"),
    )
    reversed_parts = check(
        "You must be an employee who has worked [2].",
        (2, "done some work for your employer … You must be classed as an employee"),
    )

    assert supported.checked == 1
    assert reversed_parts.checked == 0


def test_a_quote_of_one_or_two_words_is_too_short_to_verify() -> None:
    result = check("It is weekly [2].", (2, "a week"))

    assert result.removed[0].reason == TOO_SHORT


def test_words_must_match_whole() -> None:
    # "28 weeks" is in the passage, "8 weeks" only inside it.
    result = check("Up to 8 weeks [2].", (2, "for up to 8 weeks"))

    assert result.checked == 0


def test_missing_quotes_and_invented_passages_fail() -> None:
    result = check("You get 28 days [1]. And a car [7].")

    assert [r.reason for r in result.removed] == [NO_QUOTE, NO_PASSAGE]
    assert result.answer == ""


def test_a_sentence_keeps_its_verified_citations_and_loses_the_rest() -> None:
    result = check(
        "Workers get 28 days and SSP [1][2].",
        (1, "at least 28 days’ paid annual leave"),
        (2, "statutory sick pay is paid monthly"),
    )

    assert result.answer == "Workers get 28 days and SSP [1]."
    assert result.removed == []
    assert [c.verified for c in result.claims[0].citations] == [True, False]


def test_quotes_pair_with_citations_in_order_of_use() -> None:
    result = check(
        "You get 28 days [1]. That is 5.6 weeks [1].",
        (1, "at least 28 days’ paid annual leave"),
        (1, "the equivalent of 5.6 weeks of holiday"),
    )

    assert result.checked == 2


def test_sentences_that_cite_nothing_and_list_items_are_handled() -> None:
    result = check(
        "Here is what applies.\n- 28 days of leave [1]\n- 40 weeks of SSP [2]",
        (1, "at least 28 days’ paid annual leave"),
        (2, "paid for up to 40 weeks"),
    )

    assert result.answer == "Here is what applies.\n- 28 days of leave [1]"
    assert result.removed[0].text == "40 weeks of SSP"


def test_the_quotes_are_split_from_the_answer() -> None:
    raw = 'You get 28 days [1].\n\nQuotes:\n[1] "at least 28 days’ paid annual leave"\nnoise\n'

    text, quotes = split_answer(raw)

    assert text == "You get 28 days [1]."
    assert quotes == [(1, "at least 28 days’ paid annual leave")]


@pytest.mark.parametrize("size", [1, 2, 5, 9, 200])
def test_the_quotes_never_stream_to_the_reader(size: int) -> None:
    raw = 'You get 28 days [1]. Quotes: are fine mid-line.\n\nQuotes:\n[1] "at least 28 days"\n'
    shown = QuoteFilter()

    streamed = "".join(shown.feed(raw[i : i + size]) for i in range(0, len(raw), size))
    streamed += shown.finish()

    assert streamed.strip() == "You get 28 days [1]. Quotes: are fine mid-line."


def test_a_last_line_that_only_looks_like_the_heading_is_shown_in_the_end() -> None:
    shown = QuoteFilter()

    streamed = shown.feed("You get 28 days [1].\nQuo") + shown.finish()

    assert streamed == "You get 28 days [1].\nQuo"
