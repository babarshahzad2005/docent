"""Adapter tests against recorded response shapes; no network access or API keys needed."""

import asyncio
import json
import math
from collections.abc import AsyncIterator, Callable, Coroutine, Sequence
from pathlib import Path
from typing import Any

import httpx2
import pytest

from docent_api.providers import _http
from docent_api.providers.base import (
    Finished,
    GenerationEvent,
    Generator,
    Message,
    ProviderError,
    ProviderRejected,
    ProviderUnavailable,
    Purpose,
    RateLimited,
    TextDelta,
    Usage,
)
from docent_api.providers.fallback import FallbackGenerator
from docent_api.providers.gemini import GeminiEmbedder, GeminiGenerator
from docent_api.providers.groq import GroqGenerator
from docent_api.providers.registry import answer_generator, generator_for
from docent_api.providers.voyage import VoyageEmbedder, VoyageReranker
from docent_api.settings import Settings

QUESTION = [Message("user", "How much leave carries over?")]


def run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coroutine)


class Recorder:
    """A fake provider: answers every request with `respond` and keeps the requests it saw."""

    def __init__(self, respond: Callable[[httpx2.Request], httpx2.Response]) -> None:
        self.requests: list[httpx2.Request] = []
        self._respond = respond
        self.transport = httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self._respond(request)

    def body(self, n: int = 0) -> dict[str, Any]:
        decoded: dict[str, Any] = json.loads(self.requests[n].content)
        return decoded


def replying(status: int = 200, **kwargs: Any) -> Recorder:
    return Recorder(lambda _: httpx2.Response(status, **kwargs))


def gemini_text(text: str) -> dict[str, Any]:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def sse(*events: dict[str, Any] | str) -> bytes:
    lines = [f"data: {e if isinstance(e, str) else json.dumps(e)}\n\n" for e in events]
    return "".join(lines).encode()


async def collect(stream: AsyncIterator[GenerationEvent]) -> tuple[str, Usage]:
    text, usage = "", None
    async for event in stream:
        if isinstance(event, TextDelta):
            text += event.text
        else:
            assert usage is None, "exactly one Finished event"
            usage = event.usage
    assert usage is not None
    return text, usage


# --- Voyage -------------------------------------------------------------------------------


