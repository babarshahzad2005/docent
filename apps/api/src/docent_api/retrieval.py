"""Finding the passages that answer a question: hybrid search, filtered by permission in SQL.

Two searches run over the chunks of indexed Documents in the Collections the User may read:
vector similarity (meaning: "time off" finds "annual leave") and Postgres full-text search
(exact terms: a code, a name, a number). Their rankings are merged by reciprocal rank fusion,
which rewards passages either search ranks highly without having to compare their scores.

Permission is part of each query (a join on the User's Memberships), never a filter applied to
results afterwards (PRD principles): a passage the User can't read never leaves the database.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from psycopg import Connection
from psycopg.rows import DictRow

from docent_api.library import public_now

CANDIDATES = 30  # how many each search contributes before fusion
PASSAGES = 8  # how many passages an answer is given
# At most this many passages from one Document, so one long Document can't crowd out the
# others: when Documents disagree (#48), the answer needs to see each of them.
PER_DOCUMENT = 3
RRF_K = 60  # the usual reciprocal-rank-fusion constant; damps the advantage of rank 1

# The passages a User may read: indexed Documents in their Collections, within the Scope.
_READABLE = """
    from app.chunks c
    join app.documents d on d.id = c.document_id and d.status = 'indexed'
        and d.replaces_id is null
    join app.memberships m on m.collection_id = c.collection_id and m.user_id = %(user_id)s
    where c.collection_id = any(%(scope)s) and c.superseded_at is null
"""
# The passages a Visitor may read: the same, in Collections that are public now.
_PUBLIC_READABLE = f"""
    from app.chunks c
    join app.documents d on d.id = c.document_id and d.status = 'indexed'
        and d.replaces_id is null
    join app.collections p on p.id = c.collection_id and {public_now("p")}
    where c.collection_id = any(%(scope)s) and c.superseded_at is null
"""


def _readable(user_id: UUID | None) -> str:
    """Who reads: a User through their Memberships, or a Visitor (None) through publicity."""
    return _PUBLIC_READABLE if user_id is None else _READABLE


@dataclass(frozen=True)
class Passage:
    chunk_id: UUID
    document_id: UUID
    document_name: str
    heading_path: tuple[str, ...]
    page: int | None
    content: str
    score: float
    vector_rank: int | None
    keyword_rank: int | None
    similarity: float | None = None
    """How close in meaning to the question (cosine similarity, 1 is identical); None when
    the passage was found by keywords alone or embeddings were unavailable."""
    effective_date: date | None = None
    """The date its Document's content applies from (GLOSSARY: Effective Date)."""

    @property
    def source(self) -> str:
        """Where the passage comes from, as shown with a Citation."""
        parts = [self.document_name, *self.heading_path]
        place = " > ".join(parts)
        return f"{place}, page {self.page}" if self.page else place


def readable_scope(
    conn: Connection[DictRow], user_id: UUID, scope: Sequence[UUID] | None
) -> list[UUID]:
    """The Collections in `scope` (or all, if None) that the User is a Member of."""
    rows = conn.execute(
        """
        select collection_id from app.memberships
        where user_id = %(user_id)s
          and (%(scope)s::uuid[] is null or collection_id = any(%(scope)s::uuid[]))
        """,
        {"user_id": user_id, "scope": list(scope) if scope is not None else None},
    ).fetchall()
    return [row["collection_id"] for row in rows]


