"""The Eval Set harness (#46): how well Docent answers the Demo Collection, measured.

    uv run docent-eval                        # all 50 questions, with answers and the judge
    uv run docent-eval --answers 10           # every question retrieved, 10 answered (CI)
    uv run docent-eval --out report.json

For each question in `evals/eval-set.jsonl` it runs Docent's own answer path (retrieval, the
weak-retrieval decline, the answer model, quote verification, the model's own decline)
without saving anything, so it can run against any database holding the Demo Collection.
It reports:

- **hit@5**: answerable questions with an expected passage among the top 5 retrieved;
- **decline accuracy**: unanswerable questions declined, and answerable ones answered;
- **faithfulness**: answer sentences a judge model (not the answer model) finds supported
  by the passages they cite;
- **conflicts**: conflict questions with both versions retrieved among the 8 passages;
- **the weak-retrieval threshold**: decline accuracy at each candidate threshold, from each
  question's best similarity, for choosing `DECLINE_BELOW_SIMILARITY`.

Answers use the answer model alone (no fallback, temperature 0), paced to its free-tier
rate limit, so a run measures that model and nothing else.
"""

import argparse
import asyncio
import json
import re
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from psycopg import Connection
from psycopg.rows import DictRow, dict_row

from docent_api.answers import (
    _IDENTIFIER,
    DECLINE,
    MAX_ANSWER_TOKENS,
    SYSTEM_PROMPT,
    _weak_retrieval,
    build_prompt,
    cited_numbers,
    is_decline,
    normalize_citations,
)
from docent_api.conflicts import notice, split_disagreements
from docent_api.providers.base import (
    Generator,
    Message,
    ProviderError,
    Purpose,
    RateLimited,
    TextDelta,
)
from docent_api.providers.registry import embedder, generator_for
from docent_api.retrieval import Passage, retrieve
from docent_api.settings import Settings, get_settings
from docent_api.verification import _claims, split_answer, verify

REPO = Path(__file__).resolve().parents[4]
EVAL_SET = REPO / "evals" / "eval-set.jsonl"
HIT_AT = 5
THRESHOLDS = [round(0.50 + 0.01 * i, 2) for i in range(31)]  # 0.50 to 0.80
# Groq's free tier allows 8,000 tokens a minute; an answer with its prompt is about 4,500.
SECONDS_BETWEEN_ANSWERS = 35.0

JUDGE_PROMPT = """You check whether each numbered sentence of an answer is supported by the \
passages it cites. Only the passages count: not your own knowledge.

Reply with JSON only: one true or false per sentence, in order, like
{"supported": [true, false]}

A sentence is supported when its cited passages state it, or plainly imply it. A sentence \
that cites nothing is not supported unless it only introduces or links other sentences."""


@dataclass
class Item:
    id: str
    question: str
    kind: str  # "answerable", "conflict", or "unanswerable"
    expected: list[dict[str, str]]
    reviewed: bool = False


@dataclass
class Result:
    id: str
    kind: str
    best_similarity: float | None
    hit_at_5: bool | None = None  # answerable and conflict questions
    both_versions: bool | None = None  # conflict questions
    answered: bool | None = None  # None: not answered in this run
    outcome: str | None = None
    answer: str | None = None
    claims: int = 0
    supported: int | None = None
    judge_failed: bool = False
    notice_documents: list[str] = field(default_factory=list)  # in a "documents disagree" notice
    notice_complete: bool = False  # a conflict question got a notice (see evaluate)
    rate_limited: bool = False  # the answer model's quota ran out on this question
    # The question names an identifier keyword search found: it reaches the model whatever
    # its similarity (answers._weak_retrieval).
    bypasses_threshold: bool = False
    notes: list[str] = field(default_factory=list)


def load(path: Path = EVAL_SET) -> list[Item]:
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            data = json.loads(line)
            items.append(
                Item(
                    data["id"],
                    data["question"],
                    data["kind"],
                    data["expected"],
                    data.get("reviewed", False),
                )
            )
    return items


def _normal(text: str) -> str:
    return " ".join(text.split()).lower()


def found(expected: dict[str, str], passages: Sequence[Passage]) -> bool:
    """Whether an expected passage (its document, and words it contains) is among these."""
    words = _normal(expected["contains"])
    return any(
        p.document_name == expected["document"] and words in _normal(p.content) for p in passages
    )