def test_voyage_embeds_in_input_order() -> None:
    fake = replying(
        json={
            "data": [{"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]}],
            "model": "voyage-4",
            "usage": {"total_tokens": 7},
        }
    )
    embedder = VoyageEmbedder("key", dimensions=2, transport=fake.transport)

    result = run(embedder.embed(["first", "second"], Purpose.QUERY))

    assert result.vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert result.usage.model == "voyage-4"
    assert result.usage.input_tokens == 7
    assert fake.body() == {
        "input": ["first", "second"],
        "model": "voyage-4",
        "input_type": "query",
        "output_dimension": 2,
    }
    assert fake.requests[0].headers["authorization"] == "Bearer key"


def test_voyage_reranks_most_relevant_first() -> None:
    fake = replying(
        json={
            "data": [{"index": 0, "relevance_score": 0.2}, {"index": 1, "relevance_score": 0.9}],
            "model": "rerank-2.5-lite",
            "usage": {"total_tokens": 4},
        }
    )
    reranker = VoyageReranker("key", transport=fake.transport)

    ranking = run(reranker.rerank("cat", ["a dog", "a cat"], top_k=2))

    assert [p.index for p in ranking.passages] == [1, 0]
    assert ranking.passages[0].score == 0.9
    assert fake.body()["top_k"] == 2


def test_a_short_embeddings_response_is_an_error() -> None:
    fake = replying(json={"data": [{"index": 0, "embedding": [1.0]}], "usage": {}})
    embedder = VoyageEmbedder("key", dimensions=1, transport=fake.transport)

    with pytest.raises(ProviderUnavailable):
        run(embedder.embed(["one", "two"], Purpose.PASSAGE))


# --- Gemini -------------------------------------------------------------------------------


def test_gemini_embeddings_are_normalized() -> None:
    fake = replying(json={"embeddings": [{"values": [3.0, 4.0]}, {"values": [0.0, 2.0]}]})
    embedder = GeminiEmbedder("key", dimensions=2, transport=fake.transport)

    result = run(embedder.embed(["a", "b"], Purpose.PASSAGE))

    assert result.vectors == [[0.6, 0.8], [0.0, 1.0]]
    assert all(math.isclose(math.hypot(*v), 1.0) for v in result.vectors)
    request = fake.body()["requests"][0]
    assert request["taskType"] == "RETRIEVAL_DOCUMENT"
    assert request["outputDimensionality"] == 2
    assert fake.requests[0].headers["x-goog-api-key"] == "key"


def test_gemini_streams_answer_text_without_thoughts() -> None:
    fake = replying(
        content=sse(
            {"candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True}]}}]},
            {"candidates": [{"content": {"parts": [{"text": "Up to 10 days "}]}}]},
            {
                "candidates": [{"content": {"parts": [{"text": "carry over [1]."}]}}],
                "usageMetadata": {
                    "promptTokenCount": 120,
                    "candidatesTokenCount": 9,
                    "thoughtsTokenCount": 3,
                },
                "modelVersion": "gemini-3.5-flash-lite-001",
            },
        ),
        headers={"content-type": "text/event-stream"},
    )
    generator = GeminiGenerator(
        "key", "gemini-3.5-flash-lite", {"thinkingLevel": "minimal"}, transport=fake.transport
    )

    text, usage = run(collect(generator.generate("Answer from passages.", QUESTION, 200)))

    assert text == "Up to 10 days carry over [1]."
    assert usage.model_version == "gemini-3.5-flash-lite-001"
    assert (usage.input_tokens, usage.output_tokens) == (120, 12)
    assert usage.first_token_ms is not None
    assert usage.latency_ms >= usage.first_token_ms
    body = fake.body()
    assert body["systemInstruction"] == {"parts": [{"text": "Answer from passages."}]}
    assert body["contents"] == [{"role": "user", "parts": [{"text": QUESTION[0].content}]}]
    assert body["generationConfig"] == {
        "maxOutputTokens": 200,
        "thinkingConfig": {"thinkingLevel": "minimal"},
    }
    assert "alt=sse" in str(fake.requests[0].url)


def test_gemini_sends_earlier_answers_as_model_turns() -> None:
    fake = replying(content=sse(gemini_text("ok")))
    generator = GeminiGenerator("key", "m", transport=fake.transport)
    history = [Message("user", "q1"), Message("assistant", "a1"), Message("user", "q2")]

    run(collect(generator.generate("s", history)))

    assert [c["role"] for c in fake.body()["contents"]] == ["user", "model", "user"]


# --- Groq ---------------------------------------------------------------------------------


def test_groq_streams_answer_text_and_usage() -> None:
    chunk = {"model": "openai/gpt-oss-120b", "system_fingerprint": "fp_1"}
    fake = replying(
        content=sse(
            {**chunk, "choices": [{"delta": {"role": "assistant", "content": ""}}]},
            {**chunk, "choices": [{"delta": {"reasoning": "hidden"}}]},
            {**chunk, "choices": [{"delta": {"content": "Up to 10 days"}}]},
            {**chunk, "choices": [{"delta": {"content": " [1]."}}]},
            {
                **chunk,
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "x_groq": {"usage": {"prompt_tokens": 150, "completion_tokens": 6}},
            },
            "[DONE]",
        )
    )
    generator = GroqGenerator(
        "key", "openai/gpt-oss-120b", reasoning_effort="low", transport=fake.transport
    )

    text, usage = run(collect(generator.generate("Answer from passages.", QUESTION, 200)))

    assert text == "Up to 10 days [1]."
    assert usage.model_version == "openai/gpt-oss-120b@fp_1"
    assert (usage.input_tokens, usage.output_tokens) == (150, 6)
    body = fake.body()
    assert body["messages"][0] == {"role": "system", "content": "Answer from passages."}
    assert body["stream"] is True
    assert body["reasoning_effort"] == "low"
    assert body["reasoning_format"] == "hidden"
    assert body["max_completion_tokens"] == 200


def test_qwens_reasoning_is_kept_out_of_the_answer_without_an_effort() -> None:
    chunk = {"model": "qwen/qwen3.8-27b"}
    fake = replying(
        content=sse(
            {**chunk, "choices": [{"delta": {"content": "4"}}]},
            {**chunk, "choices": [{"delta": {}, "finish_reason": "stop"}]},
            "[DONE]",
        )
    )
    generator = generator_for("groq:qwen/qwen3.8-27b", Settings())
    generator._http = GroqGenerator("key", "qwen/qwen3.8-27b", transport=fake.transport)._http  # type: ignore[attr-defined]

    run(collect(generator.generate("Answer briefly.", QUESTION, 50)))

    body = fake.body()
    assert body["reasoning_format"] == "hidden" and "reasoning_effort" not in body


def test_groq_reads_usage_from_the_final_usage_chunk() -> None:
    fake = replying(
        content=sse(
            {"choices": [{"delta": {"content": "Hi"}}]},
            {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 1}},
        )
    )
    generator = GroqGenerator("key", "qwen/qwen3.8-27b", transport=fake.transport)

    _, usage = run(collect(generator.generate("s", QUESTION)))

    assert (usage.input_tokens, usage.output_tokens) == (5, 1)
    assert "reasoning_effort" not in fake.body()


# --- Errors -------------------------------------------------------------------------------


def _generators(transport: httpx2.AsyncBaseTransport) -> list[Generator]:
    return [
        GeminiGenerator("key", "m", transport=transport),
        GroqGenerator("key", "m", transport=transport),
    ]


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (429, RateLimited),
        (503, ProviderUnavailable),
        (500, ProviderUnavailable),
        (401, ProviderRejected),
        (404, ProviderRejected),
    ],
)
def test_http_failures_become_provider_errors(status: int, error: type[ProviderError]) -> None:
    fake = replying(status, json={"error": {"message": "nope"}}, headers={"retry-after": "7"})
    embedder = VoyageEmbedder("key", transport=fake.transport)

    with pytest.raises(error, match="nope") as raised:
        run(embedder.embed(["a"], Purpose.QUERY))
    if isinstance(raised.value, RateLimited):
        assert raised.value.retry_after == 7.0

    for generator in _generators(fake.transport):
        with pytest.raises(error):
            run(collect(generator.generate("s", QUESTION)))