def retrieve(
    conn: Connection[DictRow],
    user_id: UUID | None,
    scope: Sequence[UUID],
    question: str,
    question_vector: Sequence[float] | None,
    limit: int = PASSAGES,
) -> list[Passage]:
    """The passages most likely to answer `question`, best first.

    Without a question vector (the embedding provider was unavailable), keyword search alone
    still finds passages. A Visitor (`user_id` None) reads only Collections public now.
    """
    readable = _readable(user_id)
    params = {"user_id": user_id, "scope": list(scope), "k": CANDIDATES, "question": question}
    vector_ids: list[UUID] = []
    similarity: dict[UUID, float] = {}
    if question_vector is not None:
        with conn.transaction():
            # The vector index finds nearest neighbours first and filters by permission after;
            # an iterative scan keeps looking until enough readable passages are found, so a
            # User with a small share of all passages still gets a full set.
            conn.execute("set local hnsw.iterative_scan = relaxed_order")
            nearest = conn.execute(
                f"""
                with nearest as materialized (
                    select c.id,
                           c.embedding operator(extensions.<=>) %(vector)s::extensions.vector
                               as distance
                    {readable} and c.embedding is not null
                    order by distance
                    limit %(k)s
                )
                select id, distance from nearest order by distance
                """,
                {**params, "vector": _vector_literal(question_vector)},
            ).fetchall()
            vector_ids = [row["id"] for row in nearest]
            similarity = {row["id"]: 1.0 - float(row["distance"]) for row in nearest}
    keyword_ids = [
        row["id"]
        for row in conn.execute(
            f"""
            with q as (
                -- Any of the question's words, not all of them: questions are phrased loosely.
                -- The words are stemmed once, as the passages were, and joined unchanged
                -- ('simple' leaves them as they are); stop-words alone give no query.
                select to_tsquery('simple', string_agg(quote_literal(lexeme), ' | ')) as query
                from unnest(tsvector_to_array(to_tsvector('english', %(question)s))) lexeme
            )
            select c.id {readable} and c.search @@ (select query from q)
            order by ts_rank_cd(c.search, (select query from q)) desc
            limit %(k)s
            """,
            params,
        ).fetchall()
    ]
    fused = _fuse(vector_ids, keyword_ids)
    found = _details(conn, fused, vector_ids, keyword_ids, similarity)
    return _spread(found, limit)


def _spread(passages: list[Passage], limit: int) -> list[Passage]:
    """The `limit` passages an answer gets, best first: at most PER_DOCUMENT from one Document,
    so a disagreeing one isn't crowded out, but only giving way to other Documents' passages
    that rank near the top (within twice `limit`); otherwise the best remain. The passage
    closest in meaning always stays, since the weak-retrieval decline depends on it."""
    pool = passages[: 2 * limit]
    keep: set[UUID] = set()
    closest = max(
        (p for p in passages if p.similarity is not None),
        key=lambda p: p.similarity or 0.0,
        default=None,
    )
    if closest is not None:
        keep.add(closest.chunk_id)
    per: dict[UUID, int] = {}
    if closest is not None:
        per[closest.document_id] = 1
    for passage in pool:
        if len(keep) == limit:
            break
        if passage.chunk_id in keep:
            continue
        if per.get(passage.document_id, 0) < PER_DOCUMENT:
            keep.add(passage.chunk_id)
            per[passage.document_id] = per.get(passage.document_id, 0) + 1
    for passage in passages:  # not enough near-top Documents: the best of the rest
        if len(keep) == limit:
            break
        keep.add(passage.chunk_id)
    return [p for p in passages if p.chunk_id in keep]