async def evaluate(
    conn: Connection[DictRow],
    items: Sequence[Item],
    answer_ids: set[str],
    generator: Generator,
    judge: Generator,
) -> list[Result]:
    user_id, demo_id = _demo_reader(conn)
    vectors = (await embedder().embed([item.question for item in items], Purpose.QUERY)).vectors
    results = []
    pace = _Pace(SECONDS_BETWEEN_ANSWERS)
    for item, vector in zip(items, vectors, strict=True):
        passages = retrieve(conn, user_id, [demo_id], item.question, vector)
        conn.rollback()
        similarities = [p.similarity for p in passages if p.similarity is not None]
        result = Result(item.id, item.kind, max(similarities) if similarities else None)
        result.bypasses_threshold = bool(
            _IDENTIFIER.search(item.question) and any(p.keyword_rank for p in passages)
        )
        if item.kind != "unanswerable":
            result.hit_at_5 = any(found(e, passages[:HIT_AT]) for e in item.expected)
        if item.kind == "conflict":
            result.both_versions = all(found(e, passages) for e in item.expected)
        if item.id in answer_ids:
            try:
                await _answer(result, item, passages, generator, judge, pace)
                # A notice of two or more Documents naming one expected: newer guidance can
                # agree with the expected newer Document and stand in for it.
                expected = {e["document"] for e in item.expected}
                result.notice_complete = (
                    item.kind == "conflict"
                    and len(result.notice_documents) >= 2
                    and bool(expected & set(result.notice_documents))
                )
            except ProviderError as error:
                # One failed question is recorded, not allowed to lose the whole run.
                result.answered, result.outcome = None, "error"
                result.notes.append(f"answer failed: {error!r}")
                if isinstance(error, RateLimited):
                    result.rate_limited = True
        results.append(result)
        print(f"  {item.id}: {_line(result)}", file=sys.stderr)
    return results


class _Pace:
    """Spaces model calls out, to stay inside a free tier's tokens per minute."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.last = 0.0

    async def wait(self) -> None:
        if self.last:
            remaining = self.seconds - (time.monotonic() - self.last)
            if remaining > 0:
                await asyncio.sleep(remaining)
        self.last = time.monotonic()


async def _answer(
    result: Result,
    item: Item,
    passages: list[Passage],
    generator: Generator,
    judge: Generator,
    pace: _Pace,
) -> None:
    """The answer path of `answers.answer`, without saving: decline early, or ask, verify,
    and recognise a decline in the model's own words."""
    if not passages or _weak_retrieval(item.question, passages):
        result.answered, result.outcome, result.answer = False, "declined", DECLINE
        return
    await pace.wait()
    raw = await _generate(generator, build_prompt(item.question, passages))
    reply, disagreements = split_disagreements(normalize_citations(raw))
    text, quotes = split_answer(reply)
    if is_decline(text):
        result.answered, result.outcome, result.answer = False, "declined", DECLINE
        return
    verification = verify(text, quotes, [p.content for p in passages])
    if not verification.checked:
        result.answered, result.outcome, result.answer = False, "unverified", text
        return
    result.answered, result.outcome, result.answer = True, "answered", verification.answer
    # As shown: only versions whose Citations survived verification (answers._verify).
    versions = notice(disagreements, passages, cited_numbers(verification.answer, len(passages)))
    result.notice_documents = [v.document_name for v in versions] if versions else []
    await _judge(result, verification.answer, passages, judge)


async def _generate(generator: Generator, prompt: str, attempts: int = 4) -> str:
    for attempt in range(attempts):
        try:
            raw = ""
            async for event in generator.generate(
                SYSTEM_PROMPT,
                [Message("user", prompt)],
                max_output_tokens=MAX_ANSWER_TOKENS,
                temperature=0,
            ):
                if isinstance(event, TextDelta):
                    raw += event.text
            return raw
        except RateLimited as error:
            if attempt == attempts - 1:
                raise
            # A per-minute limit clears within a minute; one that asks for longer is a daily
            # quota, which waiting out would hang the run for hours. Give up on it instead.
            wait = getattr(error, "retry_after", 0) or 30 * (attempt + 1)
            if wait > MAX_RATE_WAIT_SECONDS:
                raise
            await asyncio.sleep(wait)
    raise AssertionError("unreachable")


