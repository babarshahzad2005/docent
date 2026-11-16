"""Measures the model providers from this machine: speed, and the free-tier limits they enforce.

    uv run docent-measure-models              # speed of every candidate, limits from headers
    uv run docent-measure-models --probe-rpm  # also burst Gemini until it rate-limits

Uses real API keys from .env and spends a little free quota. The numbers feed ADR 0010.
"""

import argparse
import asyncio
import statistics
import time
from collections.abc import Sequence
from typing import Any

import httpx2

from docent_api.providers.base import (
    Embedder,
    Finished,
    Generator,
    Message,
    ProviderError,
    Purpose,
    TextDelta,
)
from docent_api.providers.gemini import GeminiEmbedder, GeminiGenerator
from docent_api.providers.groq import GroqGenerator
from docent_api.providers.voyage import VoyageEmbedder, VoyageReranker
from docent_api.settings import get_settings

_PASSAGE = (
    "Section {n}. Employees accrue paid leave at a rate of 1.5 days per full month of service. "
    "Unused leave of up to 10 days may be carried into the next calendar year; any balance above "
    "that is forfeited on 31 March unless a manager approves an exception in writing. Leave "
    "requests longer than five consecutive working days must be submitted at least two weeks in "
    "advance through the HR portal, and are approved in the order they are received. "
)
_SYSTEM = (
    "Answer only from the numbered passages. Cite each claim like [1]. If the passages do not "
    "contain the answer, say so.\n\n"
    + "\n".join(f"[{n}] {_PASSAGE.format(n=n)}" for n in range(1, 9))
)
_QUESTION = [Message("user", "How much leave can I carry over, and what happens to the rest?")]
_RUNS = 3


def _generators() -> list[Generator]:
    s = get_settings()
    return [
        GeminiGenerator(s.gemini_api_key, "gemini-3.5-flash", {"thinkingLevel": "minimal"}),
        GeminiGenerator(s.gemini_api_key, "gemini-3.5-flash-lite", {"thinkingLevel": "minimal"}),
        GroqGenerator(s.groq_api_key, "openai/gpt-oss-120b", reasoning_effort="low"),
        GroqGenerator(s.groq_api_key, "openai/gpt-oss-20b", reasoning_effort="low"),
        GroqGenerator(s.groq_api_key, "qwen/qwen3.8-27b"),
    ]


async def _measure_generator(generator: Generator) -> str:
    first: list[float] = []
    speed: list[float] = []
    version = "?"
    for _ in range(_RUNS):
        try:
            text = ""
            async for event in generator.generate(_SYSTEM, _QUESTION, max_output_tokens=300):
                if isinstance(event, TextDelta):
                    text += event.text
                elif isinstance(event, Finished):
                    usage = event.usage
        except ProviderError as error:
            return f"| {generator.name} | failed: {str(error)[:120]} | | | |"
        version = usage.model_version
        if usage.first_token_ms is not None:
            first.append(usage.first_token_ms)
            streaming_s = (usage.latency_ms - usage.first_token_ms) / 1000
            if usage.output_tokens and streaming_s > 0:
                speed.append(usage.output_tokens / streaming_s)
        await asyncio.sleep(2)
    return (
        f"| {generator.name} | {version} | {_median(first, 'ms')} | {_median(speed, 'tok/s')} "
        f"| {text[:60].strip()!r}... |"
    )


async def _measure_embedder(label: str, embedder: Embedder) -> str:
    texts = [_PASSAGE.format(n=n) for n in range(32)]
    try:
        result = await embedder.embed(texts, Purpose.DOCUMENT)
        query = await embedder.embed(["how much leave carries over"], Purpose.QUERY)
    except ProviderError as error:
        return f"| {label} | failed: {str(error)[:120]} | |"
    return (
        f"| {label} | {result.usage.latency_ms:.0f} ms for 32 passages "
        f"| {query.usage.latency_ms:.0f} ms for 1 query |"
    )


async def _measure_reranker() -> str:
    reranker = VoyageReranker(get_settings().voyage_api_key)
    passages = [_PASSAGE.format(n=n) for n in range(20)]
    try:
        result = await reranker.rerank("how much leave carries over", passages, top_k=5)
    except ProviderError as error:
        return f"| voyage:{reranker.model} | failed: {str(error)[:120]} |"
    return f"| voyage:{reranker.model} | {result.usage.latency_ms:.0f} ms for 20 passages |"


