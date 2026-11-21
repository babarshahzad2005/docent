# Docent

Ask questions of your own documents and get answers that cite the exact passages they came from — or a clear "I couldn't find that" instead of a guess.

**Live:** https://docent-tan.vercel.app

> **Status:** in development. First public release (v0.1) is planned at the end of milestone M2. See the [roadmap](#roadmap).

## Why

Keyword search misses anything not phrased exactly right, and general-purpose chatbots answer confidently without showing their sources. Docent only answers from documents you upload, verifies every citation against the source text, and declines when the answer isn't there.

## Features (planned for v1)

- Upload PDF, DOCX, Markdown, TXT, and web pages; background indexing with live status
- Hybrid retrieval (vector + keyword) with reranking
- Streaming answers with inline citations that open the exact passage
- Citation verification: claims that can't be tied to a source are removed
- Collections with owner / editor / viewer roles, enforced inside retrieval
- Public collections, an embeddable chat widget, and a REST API
- Answer quality measured on every pull request against a published eval set

## Architecture

- **Web:** Next.js (TypeScript)
- **API and workers:** FastAPI (Python)
- **Data:** Postgres with pgvector and full-text search, auth, and file storage on Supabase

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and the [decision records](docs/adr/).

## Roadmap

| Milestone | Scope |
|---|---|
| M0 | Foundation: repo, CI, auth, deploy |
| M1 | Ingestion |
| M2 | Cited answers and eval suite → **v0.1** |
| M3 | Collections and sharing |
| M4 | Public collections, widget, API |
| M5 | Full eval set, history, load test → **v1.0** |

Full requirements: [docs/PRD.md](docs/PRD.md). Terminology: [GLOSSARY.md](GLOSSARY.md).

## Deployment

| Part | Host | Config |
|---|---|---|
| Web app | Vercel (Hobby), root directory `apps/web` | Preview deployment for every pull request |
| API | Vercel Python runtime, root directory `apps/api` ([ADR 0008](docs/adr/0008-api-on-vercel-functions.md)) | Preview deployment for every pull request |

Both run in Vercel's Singapore region, next to the database. A scheduled workflow ([`keep-alive.yml`](.github/workflows/keep-alive.yml)) pings the API every 10 minutes, which also keeps the free database from pausing once it's connected. Dependencies are kept current by Dependabot.

## Evaluation

Answer quality is measured on the **Eval Set**: 50 maintainer-reviewed questions about the Demo Collection. 33 are answerable, each with its expected passages; 3 test Documents that disagree; 14 are unanswerable. The harness runs each question through Docent's own answer path, read-only, against the live Demo Collection. CI runs a subset on every pull request that changes the answer path, and blocks regressions. The full set runs nightly. Details are in [`evals/README.md`](evals/README.md).

| Metric | Result | Target | How it's measured |
| --- | --- | --- | --- |
| Retrieval hit@5 | **91.7%** (33 of 36) | ≥ 90% | An expected passage among the top 5 retrieved |
| Faithfulness | **97.2%** (35 of 36 sentences) | ≥ 95% | Answer sentences a judge model (Gemini, never the answer model) finds supported by the passages they cite. Spot-checked by hand on 20% of items: 13 of 13 agreed ([judge-spot-check.md](evals/judge-spot-check.md)) |
| Unanswerable questions declined | **100%** (14 of 14) | ≥ 90% | Unanswerable questions declined: by a similarity threshold before the model (chosen on the set), or by the model |
| Answerable and conflict questions answered | **88.9%** (32 of 36) | | Answered, not declined or hidden for failing citation checks |
| Documents that disagree noticed | 1 of 3 | | A "Your documents disagree" notice naming both versions (#67 improves this) |

hit@5 comes from a CI run on 2026-11-20, with the per-Document cap. The answer metrics come from that night's full run, made before the cap. Every Citation is also checked live against its passage by quote matching (ADR 0007), and a claim that can't be tied to its passage is removed before the reader sees the final answer.

**Speed**, measured from the deployment in Singapore (ADR 0010; from the 4 answers so far):

- Time to first token, p50: 668 ms on gpt-oss-120b. The target is under 1.5 s.
- Whole answer: 1.6 s p50 and 2.0 s p95. The target is p95 under 8 s.
- If gpt-oss-120b fails, Qwen 3.8 27B on Groq answers, at about 0.3–0.8 s to first token (timed from a laptop), then Gemini Flash-Lite.

**Cost per answer: $0.** Every model runs on a free tier (Groq for answers, Google Gemini for embeddings), and the whole stack is on free hosting tiers. The 3 real answers logged with token counts (the Answer Log, before quotes were added) averaged about 2,300 prompt tokens and 90 answer tokens. With the quotes that verification needs, and 8 passages, the Eval Set's answers come to about 4,500 tokens each. Groq's free tier allows about 200,000 tokens a day for the answer model, which bounds both traffic and the nightly eval.

## Getting started

**Requirements:** Node.js 22 or newer, [pnpm](https://pnpm.io), [uv](https://docs.astral.sh/uv/), and Python 3.13 (uv can install it for you).

```bash
pnpm install                       # web app and shared packages
uv --directory apps/api sync       # API and its dev tools
cp .env.example .env               # then fill it in (see the file for where each value comes from)
uv --directory apps/api run docent-migrate   # create or update the database tables
uv --directory apps/api run docent-setup-storage   # create the private bucket for uploaded files
pnpm dev                           # API on :8000, web app on :3000
```

The web app reads `apps/web/.env.local` (its variables are listed at the bottom of [.env.example](.env.example)). Open http://localhost:3000 and sign in with Google or an email link.

### Database

Tables live in a private `app` schema that Supabase's auto-generated Data API can't reach ([ADR 0009](docs/adr/0009-private-app-schema.md)). Migrations are versioned in `apps/api/src/docent_api/migrations` and applied with `docent-migrate`: CI applies them to a fresh database on every pull request, and production deployments apply them during the API's build. Preview deployments never touch the production database.

Ingestion runs in short batches: one starts right after each upload, and a pg_cron job in the database starts another every minute while Documents are waiting, so processing continues with the browser closed. `docent-setup-scheduler --api-url <deployed API>` creates the job and its token (kept in Supabase Vault; the API stores only a hash); run it once per Supabase project, and again to rotate the token. Without the scheduler (local development), a Document that pauses waits until the next upload starts a batch.

### Demo Collection

Every User can ask the **Demo Collection**, read-only: 32 openly licensed workplace guides from [GOV.UK](https://www.gov.uk/) (Open Government Licence v3.0) and the [GitLab Handbook](https://handbook.gitlab.com/) (CC BY-SA 4.0), as Markdown, PDF, and Word. Each is credited with its source and licence in the app, and listed in [`evals/demo/sources.json`](evals/demo/sources.json); [`evals/demo/LICENSE.md`](evals/demo/LICENSE.md) explains why these files are not under Docent's MIT licence. Questions asked on its page are answered from it alone. Two of them disagree on purpose: the 2019 holiday calculation guidance and the January 2024 reforms. `uv --directory apps/api run docent-demo fetch` downloads the sources again; `docent-demo seed` loads them into a database's Demo Collection.

Contains public sector information licensed under the Open Government Licence v3.0. GitLab Handbook content © GitLab B.V., licensed under CC BY-SA 4.0; converted to Markdown, with images, links, and diagrams removed.

### File storage

Uploaded files go straight from the browser to a private Supabase Storage bucket, `documents`, using a one-time upload link the API issues after checking the User may add to that Collection. Only the API (with the secret key) can read or delete them. `docent-setup-storage` creates the bucket, or checks its settings (private, 20 MB per file); run it once per Supabase project.

### Models

Every model call goes through one provider interface in `apps/api/src/docent_api/providers`. Answers come from Groq (`openai/gpt-oss-120b`), falling back to Gemini (`gemini-3.5-flash-lite`) if Groq fails, is rate-limited, or returns no text; embeddings come from Gemini and reranking from Voyage. The choice was made from measured free-tier limits and speeds, recorded in [ADR 0010](docs/adr/0010-model-choice-by-measured-quota.md). Run `uv --directory apps/api run docent-measure-models` to measure again.

### Repository layout

| Path | What it is |
|---|---|
| `apps/web` | Next.js web app |
| `apps/api` | FastAPI service: API, database migrations, and background work |
| `packages/client` | TypeScript client generated from the API's OpenAPI schema |
| `evals` | Eval Set and quality harness |
| `docs` | Requirements, architecture, and decision records |

### Common tasks

| Command | Does |
|---|---|
| `pnpm lint` / `pnpm typecheck` / `pnpm test` | Checks for the web app and client |
| `uv --directory apps/api run pytest` | API tests (CI also runs `ruff format --check .`, `ruff check .`, and `mypy`) |
| `uv --directory apps/api run docent-measure-models` | Measure each model provider's speed and free-tier limits (uses real keys and a little quota) |
| `pnpm gen:client` | Regenerate the API client after changing an API route or model |

## License

[MIT](LICENSE)
