"""Voyage AI: embeddings and reranking."""

from collections.abc import Sequence
from typing import Any

import httpx2

from docent_api.providers._http import Http
from docent_api.providers.base import (
    Embeddings,
    ProviderUnavailable,
    Purpose,
    RankedPassage,
    Ranking,
    Usage,
)

_BASE_URL = "https://api.voyageai.com/v1"
_PROVIDER = "voyage"


class _Voyage:
    def __init__(
        self, api_key: str, model: str, transport: httpx2.AsyncBaseTransport | None = None
    ) -> None:
        self.model = model
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._http = Http(_PROVIDER, transport)

    def _usage(self, data: dict[str, Any], latency_ms: float) -> Usage:
        model = str(data.get("model") or self.model)
        tokens = data.get("usage", {}).get("total_tokens")
        return Usage(
            provider=_PROVIDER,
            model=model,
            model_version=model,  # Voyage publishes no finer-grained version
            latency_ms=latency_ms,
            input_tokens=tokens if isinstance(tokens, int) else None,
        )


class VoyageEmbedder(_Voyage):
    def __init__(
        self,
        api_key: str,
        model: str = "voyage-4",
        dimensions: int = 1024,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(api_key, model, transport)
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: Sequence[str], purpose: Purpose) -> Embeddings:
        body = {
            "input": list(texts),
            "model": self.model,
            "input_type": purpose.value,
            "output_dimension": self._dimensions,
        }
        data, latency_ms = await self._http.post_json(
            f"{_BASE_URL}/embeddings", body, self._headers
        )
        try:
            items = sorted(data["data"], key=lambda item: item["index"])
            vectors = [[float(x) for x in item["embedding"]] for item in items]
        except (KeyError, TypeError, ValueError) as error:
            raise ProviderUnavailable(_PROVIDER, "unexpected embeddings response") from error
        if len(vectors) != len(texts):
            raise ProviderUnavailable(_PROVIDER, f"got {len(vectors)} of {len(texts)} vectors")
        return Embeddings(vectors, self._usage(data, latency_ms))


class VoyageReranker(_Voyage):
    def __init__(
        self,
        api_key: str,
        model: str = "rerank-2.5-lite",
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(api_key, model, transport)

    async def rerank(
        self, query: str, passages: Sequence[str], top_k: int | None = None
    ) -> Ranking:
        body: dict[str, Any] = {"query": query, "documents": list(passages), "model": self.model}
        if top_k is not None:
            body["top_k"] = top_k
        data, latency_ms = await self._http.post_json(f"{_BASE_URL}/rerank", body, self._headers)
        try:
            ranked = [
                RankedPassage(index=int(item["index"]), score=float(item["relevance_score"]))
                for item in data["data"]
            ]
        except (KeyError, TypeError, ValueError) as error:
            raise ProviderUnavailable(_PROVIDER, "unexpected rerank response") from error
        ranked.sort(key=lambda passage: passage.score, reverse=True)
        return Ranking(ranked, self._usage(data, latency_ms))