async def _limit_headers() -> list[str]:
    """Limits the providers announce in response headers."""
    s = get_settings()
    lines = []
    async with httpx2.AsyncClient(timeout=30) as client:
        groq = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {s.groq_api_key}"},
            json={
                "model": "openai/gpt-oss-120b",
                "messages": [{"role": "user", "content": "hi"}],
                "max_completion_tokens": 8,
            },
        )
        found = {k: v for k, v in groq.headers.items() if k.startswith("x-ratelimit-limit")}
        lines.append(f"- groq (openai/gpt-oss-120b): {found or groq.status_code}")
        voyage = await client.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {s.voyage_api_key}"},
            json={"input": ["hi"], "model": "voyage-4"},
        )
        warning = voyage.headers.get("x-api-warning", "no warning header")
        lines.append(f"- voyage: {warning[:160]}")
    return lines


async def _probe_gemini_rpm(label: str, url: str, body: dict[str, Any], limit: int) -> str:
    """Sends tiny requests back to back until Gemini refuses one, and reports its quota."""
    key = get_settings().gemini_api_key
    start = time.perf_counter()
    async with httpx2.AsyncClient(timeout=60) as client:
        for sent in range(1, limit + 1):
            try:
                response = await client.post(url, headers={"x-goog-api-key": key}, json=body)
            except httpx2.TransportError as error:
                return f"- gemini {label}: request {sent} failed: {error!r}"
            if response.status_code != 200:
                return (
                    f"- gemini {label}: refused request {sent} (HTTP {response.status_code}) "
                    f"after {time.perf_counter() - start:.0f} s; {_quota_details(response.json())}"
                )
    return f"- gemini {label}: {limit} requests accepted in {time.perf_counter() - start:.0f} s"


async def _probe_gemini() -> list[str]:
    base = "https://generativelanguage.googleapis.com/v1beta/models"
    tiny = {"contents": [{"parts": [{"text": "hi"}]}], "generationConfig": {"maxOutputTokens": 1}}
    embed = {"content": {"parts": [{"text": "hi"}]}, "outputDimensionality": 1024}
    return [
        await _probe_gemini_rpm(model, f"{base}/{model}:generateContent", tiny, limit=40)
        for model in ("gemini-3.5-flash", "gemini-3.5-flash-lite")
    ] + [
        await _probe_gemini_rpm(
            "gemini-embedding-001", f"{base}/gemini-embedding-001:embedContent", embed, limit=120
        )
    ]


def _quota_details(body: dict[str, Any]) -> str:
    details = body.get("error", {}).get("details", [])
    violations = [
        f"{v.get('quotaId')}={v.get('quotaValue')}"
        for d in details
        for v in d.get("violations", [])
        if "quotaId" in v
    ]
    return ", ".join(violations) or str(body.get("error", {}).get("message", ""))[:200]


def _median(values: Sequence[float], unit: str) -> str:
    return f"{statistics.median(values):.0f} {unit}" if values else "n/a"


async def _main(probe_rpm: bool) -> None:
    s = get_settings()
    print(
        f"## Answer models (median of {_RUNS} runs, ~1.6K-token prompt, up to 300 output tokens)\n"
    )
    print("| Model | Version | Time to first token | Throughput | Sample |")
    print("| --- | --- | --- | --- | --- |")
    for generator in _generators():
        print(await _measure_generator(generator), flush=True)

    # Voyage allows 3 requests a minute without a payment method, so its calls are spaced out.
    print("\n## Embeddings\n\n| Model | Documents | Query |\n| --- | --- | --- |")
    print(await _measure_embedder("gemini:gemini-embedding-001", GeminiEmbedder(s.gemini_api_key)))
    print(await _measure_embedder("voyage:voyage-4", VoyageEmbedder(s.voyage_api_key)), flush=True)
    await asyncio.sleep(61)
    print("\n## Reranking\n\n| Model | Latency |\n| --- | --- |")
    print(await _measure_reranker(), flush=True)
    await asyncio.sleep(61)

    print("\n## Limits announced by the providers\n")
    for line in await _limit_headers():
        print(line)
    if probe_rpm:
        for line in await _probe_gemini():
            print(line, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--probe-rpm", action="store_true", help="burst Gemini to find its limit")
    asyncio.run(_main(parser.parse_args().probe_rpm))


if __name__ == "__main__":
    main()
