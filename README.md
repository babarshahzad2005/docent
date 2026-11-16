# Docent

Ask questions of your own documents and get answers that cite the exact passages they came from — or a clear "I couldn't find that" instead of a guess.

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

## Evaluation

Results, methodology, and cost per answer will be published here once the eval suite runs in CI (M2).

## Getting started

**Requirements:** Node.js 22 or newer, [pnpm](https://pnpm.io), [uv](https://docs.astral.sh/uv/), and Python 3.13 (uv can install it for you).

```bash
pnpm install                     # web app and shared packages
uv --directory apps/api sync     # API and its dev tools
pnpm dev                         # API on :8000, web app on :3000
```

Open http://localhost:3000. The home page shows whether the web app can reach the API.

Configuration variables are listed in [.env.example](.env.example).

### Repository layout

| Path | What it is |
|---|---|
| `apps/web` | Next.js web app |
| `apps/api` | FastAPI service (API and background worker) |
| `packages/client` | TypeScript client generated from the API's OpenAPI schema |
| `evals` | Eval Set and quality harness |
| `docs` | Requirements, architecture, and decision records |

### Common tasks

| Command | Does |
|---|---|
| `pnpm lint` / `pnpm typecheck` / `pnpm test` | Checks for the web app and client |
| `uv --directory apps/api run pytest` | API tests (also `ruff check .` and `mypy`) |
| `pnpm gen:client` | Regenerate the API client after changing an API route or model |

## License

[MIT](LICENSE)
