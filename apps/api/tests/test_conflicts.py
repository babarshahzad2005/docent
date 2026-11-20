"""When Documents disagree (#48): reading the model's list, and the notice it becomes."""

from datetime import date
from uuid import uuid4

from docent_api.conflicts import notice, split_disagreements
from docent_api.retrieval import Passage
from docent_api.verification import QuoteFilter, split_answer

REFORMS = uuid4()
GUIDANCE = uuid4()


def passage(document, name: str, text: str, effective: date) -> Passage:  # type: ignore[no-untyped-def]
    return Passage(
        chunk_id=uuid4(),
        document_id=document,
        document_name=name,
        heading_path=(),
        page=None,
        content=text,
        score=0.0,
        vector_rank=1,
        keyword_rank=None,
        similarity=0.7,
        effective_date=effective,
    )


PASSAGES = [
    passage(
        REFORMS, "reforms-2024.md", "Leave accrues at 12.07% of hours worked.", date(2024, 1, 1)
    ),
    passage(
        GUIDANCE,
        "guidance-2019.pdf",
        "Workers receive at least 5.6 weeks' annual leave.",
        date(2019, 11, 1),
    ),
    passage(REFORMS, "reforms-2024.md", "Rolled-up holiday pay is allowed.", date(2024, 1, 1)),
]

RAW = (
    "Holiday accrues at 12.07% of hours worked [1]. The documents disagree [1][2].\n\n"
    'Quotes:\n[1] "accrues at 12.07% of hours worked"\n'
    '[1] "accrues at 12.07% of hours worked"\n[2] "at least 5.6 weeks"\n\n'
    'Disagreements:\n[1] "12.07% of hours worked"\n[2] "at least 5.6 weeks"\n'
)


def test_the_list_is_read_and_kept_apart_from_the_quotes() -> None:
    reply, entries = split_disagreements(RAW)
    text, quotes = split_answer(reply)

    assert entries == [(1, "12.07% of hours worked"), (2, "at least 5.6 weeks")]
    assert len(quotes) == 3 and all("Disagreements" not in q for _, q in quotes)
    assert text.endswith("The documents disagree [1][2].")


def test_the_list_never_streams_to_the_reader_even_before_the_quotes() -> None:
    raw = 'Holiday accrues [1].\n\nDisagreements:\n[1] "12.07%"\n\nQuotes:\n[1] "accrues"\n'
    shown = QuoteFilter()

    streamed = "".join(shown.feed(raw[i : i + 4]) for i in range(0, len(raw), 4))
    streamed += shown.finish()
    reply, entries = split_disagreements(raw)

    assert streamed.strip() == "Holiday accrues [1]."
    assert entries == [(1, "12.07%")] and split_answer(reply)[1] == [(1, "accrues")]


def test_the_notice_lists_each_document_newest_first() -> None:
    versions = notice([(2, "at least 5.6 weeks"), (1, "12.07% of hours worked")], PASSAGES)

    assert versions is not None
    assert [(v.document_name, v.value, v.effective_date) for v in versions] == [
        ("reforms-2024.md", "12.07% of hours worked", "2024-01-01"),
        ("guidance-2019.pdf", "at least 5.6 weeks", "2019-11-01"),
    ]


def test_a_value_may_leave_words_out_with_an_ellipsis() -> None:
    versions = notice([(1, "accrues at ... hours worked"), (2, "receive ... 5.6 weeks")], PASSAGES)

    assert versions is not None and len(versions) == 2


def test_values_not_in_their_passage_or_from_one_document_make_no_notice() -> None:
    made_up = notice([(1, "10% of hours worked"), (2, "at least 5.6 weeks")], PASSAGES)
    one_document = notice([(1, "12.07% of hours worked"), (3, "Rolled-up holiday pay")], PASSAGES)
    no_such_passage = notice([(1, "12.07% of hours worked"), (9, "anything")], PASSAGES)

    assert made_up is None and one_document is None and no_such_passage is None


def test_only_versions_the_answer_still_cites_make_the_notice() -> None:
    entries = [(1, "12.07% of hours worked"), (2, "at least 5.6 weeks")]

    assert notice(entries, PASSAGES, cited=[1, 2]) is not None
    assert notice(entries, PASSAGES, cited=[1]) is None  # [2] failed verification


def test_values_of_one_word_are_too_short_to_count() -> None:
    assert notice([(1, "12.07%"), (2, "weeks")], PASSAGES) is None


def test_answer_text_after_the_list_is_kept() -> None:
    raw = (
        'Holiday accrues [1].\n\nDisagreements:\n[1] "12.07% of hours"\n[2] "at least 5.6 weeks"\n'
        'The older guide said otherwise [2].\n\nQuotes:\n[1] "accrues at 12.07%"\n'
    )

    reply, entries = split_disagreements(raw)

    assert len(entries) == 2
    assert "The older guide said otherwise [2]." in reply and "Quotes:" in reply


def test_a_line_starting_with_disagreement_is_answer_text() -> None:
    shown = QuoteFilter()
    raw = 'Disagreement between the two guides is about accrual [1].\n\nQuotes:\n[1] "x y z"\n'

    streamed = "".join(shown.feed(raw[i : i + 3]) for i in range(0, len(raw), 3))
    streamed += shown.finish()

    assert streamed.strip() == "Disagreement between the two guides is about accrual [1]."
    assert split_disagreements(raw)[1] == []
