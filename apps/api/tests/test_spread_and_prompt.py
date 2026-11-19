"""Passages from several Documents reach the answer, each with its Effective Date (#48)."""

from datetime import date
from uuid import UUID, uuid4

from docent_api.answers import SYSTEM_PROMPT, build_prompt
from docent_api.retrieval import PER_DOCUMENT, Passage, _spread


def passage(document: UUID, text: str, effective: date | None = None) -> Passage:
    return Passage(uuid4(), document, "doc.md", (), None, text, 0.0, 1, None, 0.7, effective)


def test_one_long_document_cannot_crowd_out_the_others() -> None:
    reforms, guidance = uuid4(), uuid4()
    ranked = [passage(reforms, f"reforms {n}") for n in range(8)] + [
        passage(guidance, "guidance 1")
    ]

    chosen = _spread(ranked, limit=8)

    assert [p.content for p in chosen][:PER_DOCUMENT] == ["reforms 0", "reforms 1", "reforms 2"]
    assert "guidance 1" in [p.content for p in chosen]
    assert len(chosen) == 8  # the rest is filled from the long Document, best first


def test_with_one_document_the_best_passages_are_kept() -> None:
    only = uuid4()
    ranked = [passage(only, f"p{n}") for n in range(10)]

    assert [p.content for p in _spread(ranked, limit=8)] == [f"p{n}" for n in range(8)]


def test_each_source_shows_its_effective_date_and_the_rule_says_newer_wins() -> None:
    prompt = build_prompt(
        "How is holiday worked out?",
        [
            passage(uuid4(), "12.07% of hours worked", date(2024, 1, 1)),
            passage(uuid4(), "a representative reference period", date(2019, 11, 1)),
            passage(uuid4(), "no date known"),
        ],
    )

    assert "[1] Source: doc.md (effective 2024-01-01)" in prompt
    assert "[2] Source: doc.md (effective 2019-11-01)" in prompt
    assert "[3] Source: doc.md\n" in prompt
    assert "answer from the one with the later date" in SYSTEM_PROMPT