def test_network_failures_mean_unavailable() -> None:
    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=request)

    transport = httpx2.MockTransport(down)

    with pytest.raises(ProviderUnavailable):
        run(GeminiEmbedder("key", transport=transport).embed(["a"], Purpose.QUERY))
    for generator in _generators(transport):
        with pytest.raises(ProviderUnavailable):
            run(collect(generator.generate("s", QUESTION)))


# --- Fallback -----------------------------------------------------------------------------


class ScriptedGenerator:
    """Streams `chunks`, then raises `error` if given."""

    def __init__(self, name: str, chunks: Sequence[str], error: ProviderError | None = None):
        self._name = name
        self._chunks = chunks
        self._error = error
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    async def generate(
        self,
        system: str,
        messages: Sequence[Message],
        max_output_tokens: int = 1024,
        temperature: float | None = None,
    ) -> AsyncIterator[GenerationEvent]:
        self.calls += 1
        for chunk in self._chunks:
            yield TextDelta(chunk)
        if self._error:
            raise self._error
        yield Finished(Usage(self._name, self._name, self._name, latency_ms=1.0))


def test_the_primary_answers_when_it_works() -> None:
    primary, backup = ScriptedGenerator("primary", ["ok"]), ScriptedGenerator("backup", ["no"])

    text, usage = run(collect(FallbackGenerator(primary, backup).generate("s", QUESTION)))

    assert (text, usage.provider, usage.fell_back_from) == ("ok", "primary", None)
    assert backup.calls == 0


