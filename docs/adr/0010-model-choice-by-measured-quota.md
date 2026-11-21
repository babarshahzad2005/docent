# Answers from Groq's gpt-oss-120b with Gemini Flash-Lite as fallback; Gemini for embeddings

The answer model is `openai/gpt-oss-120b` on Groq, falling back automatically to `gemini-3.5-flash-lite` when Groq errors, is rate-limited, or returns no answer text before it starts answering. Embeddings come from Gemini's `gemini-embedding-001` at 1024 dimensions, not from Voyage as first planned. Voyage stays as the reranker. Every call goes through the provider interface in `apps/api/src/docent_api/providers`, and the answer models are settings (`ANSWER_MODEL`, `FALLBACK_ANSWER_MODEL`), so a paid model can be swapped in without code changes.

## Measurements

Taken on 2026-11-16 with `uv run docent-measure-models --probe-rpm`: an answer of at most 300 tokens to a question over eight passages (about 850–890 prompt tokens), median of 3 runs. Throughput is output tokens over the whole call, hidden reasoning included.

| Answer model | First token | Whole answer | Throughput | Free-tier limits |
| --- | --- | --- | --- | --- |
| groq `openai/gpt-oss-120b` (reasoning effort low) | 1,227 ms (653 ms in an earlier run) | 1,249 ms | 66 tok/s | 1,000 requests/day, 8,000 tokens/min (response headers) |
| groq `openai/gpt-oss-20b` (reasoning effort low) | 521 ms | 576 ms | 116 tok/s | same |
| groq `qwen/qwen3.8-27b` | 258 ms | 367 ms | 136 tok/s | same |
| gemini `gemini-3.5-flash-lite` (thinking minimal) | 1,203 ms | 1,348 ms | 43 tok/s | 15 requests/min (quota `GenerateRequestsPerMinutePerProjectPerModel-FreeTier=15`) |
| gemini `gemini-3.5-flash`, `gemini-flash-latest`, `gemini-3.8-flash` | — | — | — | HTTP 503 "high demand" or a timeout on every attempt; unusable on the free tier today |
| gemini `gemini-2.5-flash` | — | — | — | HTTP 404, no longer offered to new users |

| Embeddings and reranking | Latency | Free-tier limits |
| --- | --- | --- |
| gemini `gemini-embedding-001` | 3.2–18 s for 32 passages, 0.8–1.0 s for a query | 100 texts/min, each text in a batch counted separately (quota `EmbedContentRequestsPerMinutePerUserPerProjectPerModel-FreeTier=100`) |
| voyage `voyage-4` | 2.7 s for 32 passages, 0.8–1.3 s for a query | 3 requests/min and 10K tokens/min without a payment method on file (`x-api-warning` header) |
| voyage `rerank-2.5-lite` | 0.9–1.7 s for 20 passages | same 3 requests/min; `rerank-2.5` refused even the first request |

Daily limits for Gemini were not measured, because finding them means using them up.

**Where this was measured.** The script ran on the developer's laptop in Pakistan, not from the API's Vercel region in Singapore (ADR 0008), so the issue's "from this deployment" is only half met. The quotas don't depend on where requests come from; latencies do. The choice below doesn't hinge on a few hundred milliseconds (every usable candidate stayed under the 1.5 s time-to-first-token target), and the latencies are re-measured from the deployment when answers go live in M2, where the Answer Log records them on every real answer.

## Why

- **gpt-oss-120b answers first.** It is the strongest model Groq offers for free. Its first token arrived in 0.65–1.2 s across runs, inside the 1.5 s target (PRD › Success metrics). Qwen and gpt-oss-20b are faster but smaller; if quality allows, they are the first thing to try for speed. The binding limit is 8,000 tokens a minute, about four answers a minute at the measured prompt size (more once real prompts carry more passages, fewer then too). That is enough for a portfolio demo, and the fallback absorbs bursts.
- **Gemini Flash-Lite is the fallback.** It runs on a different company's infrastructure, so one provider's outage or quota doesn't take answers down, and its 15 requests a minute cover what Groq refuses. Gemini's larger Flash models would be better, but they refused every free-tier request.
- **Embeddings move to Gemini.** Without a card, Voyage allows 3 requests a minute and 10K tokens a minute. Every question needs one query embedding, so Docent could answer at most three questions a minute in total and ingest almost nothing meanwhile. Gemini allows 100 texts a minute: roughly 100 passages of ingestion, or 100 questions, shared. Embedding providers can't fall back to each other, because vectors from different models aren't comparable; switching later means re-embedding every passage (ARCHITECTURE › Embedding model per chunk).
- **Voyage stays for reranking.** Reranking arrives in M5 and runs once per question. 3 requests a minute is tight; this is revisited then, measured again.

