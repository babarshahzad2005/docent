"""HTTP plumbing shared by the adapters: one client per call, errors mapped to ProviderError."""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2

from docent_api.providers.base import (
    ProviderError,
    ProviderRejected,
    ProviderUnavailable,
    RateLimited,
)

# The read timeout is the longest wait between streamed chunks; the deadline caps the whole call,
# so a provider that trickles out chunks can't hold a request open indefinitely.
TIMEOUT = httpx2.Timeout(30.0, connect=5.0)
DEADLINE_SECONDS = 120.0


class Stopwatch:
    """Times a call from its start, including when its first answer text arrived."""

    def __init__(self) -> None:
        self._start = time.perf_counter()
        self.first_token_ms: float | None = None

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self._start) * 1000

    def mark_first_token(self) -> None:
        if self.first_token_ms is None:
            self.first_token_ms = self.elapsed_ms()


class ProviderHttp:
    """Makes one provider's requests. Tests pass a fake transport; production uses the network."""

    def __init__(self, provider: str, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        self.provider = provider
        self._transport = transport

    def _client(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=self._transport, timeout=TIMEOUT)

    async def post_json(
        self, url: str, body: dict[str, Any], headers: dict[str, str]
    ) -> tuple[dict[str, Any], float]:
        """POST and return the decoded JSON body and the latency in milliseconds."""
        stopwatch = Stopwatch()
        try:
            async with asyncio.timeout(DEADLINE_SECONDS), self._client() as client:
                response = await client.post(url, json=body, headers=headers)
        except (httpx2.HTTPError, httpx2.StreamError) as error:
            raise ProviderUnavailable(self.provider, f"request failed: {error!r}") from error
        except TimeoutError as error:
            raise ProviderUnavailable(self.provider, "request took too long") from error
        latency_ms = stopwatch.elapsed_ms()
        self._raise_for_status(response)
        return self._decode(response.text), latency_ms

    @asynccontextmanager
    async def stream_events(
        self, url: str, body: dict[str, Any], headers: dict[str, str]
    ) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
        """POST and yield the server-sent events of the response as decoded JSON objects.

        An error the provider reports inside the stream is raised as a ProviderError.
        """
        try:
            async with (
                asyncio.timeout(DEADLINE_SECONDS),
                self._client() as client,
                client.stream("POST", url, json=body, headers=headers) as response,
            ):
                if response.status_code >= 400:
                    await response.aread()
                    self._raise_for_status(response)
                yield self._events(response)
        except (httpx2.HTTPError, httpx2.StreamError) as error:
            raise ProviderUnavailable(self.provider, f"stream failed: {error!r}") from error
        except TimeoutError as error:
            raise ProviderUnavailable(self.provider, "answer took too long") from error

    async def _events(self, response: httpx2.Response) -> AsyncIterator[dict[str, Any]]:
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line.removeprefix("data:").strip()
            if not data or data == "[DONE]":
                continue
            event = self._decode(data)
            if "error" in event:
                raise self._stream_error(event["error"])
            yield event

    def _decode(self, text: str) -> dict[str, Any]:
        try:
            decoded = json.loads(text)
        except ValueError as error:
            raise ProviderUnavailable(self.provider, "response is not JSON") from error
        if not isinstance(decoded, dict):
            raise ProviderUnavailable(self.provider, "response is not a JSON object")
        return decoded

    def _stream_error(self, error: object) -> ProviderError:
        details = error if isinstance(error, dict) else {"message": error}
        message = f"error in stream: {str(details.get('message', details))[:300]}"
        if details.get("code") == 429 or details.get("status") == "RESOURCE_EXHAUSTED":
            return RateLimited(self.provider, message)
        return ProviderUnavailable(self.provider, message)

    def _raise_for_status(self, response: httpx2.Response) -> None:
        status = response.status_code
        if status < 400:
            return
        message = f"HTTP {status}: {_error_message(response)}"
        error: ProviderError
        if status == 429:
            error = RateLimited(self.provider, message, _retry_after(response))
        elif status >= 500 or status == 408:
            error = ProviderUnavailable(self.provider, message)
        else:
            error = ProviderRejected(self.provider, message)
        raise error


def _error_message(response: httpx2.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(body, dict):
        error = body.get("error", body.get("detail", body))
        if isinstance(error, dict):
            error = error.get("message", error)
        return str(error)[:300]
    return str(body)[:300]


def _retry_after(response: httpx2.Response) -> float | None:
    """Seconds until the quota resets: the Retry-After header, or Gemini's RetryInfo detail."""
    value = response.headers.get("retry-after")
    if value is None:
        value = _gemini_retry_delay(response)
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _gemini_retry_delay(response: httpx2.Response) -> str | None:
    try:
        details = response.json()["error"]["details"]
        return next(str(d["retryDelay"]).removesuffix("s") for d in details if "retryDelay" in d)
    except (ValueError, KeyError, TypeError, StopIteration):
        return None
