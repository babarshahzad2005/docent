"""Groq: answer generation through its OpenAI-compatible chat API."""

import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx2

from docent_api.providers._http import Http
from docent_api.providers.base import Finished, GenerationEvent, Message, TextDelta, Usage

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
        self._http = Http(_PROVIDER, transport)

    @property
    def name(self) -> str:
        return f"{_PROVIDER}:{self.model}"

    async def generate(
        self, system: str, messages: Sequence[Message], max_output_tokens: int = 1024
    ) -> AsyncIterator[GenerationEvent]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}]
            + [{"role": m.role, "content": m.content} for m in messages],
            "max_completion_tokens": max_output_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if self._reasoning_effort is not None:
            body["reasoning_effort"] = self._reasoning_effort
            body["reasoning_format"] = "hidden"
        start = time.perf_counter()
        first_token_ms: float | None = None
        version = self.model
        usage: dict[str, Any] = {}

        async with self._http.stream_events(_URL, body, self._headers) as events:
            async for event in events:
                fingerprint = event.get("system_fingerprint")
                version = f"{event.get('model') or self.model}" + (
                    f"@{fingerprint}" if fingerprint else ""
                )
                usage = event.get("usage") or (event.get("x_groq") or {}).get("usage") or usage
                for choice in event.get("choices") or []:
                    text = (choice.get("delta") or {}).get("content")
                    if isinstance(text, str) and text:
                        if first_token_ms is None:
                            first_token_ms = (time.perf_counter() - start) * 1000
                        yield TextDelta(text)

        yield Finished(
            Usage(
                provider=_PROVIDER,
                model=self.model,
                model_version=version,
                latency_ms=(time.perf_counter() - start) * 1000,
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
                first_token_ms=first_token_ms,
            )
        )
