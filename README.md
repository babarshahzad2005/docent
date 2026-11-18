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

Results, methodology, and cost per answer will be published here once the eval suite runs in CI (M2).

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

Every User can ask the **Demo Collection**: 33 openly licensed workplace guides from [GOV.UK](https://www.gov.uk/) (Open Government Licence v3.0) and the [GitLab Handbook](https://handbook.gitlab.com/) (CC BY-SA 4.0), as Markdown, PDF, and Word. Each is credited with its source and licence in the app, and listed in [`evals/demo/sources.json`](evals/demo/sources.json). Two of them disagree on purpose: the 2019 holiday calculation guidance and the January 2024 reforms. `uv --directory apps/api run docent-demo fetch` downloads the sources again; `docent-demo seed` loads them into a database's Demo Collection.

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