async def _judge(result: Result, answer: str, passages: list[Passage], judge: Generator) -> None:
    cited = sorted({int(n) for n in re.findall(r"\[(\d{1,2})\]", answer)})
    quoted = "\n\n".join(
        f"[{n}] {passages[n - 1].content}" for n in cited if 1 <= n <= len(passages)
    )
    # The sentences are numbered here and judged by number: the judge never echoes text, so
    # its reply is always plain JSON.
    sentences = [text.strip() for text, _ in _claims(answer) if text.strip()]
    numbered = "\n".join(f"{n}. {text}" for n, text in enumerate(sentences, start=1))
    prompt = f"Passages:\n\n{quoted}\n\nAnswer, by sentence:\n\n{numbered}"
    result.claims = len(sentences)
    for attempt in range(2):
        try:
            reply = ""
            async for event in judge.generate(
                JUDGE_PROMPT, [Message("user", prompt)], max_output_tokens=600, temperature=0
            ):
                if isinstance(event, TextDelta):
                    reply += event.text
            verdicts = _verdicts(reply)
            if len(verdicts) != len(sentences):
                raise ValueError(f"{len(verdicts)} verdicts for {len(sentences)} sentences")
            result.supported = sum(verdicts)
            return
        except RateLimited:
            if attempt == 0:
                await asyncio.sleep(30)
                continue
            result.notes.append("judge failed: rate limited")
        except (ProviderError, ValueError, KeyError, TypeError) as error:
            result.notes.append(f"judge failed: {error!r}")
        break
    result.judge_failed = True  # counted in the report, never silently left out


def _verdicts(reply: str) -> list[bool]:
    """The judge's verdicts from its reply: the first JSON object in it, as true or false."""
    start = reply.find("{")
    if start < 0:
        raise ValueError("no JSON in the judge's reply")
    data, _ = json.JSONDecoder().raw_decode(reply[start:])
    verdicts = data["supported"]
    if not isinstance(verdicts, list):
        verdicts = [verdicts]  # a one-sentence answer is sometimes judged with a bare verdict
    return [v is True or (isinstance(v, str) and v.strip().lower() == "true") for v in verdicts]


def _demo_reader(conn: Connection[DictRow]) -> tuple[UUID, UUID]:
    """The Demo Collection, and a User who can read it (every User can)."""
    row = conn.execute(
        """
        select m.user_id, c.id as collection_id from app.collections c
        join app.memberships m on m.collection_id = c.id
        where c.is_demo limit 1
        """
    ).fetchone()
    conn.rollback()
    if row is None:
        raise SystemExit("No Demo Collection with a reader: run `docent-demo seed` first.")
    return row["user_id"], row["collection_id"]


def _line(result: Result) -> str:
    parts = [f"similarity {result.best_similarity:.3f}" if result.best_similarity else "no vector"]
    if result.hit_at_5 is not None:
        parts.append("hit" if result.hit_at_5 else "MISS")
    if result.outcome:
        parts.append(result.outcome)
    if result.supported is not None:
        parts.append(f"{result.supported}/{result.claims} supported")
    return ", ".join(parts)


# --- The report ---------------------------------------------------------------------------


def report(results: Sequence[Result], settings: Settings) -> dict[str, Any]:
    retrievable = [r for r in results if r.hit_at_5 is not None]
    conflicts = [r for r in results if r.both_versions is not None]
    answered = [r for r in results if r.answered is not None]
    should_answer = [r for r in answered if r.kind != "unanswerable"]
    should_decline = [r for r in answered if r.kind == "unanswerable"]
    judged = [r for r in answered if r.supported is not None and r.claims]
    claims = sum(r.claims for r in judged)
    to_judge = [r for r in answered if r.answered]
    metrics = {
        "hit_at_5": _rate(sum(bool(r.hit_at_5) for r in retrievable), len(retrievable)),
        "conflicts_both_retrieved": _rate(
            sum(bool(r.both_versions) for r in conflicts), len(conflicts)
        ),
        # Conflict questions answered with a notice of two or more Documents, at least one of
        # them expected (#48).
        "conflicts_noticed": _rate(
            sum(r.notice_complete for r in answered if r.kind == "conflict"),
            sum(1 for r in answered if r.kind == "conflict"),
        ),
        "unanswerable_declined": _rate(
            sum(not r.answered for r in should_decline), len(should_decline)
        ),
        "answerable_answered": _rate(
            sum(bool(r.answered) for r in should_answer), len(should_answer)
        ),
        "faithfulness": _rate(sum(r.supported or 0 for r in judged), claims),
        "answers_judged": _rate(len(judged), len(to_judge)),
    }
    return {
        "models": {
            "answer": settings.answer_model,
            "judge": settings.judge_model,
            "embedding": "gemini:gemini-embedding-001",
        },
        "decline_below_similarity": settings.decline_below_similarity,
        "questions": len(results),
        "answered_in_run": len(answered),
        "errors": [r.id for r in results if r.outcome == "error"],
        "metrics": metrics,
        "threshold_sweep": threshold_sweep(results),
        "results": [asdict(r) for r in results],
    }


