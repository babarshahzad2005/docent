"""Passages from several Documents reach the answer, each with its Effective Date (#48)."""

from datetime import date
from uuid import UUID, uuid4

from docent_api.answers import SYSTEM_PROMPT, build_prompt
from docent_api.retrieval import PER_DOCUMENT, Passage, _spread


def passage(
    document: UUID, text: str, effective: date | None = None, similarity: float = 0.7
) -> Passage:
    return Passage(
        chunk_id=uuid4(),
        document_id=document,
        document_name="doc.md",
        heading_path=(),
        page=None,
        content=text,
        score=0.0,
        vector_rank=1,
        keyword_rank=None,
        similarity=similarity,
        effective_date=effective,
    )


def test_one_long_document_cannot_crowd_out_the_others() -> None:
    reforms, guidance = uuid4(), uuid4()
    ranked = [passage(reforms, f"reforms {n}") for n in range(8)] + [
        passage(guidance, "guidance 1")
    ]

    chosen = _spread(ranked, limit=8)

    assert [p.content for p in chosen][:PER_DOCUMENT] == ["reforms 0", "reforms 1", "reforms 2"]
    assert "guidance 1" in [p.content for p in chosen]
    assert len(chosen) == 8  # the rest is filled from the long Document
    assert [p.content for p in chosen] == [p.content for p in ranked if p in chosen]  # best first


def test_a_passage_far_down_the_ranking_does_not_displace_a_strong_one() -> None:
    policy, other = uuid4(), uuid4()
    ranked = [passage(policy, f"policy {n}") for n in range(20)] + [passage(other, "weak")]

    chosen = _spread(ranked, limit=8)

    assert [p.content for p in chosen] == [f"policy {n}" for n in range(8)]


def test_the_passage_closest_in_meaning_always_stays() -> None:
    a = uuid4()
    ranked = [passage(a, f"a{n}", similarity=0.70) for n in range(3)]
    ranked += [passage(uuid4(), f"b{n}", similarity=0.60) for n in range(6)]
    ranked.insert(9, passage(a, "a-closest", similarity=0.90))

    assert "a-closest" in [p.content for p in _spread(ranked, limit=8)]


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
    assert "Answer from the document with the latest date" in SYSTEM_PROMPT
