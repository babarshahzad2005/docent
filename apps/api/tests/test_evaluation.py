"""The Eval Set and its harness (#46): the set's shape, and how results are scored."""

from collections import Counter
from uuid import uuid4

from docent_api.evaluation import (
    Result,
    found,
    load,
    markdown,
    regressions,
    report,
    threshold_sweep,
)
from docent_api.retrieval import Passage
from docent_api.settings import Settings


def test_the_eval_set_has_50_items_with_at_least_12_unanswerable_and_some_conflicts() -> None:
    items = load()
    kinds = Counter(item.kind for item in items)

    assert len(items) == 50
    assert kinds["unanswerable"] >= 12 and kinds["conflict"] >= 3
    assert len({item.id for item in items}) == len(items)
    assert all(item.reviewed for item in items)  # every item checked by the maintainer
    for item in items:
        assert item.question.strip()
        if item.kind == "unanswerable":
            assert item.expected == []
        else:
            assert item.expected and all(e["document"] and e["contains"] for e in item.expected)
        if item.kind == "conflict":
            assert len({e["document"] for e in item.expected}) >= 2  # both versions


def passage(document: str, content: str) -> Passage:
    return Passage(uuid4(), uuid4(), document, (), None, content, 0.0, 1, None, 0.7)


def test_an_expected_passage_is_found_by_document_and_words_ignoring_spacing() -> None:
    expected = {"document": "ssp.md", "contains": "for up to 28 weeks"}

    assert found(expected, [passage("ssp.md", "It’s paid for up\nto 28 weeks.")])
    assert not found(expected, [passage("other.md", "It’s paid for up to 28 weeks.")])
    assert not found(expected, [passage("ssp.md", "It’s paid for 28 weeks.")])


def results() -> list[Result]:
    return [
        Result("a", "answerable", 0.75, hit_at_5=True, answered=True, claims=4, supported=3),
        Result("b", "answerable", 0.70, hit_at_5=False, answered=False, outcome="declined"),
        Result("c", "conflict", 0.72, hit_at_5=True, both_versions=False),
        Result("d", "unanswerable", 0.60, answered=False, outcome="declined"),
        Result("e", "unanswerable", 0.68, answered=True, outcome="answered", claims=1, supported=0),
    ]


def test_the_report_scores_each_metric_over_the_right_questions() -> None:
    metrics = report(results(), Settings())["metrics"]

    assert metrics["hit_at_5"] == {"rate": 0.6667, "of": 3, "count": 2}
    assert metrics["conflicts_both_retrieved"] == {"rate": 0.0, "of": 1, "count": 0}
    assert metrics["unanswerable_declined"] == {"rate": 0.5, "of": 2, "count": 1}
    assert metrics["answerable_answered"] == {"rate": 0.5, "of": 2, "count": 1}
    assert metrics["faithfulness"] == {"rate": 0.6, "of": 5, "count": 3}  # by sentence


def test_the_threshold_sweep_shows_what_each_threshold_would_decline() -> None:
    rows = {row["threshold"]: row for row in threshold_sweep(results())}

    assert rows[0.65]["unanswerable_declined"]["count"] == 1  # 0.60 only
    assert rows[0.69]["unanswerable_declined"]["count"] == 2
    assert rows[0.69]["answerable_let_through"]["count"] == 3  # 0.70, 0.72, 0.75
    assert rows[0.71]["answerable_let_through"]["count"] == 2


def test_judge_failures_are_counted_not_left_out() -> None:
    rows = [
        *results(),
        Result("f", "answerable", 0.74, hit_at_5=True, answered=True, judge_failed=True),
    ]

    metrics = report(rows, Settings())["metrics"]

    assert metrics["answers_judged"] == {"rate": 0.6667, "of": 3, "count": 2}  # "f" unjudged


def test_questions_naming_an_identifier_reach_the_model_at_any_threshold() -> None:
    rows = [Result("form", "answerable", 0.55, bypasses_threshold=True)]

    sweep = threshold_sweep(rows)

    assert all(row["answerable_let_through"]["count"] == 1 for row in sweep)


def test_the_judges_verdicts_are_read_from_prose_and_strings() -> None:
    from docent_api.evaluation import _verdicts

    assert _verdicts('Here you go {"supported": [true, "false", "True"]} (done {ok})') == [
        True,
        False,
        True,
    ]