def threshold_sweep(results: Sequence[Result]) -> list[dict[str, Any]]:
    """For each threshold, how the weak-retrieval decline alone would sort the questions:
    unanswerable ones declined, answerable ones let through to the model."""
    rows = []
    unanswerable = [r for r in results if r.kind == "unanswerable" and r.best_similarity]
    answerable = [r for r in results if r.kind != "unanswerable" and r.best_similarity]

    def through(result: Result, threshold: float) -> bool:
        assert result.best_similarity is not None
        return result.bypasses_threshold or result.best_similarity >= threshold

    for threshold in THRESHOLDS:
        declined = sum(not through(r, threshold) for r in unanswerable)
        let_through = sum(through(r, threshold) for r in answerable)
        rows.append(
            {
                "threshold": threshold,
                "unanswerable_declined": _rate(declined, len(unanswerable)),
                "answerable_let_through": _rate(let_through, len(answerable)),
            }
        )
    return rows


def _rate(numerator: int, denominator: int) -> dict[str, Any] | None:
    if denominator == 0:
        return None
    return {"rate": round(numerator / denominator, 4), "of": denominator, "count": numerator}


def markdown(summary: dict[str, Any]) -> str:
    """The report as a short Markdown table, for CI summaries and the README."""
    lines = [
        f"Eval Set: {summary['questions']} questions, {summary['answered_in_run']} answered "
        f"(answer model `{summary['models']['answer']}`, judge `{summary['models']['judge']}`).",
        "",
        "| Metric | Rate | Count |",
        "| --- | --- | --- |",
    ]
    for name, value in summary["metrics"].items():
        if value is not None:
            label = name.replace("_", " ")
            count = f"{value['count']} of {value['of']}"
            lines.append(f"| {label} | {value['rate']:.1%} | {count} |")
    return "\n".join(lines) + "\n"


# --- The command --------------------------------------------------------------------------


def schema_behind(conn: Connection[DictRow]) -> str | None:
    """Why the database can't run this code's queries yet (it lacks a migration this code
    brings, which production applies only once merged), or None if it can."""
    from alembic.script import ScriptDirectory

    from docent_api.migrate import alembic_config

    scripts = ScriptDirectory.from_config(alembic_config())
    head = scripts.get_current_head()
    assert head is not None
    row = conn.execute("select version_num from app.alembic_version").fetchone()
    conn.rollback()
    applied = row["version_num"] if row else None
    # Behind only if the database is at an earlier revision of this code's own history; a
    # database that is ahead (main merged a migration since) can still run older code.
    earlier = [r.revision for r in scripts.walk_revisions("base", head) if r.revision != head]
    if applied not in earlier:
        return None
    return (
        f"The database is at migration {applied}, and this change brings {head}: it can't be "
        "measured against the live Demo Collection until it is merged and migrated."
    )


SCHEMA_BEHIND = 3  # exit code: the database lacks this code's migrations (see schema_behind)
QUOTA_SPENT = 4  # exit code: the answer model's quota ran out, so the run measured too little
MAX_RATE_WAIT_SECONDS = 90