@pytest.mark.parametrize(
    "error", [RateLimited("primary", "quota"), ProviderUnavailable("primary", "down")]
)
def test_the_backup_answers_when_the_primary_fails_first(error: ProviderError) -> None:
    primary = ScriptedGenerator("primary", [], error)
    backup = ScriptedGenerator("backup", ["from ", "backup"])

    text, usage = run(collect(FallbackGenerator(primary, backup).generate("s", QUESTION)))

    assert text == "from backup"
    assert usage.provider == "backup"
    assert usage.fell_back_from == "primary"


def test_a_failure_mid_answer_is_not_spliced_with_another_model() -> None:
    primary = ScriptedGenerator("primary", ["half an "], ProviderUnavailable("primary", "cut"))
    backup = ScriptedGenerator("backup", ["other answer"])

    with pytest.raises(ProviderUnavailable):
        run(collect(FallbackGenerator(primary, backup).generate("s", QUESTION)))
    assert backup.calls == 0


def test_the_backup_failing_too_is_reported() -> None:
    primary = ScriptedGenerator("primary", [], RateLimited("primary", "quota"))
    backup = ScriptedGenerator("backup", [], ProviderUnavailable("backup", "down"))

    with pytest.raises(ProviderUnavailable, match="backup"):
        run(collect(FallbackGenerator(primary, backup).generate("s", QUESTION)))


# --- Registry -----------------------------------------------------------------------------


def test_the_configured_answer_models_are_used() -> None:
    settings = Settings(
        answer_model="groq:openai/gpt-oss-120b", fallback_answer_model="gemini:flash-lite"
    )

    generator = answer_generator(settings)

    assert isinstance(generator, FallbackGenerator)
    assert generator.primary.name == "groq:openai/gpt-oss-120b"
    assert generator.fallback.name == "gemini:flash-lite"


def test_fallbacks_are_tried_in_the_order_given() -> None:
    generator = answer_generator(Settings())  # the defaults (ADR 0010)

    assert isinstance(generator, FallbackGenerator)
    assert generator.primary.name == "groq:openai/gpt-oss-120b"
    second = generator.fallback
    assert isinstance(second, FallbackGenerator)
    assert second.primary.name == "groq:qwen/qwen3.8-27b"
    assert second.fallback.name == "gemini:gemini-3.5-flash-lite"


@pytest.mark.parametrize("spec", ["gpt-4", "openai:gpt-4", "groq:"])
def test_unknown_answer_models_are_rejected(spec: str) -> None:
    with pytest.raises(ValueError):
        generator_for(spec, Settings())


def test_only_the_adapters_talk_to_providers() -> None:
    package = Path(__file__).parents[1] / "src" / "docent_api"
    allowed = {"providers", "measure_models.py", "storage.py"}  # storage talks to Supabase
    offenders = [
        str(path.relative_to(package))
        for path in package.rglob("*.py")
        if path.relative_to(package).parts[0] not in allowed
        and "httpx2" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


# --- Answers that aren't answers ----------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ({"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}, RateLimited),
        ({"code": 500, "message": "internal"}, ProviderUnavailable),
        ("overloaded", ProviderUnavailable),
    ],
)
def test_errors_reported_inside_the_stream_are_raised(
    error: object, expected: type[ProviderError]
) -> None:
    fake = replying(content=sse({"error": error}))

    for generator in _generators(fake.transport):
        with pytest.raises(expected, match="error in stream"):
            run(collect(generator.generate("s", QUESTION)))


