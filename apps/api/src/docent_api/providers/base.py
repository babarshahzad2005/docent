"""The one interface every model call goes through: embedding, reranking, and generation.

Application code depends on these protocols and types only. Each provider adapter turns its
API's responses into them and its failures into the errors below, so providers can be swapped
or chained without touching callers.
"""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol


@dataclass(frozen=True)
class Usage:
    """What one model call cost and how it went, as recorded in the Answer Log."""

    provider: str
    model: str
    model_version: str
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    first_token_ms: float | None = None
    fell_back_from: str | None = None


class Purpose(StrEnum):
    """Retrieval models embed stored passages and search queries differently."""

    PASSAGE = "passage"
    QUERY = "query"


@dataclass(frozen=True)
class Embeddings:
    vectors: list[list[float]]
    usage: Usage


@dataclass(frozen=True)
class RankedPassage:
    index: int
    score: float


@dataclass(frozen=True)
class Ranking:
    """Passages most relevant first; `index` points into the passages that were ranked."""

    passages: list[RankedPassage]
    usage: Usage


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class Finished:
    usage: Usage


GenerationEvent = TextDelta | Finished


class Embedder(Protocol):
    @property
    def dimensions(self) -> int: ...

    async def embed(self, texts: Sequence[str], purpose: Purpose) -> Embeddings: ...


class Reranker(Protocol):
    async def rerank(
        self, query: str, passages: Sequence[str], top_k: int | None = None
    ) -> Ranking: ...


class Generator(Protocol):
    @property
    def name(self) -> str: ...

    def generate(
        self,
        system: str,
        messages: Sequence[Message],
        max_output_tokens: int = 1024,
        temperature: float | None = None,
    ) -> AsyncIterator[GenerationEvent]:
        """Stream the answer as text deltas, ending with exactly one Finished event.

        An answer with no text (blocked, or the budget spent on hidden reasoning) is an error,
        so a fallback can step in. `temperature` None leaves the provider's default.
        """
        ...


class ProviderError(Exception):
    """A model call failed. Subclasses say whether trying again later can help."""

    def __init__(self, provider: str, message: str) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider


class RateLimited(ProviderError):
    """The provider's quota is used up for now."""

    def __init__(self, provider: str, message: str, retry_after: float | None = None) -> None:
        super().__init__(provider, message)
        self.retry_after = retry_after


class ProviderUnavailable(ProviderError):
    """The provider is down, slow, or unreachable."""


class ProviderRejected(ProviderError):
    """The provider refused the request (bad key, unknown model, invalid input)."""