def main() -> None:
    parser = argparse.ArgumentParser(prog="docent-eval", description=__doc__.splitlines()[0])
    parser.add_argument(
        "--answers", type=int, default=None, help="answer only the first N answerable questions"
    )
    parser.add_argument("--out", type=Path, default=REPO / "evals" / "results" / "latest.json")
    args = parser.parse_args()
    if args.answers is not None and args.answers < 0:
        parser.error("--answers must be 0 or more")
    settings = get_settings()
    items = load()
    answerable = [item for item in items if item.kind != "unanswerable"]
    answer_ids = (
        {item.id for item in answerable[: args.answers]}
        if args.answers is not None
        else {item.id for item in items}
    )
    # Unanswerable questions are always among those answered, so declines are measured.
    if args.answers is not None:
        answer_ids |= {item.id for item in items if item.kind == "unanswerable"}
    generator = generator_for(settings.answer_model, settings)
    judge = generator_for(settings.judge_model, settings)
    with psycopg.connect(
        settings.database_url, prepare_threshold=None, row_factory=dict_row
    ) as conn:
        behind = schema_behind(conn)
        if behind is not None:
            print(behind)
            raise SystemExit(SCHEMA_BEHIND)
        results = asyncio.run(evaluate(conn, items, answer_ids, generator, judge))
    summary = report(results, settings)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.out.with_suffix(".md").write_text(markdown(summary), encoding="utf-8")
    print(markdown(summary))
    limited = [r.id for r in results if r.rate_limited]
    if limited:
        print(
            f"The answer model's quota ran out on {len(limited)} questions: {', '.join(limited)}."
        )
        raise SystemExit(QUOTA_SPENT)


# --- Blocking regressions in CI -----------------------------------------------------------

# PRD targets. A metric below its target fails CI only once main has reached it: until then
# (hit@5 is 86% today) the 2-point regression rule protects it.
TARGETS = {
    "hit_at_5": 0.90,
    "faithfulness": 0.95,
    "unanswerable_declined": 0.90,
}
MAX_DROP = 0.02


# Metrics that depend on what the answer and judge models write: at temperature 0 they still
# vary a little, and one question of eight is twelve points, so these block only when more
# than one item's worth is lost. Retrieval metrics are deterministic and get no allowance.
MODEL_METRICS = {"answerable_answered", "faithfulness", "answers_judged"}


def regressions(baseline: dict[str, Any] | None, current: dict[str, Any]) -> list[str]:
    """Why `current` should block a merge against `baseline` (main): a metric more than two
    points lower, one main meets that has fallen below its target, a metric main has that
    this run lacks, or questions that failed to run."""
    problems = []
    before_metrics = (baseline or {}).get("metrics", {})
    for name, before in before_metrics.items():
        if before is not None and current["metrics"].get(name) is None:
            problems.append(f"{name} is missing from this run (main has {before['rate']:.1%})")
    for name, value in current["metrics"].items():
        before = before_metrics.get(name)
        if value is None or before is None:
            continue
        rate, was = value["rate"], before["rate"]
        lost = (was - rate) * min(value["of"], before["of"])
        tolerated = name in MODEL_METRICS and lost < 1.5
        if rate < was - MAX_DROP - 1e-9 and not tolerated:
            problems.append(f"{name} fell from {was:.1%} to {rate:.1%}")
        target = TARGETS.get(name)
        if target is not None and rate < target <= was and not tolerated:
            problems.append(
                f"{name} is {rate:.1%}, below its {target:.0%} target, which main meets"
            )
    if current.get("errors"):
        problems.append(f"questions that failed to run: {', '.join(current['errors'])}")
    return problems


def compare() -> None:
    """`docent-eval-compare BASELINE CURRENT`: exit 1 when CURRENT regresses against main."""
    parser = argparse.ArgumentParser(prog="docent-eval-compare", description=compare.__doc__)
    parser.add_argument("baseline", type=Path, help="main's report (missing: no comparison)")
    parser.add_argument("current", type=Path)
    parser.add_argument(
        "--require-baseline",
        action="store_true",
        help="fail when the baseline is missing (main has run, so it should exist)",
    )
    args = parser.parse_args()
    current = json.loads(args.current.read_text(encoding="utf-8"))
    baseline = (
        json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline.is_file() else None
    )
    if baseline is None and args.require_baseline:
        print("Regression check impossible: main has run, but its report couldn't be fetched.")
        raise SystemExit(1)
    if baseline is None:
        print("No report from main to compare with: only failed questions are checked.")
    problems = regressions(baseline, current)
    for problem in problems:
        print(f"Regression: {problem}")
    if not problems:
        print("No regressions.")
    raise SystemExit(1 if problems else 0)