def test_a_bare_verdict_for_a_one_sentence_answer_is_read() -> None:
    from docent_api.evaluation import _verdicts

    assert _verdicts('{"supported": true}') == [True]


def test_conflict_questions_count_as_noticed_only_with_a_notice() -> None:
    rows = [
        Result("c1", "conflict", 0.7, hit_at_5=True, answered=True, notice_complete=True),
        Result("c2", "conflict", 0.7, hit_at_5=True, answered=True, notice_complete=False),
    ]

    assert report(rows, Settings())["metrics"]["conflicts_noticed"] == {
        "rate": 0.5,
        "of": 2,
        "count": 1,
    }


def test_the_markdown_summary_is_a_table_of_rates() -> None:
    text = markdown(report(results(), Settings()))

    assert "| hit at 5 | 66.7% | 2 of 3 |" in text
    assert "judge `gemini:" in text


def metrics(of: int = 100, **rates: float) -> dict[str, object]:
    return {"metrics": {k: {"rate": v, "of": of, "count": 0} for k, v in rates.items()}}


def test_a_drop_of_more_than_two_points_against_main_blocks() -> None:
    main = metrics(hit_at_5=0.86, faithfulness=1.0)

    assert regressions(main, metrics(hit_at_5=0.85, faithfulness=0.98)) == []
    assert regressions(main, metrics(hit_at_5=0.83, faithfulness=1.0)) == [
        "hit_at_5 fell from 86.0% to 83.0%"
    ]


def test_one_lost_retrieval_question_blocks_since_retrieval_doesnt_vary() -> None:
    # One question of 36 is 2.8 points: retrieval is deterministic, so no allowance.
    assert regressions(metrics(36, hit_at_5=31 / 36), metrics(36, hit_at_5=30 / 36))


def test_a_metric_main_has_but_this_run_lacks_blocks() -> None:
    current = {"metrics": {"hit_at_5": {"rate": 0.86, "of": 36, "count": 31}, "faithfulness": None}}

    assert regressions(metrics(faithfulness=1.0, hit_at_5=0.86), current) == [
        "faithfulness is missing from this run (main has 100.0%)"
    ]


def test_one_unsupported_sentence_below_target_is_tolerated_two_are_not() -> None:
    main = metrics(15, faithfulness=1.0)

    assert regressions(main, metrics(15, faithfulness=14 / 15)) == []
    assert regressions(main, metrics(15, faithfulness=13 / 15))


def test_falling_below_a_target_blocks_only_once_main_meets_it() -> None:
    assert regressions(metrics(hit_at_5=0.86), metrics(hit_at_5=0.85)) == []  # not yet met
    problems = regressions(metrics(faithfulness=0.96), metrics(faithfulness=0.935))
    assert "faithfulness is 93.5%, below its 95% target, which main meets" in problems


def test_without_a_baseline_nothing_blocks_but_failed_questions() -> None:
    assert regressions(None, metrics(hit_at_5=0.5)) == []
    assert regressions(None, {**metrics(), "errors": ["ssp-amount"]}) == [
        "questions that failed to run: ssp-amount"
    ]


def test_one_item_changing_in_a_small_subset_does_not_block() -> None:
    # One answer of eight is 12.5 points: the model's own variation, not a regression.
    assert (
        regressions(metrics(8, answerable_answered=0.75), metrics(8, answerable_answered=0.625))
        == []
    )
    assert regressions(metrics(8, answerable_answered=0.75), metrics(8, answerable_answered=0.5))


def test_a_daily_quota_wait_gives_up_at_once_instead_of_hanging() -> None:
    import asyncio
    import time

    import pytest

    from docent_api.evaluation import _generate
    from docent_api.providers.base import RateLimited

    class Spent:
        name = "fake:spent"
        calls = 0

        async def generate(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            Spent.calls += 1
            raise RateLimited("fake", "daily quota", retry_after=3600)
            yield  # pragma: no cover

    started = time.monotonic()
    with pytest.raises(RateLimited):
        asyncio.run(_generate(Spent(), "prompt"))  # type: ignore[arg-type]

    assert Spent.calls == 1 and time.monotonic() - started < 5