## Fallback rule

The fallback is used only if the primary fails before it has written any text. Once text has reached the reader, switching models would splice two different answers together, so a failure after that point is reported as an error. An answer with no text at all (blocked by the provider, or its budget spent on hidden reasoning) counts as a failure. The Answer Log records which model answered and, when it happened, which model it fell back from.

## Consequences

- Answers depend on two free tiers. When both are exhausted, asking fails with a clear message until the quota resets.
- Ingestion is paced at about 100 passages a minute and shares that budget with questions; a 300-page Document takes minutes, not seconds, to index. M1's ingestion batches respect the limit and the `retry_after` the provider returns.
- Gemini reports no token counts for embeddings, so the Answer Log records model and latency for them but not tokens.
- Gemini's daily limits are unknown; the Answer Log will show real usage.
- Model versions change under us (`gemini-2.5-flash` disappeared for new users). The measurement script is re-run before each milestone that depends on answer quality, and this ADR is updated with the new numbers.

## From the deployment (#26, November 2026)

The measurements above were taken from a laptop in Pakistan. The API runs in Vercel's Singapore region. The Answer Log records each real answer's model time to first token (from the call to the first token) and its whole time.

| Answer model | Real answers | First token, p50 | Whole answer, p50 / p95 |
| --- | --- | --- | --- |
| groq `openai/gpt-oss-120b` | 4 | 668 ms | 1,602 ms / 2,012 ms |
| gemini `gemini-3.5-flash-lite` (as the fallback) | 7 | 5,079 ms | 5,597 ms / 7,276 ms |

The samples are few, because v0.1 has little traffic yet. A p95 over 4 answers says little, so they are re-checked once there is more traffic. Qwen's timings below are from the laptop, and its deployment numbers will come from the Answer Log once it has answered there. gpt-oss-120b meets the 1.5 s target, and the 8 s p95 target too. Gemini as the fallback misses it by far. Real prompts with 8 passages are much larger than the earlier test prompt: timed on a full-size prompt, Gemini took 7–16 s to its first token.

**The fallback is revisited.** It becomes a chain, tried in order (`FALLBACK_ANSWER_MODEL`, comma-separated). Candidates were timed on a full-size prompt (3 runs each, from the laptop) and scored on the Eval Set's first 10 answerable questions:

| Candidate | First token | Answerable answered | Faithfulness |
| --- | --- | --- | --- |
| groq `openai/gpt-oss-20b` | 0.6–0.7 s | 1 of 10 | 3 of 3 sentences |
| **groq `qwen/qwen3.8-27b`** | **0.33–0.76 s** | **10 of 10** | **18 of 18 sentences** |
| gemini `gemini-3.5-flash-lite` | 7–16 s | (fallback until now) | |

gpt-oss-20b is fast, but it rarely follows the citation format, so its answers are hidden or declined. Qwen is fast, and on this sample it answered as well as gpt-oss-120b. The chain is therefore:

1. `groq:openai/gpt-oss-120b`
2. `groq:qwen/qwen3.8-27b`
3. `gemini:gemini-3.5-flash-lite`

Groq's rate limits are per model, so Qwen's own allowance absorbs the most common failure, gpt-oss-120b's 8,000 tokens a minute, in under a second. Gemini stays last, on another provider, for when Groq as a whole is down. Qwen answering well enough to be the primary is worth testing on the full Eval Set before any switch (M5). Qwen's reasoning is kept out of its answers (`reasoning_format: hidden`), as gpt-oss's is. When a fallback answers, the Answer Log records the model that answered and that the answer model failed (`fell_back_from`); it doesn't record which middle step was tried. This section supersedes the earlier bullet that names Gemini Flash-Lite as the fallback.