def _fuse(*rankings: list[UUID]) -> list[tuple[UUID, float]]:
    scores: dict[UUID, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def _details(
    conn: Connection[DictRow],
    fused: list[tuple[UUID, float]],
    vector_ids: list[UUID],
    keyword_ids: list[UUID],
    similarity: dict[UUID, float],
) -> list[Passage]:
    if not fused:
        return []
    rows = conn.execute(
        """
        select c.id, c.document_id, d.name, c.heading_path, c.page, c.content, d.effective_date
        from app.chunks c join app.documents d on d.id = c.document_id
        where c.id = any(%s)
        """,
        ([chunk_id for chunk_id, _ in fused],),
    ).fetchall()
    by_id = {row["id"]: row for row in rows}
    passages = []
    for chunk_id, score in fused:
        row = by_id.get(chunk_id)
        if row is None:
            continue  # deleted between the searches and now
        passages.append(
            Passage(
                chunk_id=chunk_id,
                document_id=row["document_id"],
                document_name=row["name"],
                heading_path=tuple(row["heading_path"]),
                page=row["page"],
                content=row["content"],
                score=score,
                vector_rank=_rank(vector_ids, chunk_id),
                keyword_rank=_rank(keyword_ids, chunk_id),
                similarity=similarity.get(chunk_id),
                effective_date=row["effective_date"],
            )
        )
    return passages


def documents_state(conn: Connection[DictRow], user_id: UUID | None, scope: Sequence[UUID]) -> str:
    """What the User (or a Visitor, None) can search in `scope`: "indexed" (some Document is
    ready), "processing" (none is ready, but some is still on its way), or "none"."""
    access = (
        f"join app.collections p on p.id = d.collection_id and {public_now('p')}"
        if user_id is None
        else "join app.memberships m on m.collection_id = d.collection_id"
        " and m.user_id = %(user_id)s"
    )
    row = conn.execute(
        f"""
        select bool_or(d.status = 'indexed') as indexed,
               bool_or(d.status not in ('indexed', 'failed')) as processing
        from app.documents d
        {access}
        where d.collection_id = any(%(scope)s::uuid[])
        """,
        {"user_id": user_id, "scope": list(scope)},
    ).fetchone()
    if row is not None and row["indexed"]:
        return "indexed"
    if row is not None and row["processing"]:
        return "processing"
    return "none"


def _rank(ranking: list[UUID], chunk_id: UUID) -> int | None:
    return ranking.index(chunk_id) + 1 if chunk_id in ranking else None


def _vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in vector) + "]"


class PassageNotFound(Exception):
    """No such passage that the User (or Visitor) can read."""


def passage_in_context(
    conn: Connection[DictRow],
    user_id: UUID | None,
    chunk_id: UUID,
    public_collection: UUID | None = None,
) -> dict[str, object]:
    """A passage with the passages just before and after it in the same section.

    Readable only through a Membership of its Collection, like every other read of passages;
    or, for a Visitor (`user_id` None), only in `public_collection` while it is public.
    """
    if user_id is None:
        if public_collection is None:
            raise PassageNotFound(chunk_id)
        access = (
            "join app.collections p on p.id = c.collection_id and p.id = %(public)s"
            f" and {public_now('p')}"
        )
    else:
        access = (
            "join app.memberships m on m.collection_id = c.collection_id"
            " and m.user_id = %(user_id)s"
        )
    row = conn.execute(
        f"""
        select c.id as chunk_id, c.document_id, d.name as document_name, c.heading_path,
               c.page, c.content, c.ordinal, c.superseded_at is not null as replaced,
               c.superseded_at
        from app.chunks c
        join app.documents d on d.id = c.document_id and d.status = 'indexed'
        {access}
        where c.id = %(chunk)s
        """,
        {"user_id": user_id, "public": public_collection, "chunk": chunk_id},
    ).fetchone()
    if row is None:
        raise PassageNotFound(chunk_id)
    neighbours = {
        neighbour["ordinal"]: neighbour["content"]
        for neighbour in conn.execute(
            """
            select ordinal, content from app.chunks
            where document_id = %(document)s and ordinal in (%(before)s, %(after)s)
              and heading_path = %(path)s and page is not distinct from %(page)s
              and superseded_at is not distinct from %(superseded)s  -- the same version
            """,
            {
                "document": row["document_id"],
                "before": row["ordinal"] - 1,
                "after": row["ordinal"] + 1,
                "path": row["heading_path"],
                "page": row["page"],
                "superseded": row["superseded_at"],
            },
        ).fetchall()
    }
    return {
        **{key: value for key, value in row.items() if key not in ("ordinal", "superseded_at")},
        "before": neighbours.get(row["ordinal"] - 1),
        "after": neighbours.get(row["ordinal"] + 1),
    }
