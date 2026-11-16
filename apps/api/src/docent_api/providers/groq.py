"""Groq: answer generation through its OpenAI-compatible chat API."""

from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx2

from docent_api.providers._http import ProviderHttp, Stopwatch
from docent_api.providers.base import (
    Finished,
    GenerationEvent,
    Message,
    ProviderUnavailable,
    TextDelta,
    Usage,
)

_URL = "https://api.groq.com/openai/v1/chat/completions"
_PROVIDER = "groq"


class GroqGenerator:
    def __init__(
        self,
        api_key: str,
        model: str,
        reasoning_effort: str | None = None,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        """`reasoning_effort` (e.g. "low") applies to reasoning models; reasoning stays hidden."""
        self.model = model
        self._reasoning_effort = reasoning_effort
        self._headers = {"Authorization": f"Bearer {api_key}"}
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
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}]
            + [{"role": m.role, "content": m.content} for m in messages],
            "max_completion_tokens": max_output_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if temperature is not None:
            body["temperature"] = temperature
        if self._reasoning_effort is not None:
            body["reasoning_effort"] = self._reasoning_effort
            body["reasoning_format"] = "hidden"
        stopwatch = Stopwatch()
        version = self.model
        usage: dict[str, Any] = {}
        stop_reason = "none given"

        async with self._http.stream_events(_URL, body, self._headers) as events:
            async for event in events:
                version = _version(event) or version
                usage = event.get("usage") or (event.get("x_groq") or {}).get("usage") or usage
                for choice in event.get("choices") or []:
                    stop_reason = choice.get("finish_reason") or stop_reason
                    text = (choice.get("delta") or {}).get("content")
                    if isinstance(text, str) and text:
                        stopwatch.mark_first_token()
                        yield TextDelta(text)

        if stopwatch.first_token_ms is None:
            raise ProviderUnavailable(_PROVIDER, f"no answer text (stop reason: {stop_reason})")
        yield Finished(
            Usage(
                provider=_PROVIDER,
                model=self.model,
                model_version=version,
                latency_ms=stopwatch.elapsed_ms(),
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
                first_token_ms=stopwatch.first_token_ms,
            )
        )


def _version(event: dict[str, Any]) -> str | None:
    """The served model plus Groq's deployment fingerprint, e.g. "openai/gpt-oss-120b@fp_1"."""
    model = event.get("model")
    if not model:
        return None
    fingerprint = event.get("system_fingerprint")
    return f"{model}@{fingerprint}" if fingerprint else str(model)