def test_a_blocked_gemini_answer_is_an_error() -> None:
    fake = replying(
        content=sse(
            {"promptFeedback": {"blockReason": "SAFETY"}},
            {"candidates": [{"finishReason": "SAFETY"}]},
        )
    )
    generator = GeminiGenerator("key", "m", transport=fake.transport)

    with pytest.raises(ProviderUnavailable, match="SAFETY"):
        run(collect(generator.generate("s", QUESTION)))


def test_a_groq_answer_spent_on_hidden_reasoning_is_an_error() -> None:
    fake = replying(
        content=sse(
            {"choices": [{"delta": {"reasoning": "hmm"}}]},
            {"choices": [{"delta": {}, "finish_reason": "length"}]},
            "[DONE]",
        )
    )
    generator = GroqGenerator("key", "m", transport=fake.transport)

    with pytest.raises(ProviderUnavailable, match="length"):
        run(collect(generator.generate("s", QUESTION)))


def test_the_backup_answers_when_the_primary_returns_nothing() -> None:
    empty = replying(content=sse({"choices": [{"delta": {}, "finish_reason": "length"}]}))
    backup = ScriptedGenerator("backup", ["answer"])
    generator = FallbackGenerator(GroqGenerator("key", "m", transport=empty.transport), backup)

    text, usage = run(collect(generator.generate("s", QUESTION)))

    assert (text, usage.fell_back_from) == ("answer", "groq:m")


def test_temperature_is_sent_only_when_set() -> None:
    gemini = replying(content=sse(gemini_text("ok")))
    groq = replying(content=sse({"choices": [{"delta": {"content": "ok"}}]}))

    run(collect(GeminiGenerator("k", "m", transport=gemini.transport).generate("s", QUESTION)))
    run(collect(GroqGenerator("k", "m", transport=groq.transport).generate("s", QUESTION, 9, 0)))

    assert "temperature" not in gemini.body()["generationConfig"]
    assert groq.body()["temperature"] == 0


def test_a_call_that_takes_too_long_is_cut_off(monkeypatch: pytest.MonkeyPatch) -> None:
    async def slow(request: httpx2.Request) -> httpx2.Response:
        await asyncio.sleep(5)
        return httpx2.Response(200, json={})

    monkeypatch.setattr(_http, "DEADLINE_SECONDS", 0.05)
    transport = httpx2.MockTransport(slow)

    with pytest.raises(ProviderUnavailable, match="too long"):
        run(GeminiEmbedder("key", transport=transport).embed(["a"], Purpose.QUERY))
    with pytest.raises(ProviderUnavailable, match="too long"):
        run(collect(GroqGenerator("key", "m", transport=transport).generate("s", QUESTION)))


def test_gemini_embeds_large_inputs_in_batches_of_100() -> None:
    def respond(request: httpx2.Request) -> httpx2.Response:
        count = len(json.loads(request.content)["requests"])
        return httpx2.Response(200, json={"embeddings": [{"values": [1.0]}] * count})

    fake = Recorder(respond)
    embedder = GeminiEmbedder("key", dimensions=1, transport=fake.transport)

    result = run(embedder.embed([f"t{n}" for n in range(250)], Purpose.PASSAGE))

    assert len(result.vectors) == 250
    assert [len(fake.body(n)["requests"]) for n in range(3)] == [100, 100, 50]


def test_gemini_says_when_its_quota_resets() -> None:
    body = {
        "error": {
            "code": 429,
            "message": "quota",
            "details": [
                {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": []},
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "28s"},
            ],
        }
    }
    fake = replying(429, json=body)

    with pytest.raises(RateLimited) as raised:
        run(GeminiEmbedder("key", transport=fake.transport).embed(["a"], Purpose.QUERY))

    assert raised.value.retry_after == 28.0
