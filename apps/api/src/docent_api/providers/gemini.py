"""Google Gemini: answer generation and embeddings."""

import math
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx2

from docent_api.providers._http import Http
from docent_api.providers.base import (
    Embeddings,
    Finished,
    GenerationEvent,
    Message,
    ProviderUnavailable,
    Purpose,
    TextDelta,
    Usage,
)

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_PROVIDER = "gemini"
_ROLES = {"user": "user", "assistant": "model"}
_TASK_TYPES = {Purpose.DOCUMENT: "RETRIEVAL_DOCUMENT", Purpose.QUERY: "RETRIEVAL_QUERY"}


class GeminiGenerator:
    def __init__(
        self,
        api_key: str,
        model: str,
        thinking: dict[str, Any] | None = None,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        """`thinking` is passed as Gemini's thinkingConfig, e.g. {"thinkingLevel": "minimal"}."""
        self.model = model
        self._thinking = thinking
        self._headers = {"x-goog-api-key": api_key}
        self._http = Http(_PROVIDER, transport)

    @property
    def name(self) -> str:
        return f"{_PROVIDER}:{self.model}"

    async def generate(
        self, system: str, messages: Sequence[Message], max_output_tokens: int = 1024
    ) -> AsyncIterator[GenerationEvent]:
        config: dict[str, Any] = {"maxOutputTokens": max_output_tokens}
        if self._thinking is not None:
            config["thinkingConfig"] = self._thinking
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [
                {"role": _ROLES[m.role], "parts": [{"text": m.content}]} for m in messages
            ],
            "generationConfig": config,
        }
        url = f"{_BASE_URL}/models/{self.model}:streamGenerateContent?alt=sse"
        start = time.perf_counter()
        first_token_ms: float | None = None
        version = self.model
        metadata: dict[str, Any] = {}

        async with self._http.stream_events(url, body, self._headers) as events:
            async for event in events:
                version = str(event.get("modelVersion") or version)
                metadata = event.get("usageMetadata") or metadata
                for text in _texts(event):
                    if first_token_ms is None:
                        first_token_ms = (time.perf_counter() - start) * 1000
                    yield TextDelta(text)

        output = metadata.get("candidatesTokenCount")
        thoughts = metadata.get("thoughtsTokenCount")
        if isinstance(output, int) and isinstance(thoughts, int):
            output += thoughts
        yield Finished(
            Usage(
                provider=_PROVIDER,
                model=self.model,
                model_version=version,
                latency_ms=(time.perf_counter() - start) * 1000,
                input_tokens=metadata.get("promptTokenCount"),
                output_tokens=output if isinstance(output, int) else None,
                first_token_ms=first_token_ms,
            )
        )


def _texts(event: dict[str, Any]) -> list[str]:
    candidates = event.get("candidates") or []
    if not candidates:
        return []
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return [p["text"] for p in parts if isinstance(p.get("text"), str) and not p.get("thought")]


class GeminiEmbedder:
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-embedding-001",
        dimensions: int = 1024,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._dimensions = dimensions
        self._headers = {"x-goog-api-key": api_key}
        self._http = Http(_PROVIDER, transport)

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: Sequence[str], purpose: Purpose) -> Embeddings:
        body = {
            "requests": [
                {
                    "model": f"models/{self.model}",
                    "content": {"parts": [{"text": text}]},
                    "taskType": _TASK_TYPES[purpose],
                    "outputDimensionality": self._dimensions,
                }
                for text in texts
            ]
        }
        url = f"{_BASE_URL}/models/{self.model}:batchEmbedContents"
        data, latency_ms = await self._http.post_json(url, body, self._headers)
        try:
            vectors = [_normalized(item["values"]) for item in data["embeddings"]]
        except (KeyError, TypeError, ValueError) as error:
            raise ProviderUnavailable(_PROVIDER, "unexpected embeddings response") from error
        if len(vectors) != len(texts):
            raise ProviderUnavailable(_PROVIDER, f"got {len(vectors)} of {len(texts)} vectors")
        usage = Usage(
            provider=_PROVIDER, model=self.model, model_version=self.model, latency_ms=latency_ms
        )
        return Embeddings(vectors, usage)


def _normalized(values: Sequence[float]) -> list[float]:
    """Gemini only normalizes full-size vectors; shortened ones must be normalized by the caller."""
    vector = [float(v) for v in values]
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm else vector
