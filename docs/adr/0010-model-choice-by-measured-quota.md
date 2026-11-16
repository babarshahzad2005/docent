# Answers from Groq's gpt-oss-120b with Gemini Flash-Lite as fallback; Gemini for embeddings

The answer model is `openai/gpt-oss-120b` on Groq, falling back automatically to `gemini-3.5-flash-lite` when Groq errors or is rate-limited before it starts answering. Embeddings come from Gemini's `gemini-embedding-001` at 1024 dimensions, not from Voyage as first planned. Voyage stays as the reranker. Every call goes through the provider interface in `apps/api/src/docent_api/providers`, and the answer models are settings (`ANSWER_MODEL`, `FALLBACK_ANSWER_MODEL`), so a paid model can be swapped in without code changes.

## Measurements

Taken on 2026-11-16 with `uv run docent-measure-models --probe-rpm`, from a home connection in Pakistan; the API itself runs in Singapore (ADR 0008), so production latencies should be similar or lower. The prompt was about 1.6K tokens, the answer at most 300 tokens, median of 3 runs.

| Answer model | Time to first token | Throughput | Free-tier limits |
| --- | --- | --- | --- |
| groq `openai/gpt-oss-120b` (reasoning effort low) | 653 ms | 927 tok/s | 1,000 requests/day, 8,000 tokens/min (response headers) |
| groq `openai/gpt-oss-20b` (reasoning effort low) | 590 ms | 1,209 tok/s | same |
| groq `qwen/qwen3.8-27b` | 403 ms | 501 tok/s | same |
| gemini `gemini-3.5-flash-lite` (thinking minimal) | 1,429 ms | 373 tok/s | 15 requests/min (refused the 16th; quota `GenerateRequestsPerMinutePerProjectPerModel-FreeTier=15`) |
| gemini `gemini-3.5-flash`, `gemini-flash-latest`, `gemini-3.8-flash` | — | — | HTTP 503 "high demand" on every attempt; unusable on the free tier today |
| gemini `gemini-2.5-flash` | — | — | HTTP 404, no longer offered to new users |

| Embeddings and reranking | Latency | Free-tier limits |
| --- | --- | --- |
| gemini `gemini-embedding-001` | 3.2 s for 32 passages, 0.96 s for a query | 120 requests in 84 s accepted without a refusal |
| voyage `voyage-4` | 2.7 s for 32 passages, 0.78 s for a query | 3 requests/min and 10K tokens/min without a payment method on file (`x-api-warning` header) |
| voyage `rerank-2.5-lite` | 1.7 s for 20 passages | same 3 requests/min; `rerank-2.5` refused even the first request |

Daily limits for Gemini were not measured, because finding them means using them up.

## Why

- **gpt-oss-120b answers first.** It is the strongest of Groq's models and starts answering in about 0.65 s, well inside the 1.5 s time-to-first-token target (PRD › Success metrics). Qwen is faster to the first token but is a smaller model. The binding limit is 8,000 tokens a minute, about three or four answers a minute at Docent's prompt size. That is enough for a portfolio demo, and the fallback absorbs bursts.
- **Gemini Flash-Lite is the fallback.** It is a different company's infrastructure, so one provider's outage or quota doesn't take answers down, and its 15 requests a minute cover what Groq refuses. Its first token arrives in about 1.4 s, slower but still within target. Gemini's larger Flash models would be better, but they refused every free-tier request.
- **Embeddings move to Gemini.** Without a card, Voyage allows 3 requests a minute, and every question needs a query embedding, so Docent could answer at most three questions a minute in total and not ingest anything at the same time. Gemini embeddings accepted more than 85 requests a minute. Embedding providers can't fall back to each other, because vectors from different models aren't comparable; switching later means re-embedding every passage (ARCHITECTURE › Embedding model per chunk).
- **Voyage stays for reranking.** Reranking arrives in M5 and runs once per question on at most a few dozen passages. 3 requests a minute is tight; this is revisited then, measured again.

## Fallback rule

The fallback is used only if the primary fails before it has written any text. Once text has reached the reader, switching models would splice two different answers together, so a failure after that point is reported as an error. The Answer Log records which model answered and, when it happened, which model it fell back from.

## Consequences

- Answers depend on two free tiers. When both are exhausted, asking fails with a clear message until the quota resets.
- Gemini's daily limits are unknown; the Answer Log's model and token counts will show real usage once people ask questions.
- Model versions change under us (`gemini-2.5-flash` disappeared for new users). The measurement script is re-run before each milestone that depends on answer quality, and this ADR is updated with the new numbers.
