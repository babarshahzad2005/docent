"""Google Gemini: answer generation and embeddings."""

import math
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx2

from docent_api.providers._http import ProviderHttp, Stopwatch
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
from docent_api.providers.vectors import check_count

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_PROVIDER = "gemini"
_ROLES = {"user": "user", "assistant": "model"}
_TASK_TYPES = {Purpose.PASSAGE: "RETRIEVAL_DOCUMENT", Purpose.QUERY: "RETRIEVAL_QUERY"}
_MAX_BATCH = 100  # batchEmbedContents accepts at most 100 texts per request


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
        self._http = ProviderHttp(_PROVIDER, transport)

    @property
    def name(self) -> str:
        return f"{_PROVIDER}:{self.model}"

    async def generate(
        self,
        system: str,
        messages: Sequence[Message],
        max_output_tokens: int = 1024,
        temperature: float | None = None,
    ) -> AsyncIterator[GenerationEvent]:
        config: dict[str, Any] = {"maxOutputTokens": max_output_tokens}
        if temperature is not None:
            config["temperature"] = temperature
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
        stopwatch = Stopwatch()
        version = self.model
        metadata: dict[str, Any] = {}
        stop_reason = "none given"

        async with self._http.stream_events(url, body, self._headers) as events:
            async for event in events:
                version = str(event.get("modelVersion") or version)
                metadata = event.get("usageMetadata") or metadata
                stop_reason = _stop_reason(event) or stop_reason
                for text in _answer_texts(event):
                    stopwatch.mark_first_token()
                    yield TextDelta(text)

        if stopwatch.first_token_ms is None:
            raise ProviderUnavailable(_PROVIDER, f"no answer text (stop reason: {stop_reason})")
        output = metadata.get("candidatesTokenCount")
        thoughts = metadata.get("thoughtsTokenCount")
        if isinstance(output, int) and isinstance(thoughts, int):
            output += thoughts
        yield Finished(
            Usage(
                provider=_PROVIDER,
                model=self.model,
                model_version=version,
                latency_ms=stopwatch.elapsed_ms(),
                input_tokens=metadata.get("promptTokenCount"),
                output_tokens=output if isinstance(output, int) else None,
                first_token_ms=stopwatch.first_token_ms,
            )
        )


def _answer_texts(event: dict[str, Any]) -> list[str]:
    """The visible answer text in one streamed event, leaving out the model's thoughts."""
    candidates = event.get("candidates") or []
    if not candidates:
        return []
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return [p["text"] for p in parts if isinstance(p.get("text"), str) and not p.get("thought")]


def _stop_reason(event: dict[str, Any]) -> str | None:
    blocked = (event.get("promptFeedback") or {}).get("blockReason")
    if blocked:
        return f"prompt blocked: {blocked}"
    candidates = event.get("candidates") or []
    reason = candidates[0].get("finishReason") if candidates else None
    return str(reason) if reason else None


class GeminiEmbedder:
    """Gemini reports no token counts for embeddings, so Usage.input_tokens stays None."""

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
        self._http = ProviderHttp(_PROVIDER, transport)

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: Sequence[str], purpose: Purpose) -> Embeddings:
        vectors: list[list[float]] = []
        latency_ms = 0.0
        for start in range(0, len(texts), _MAX_BATCH):
            batch, batch_ms = await self._embed_batch(texts[start : start + _MAX_BATCH], purpose)
            vectors += batch
            latency_ms += batch_ms
        usage = Usage(
            provider=_PROVIDER, model=self.model, model_version=self.model, latency_ms=latency_ms
        )
        return Embeddings(vectors, usage)

    async def _embed_batch(
        self, texts: Sequence[str], purpose: Purpose
    ) -> tuple[list[list[float]], float]:
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
        check_count(_PROVIDER, vectors, texts)
        return vectors, latency_ms


def _normalized(values: Sequence[float]) -> list[float]:
    """Gemini only normalizes full-size vectors; shortened ones must be normalized by the caller."""
    vector = [float(v) for v in values]
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm else vector
