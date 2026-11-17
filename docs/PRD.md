# Docent — Product Requirements

| | |
|---|---|
| **Author** | M. Babar Shahzad |
| **Status** | Draft v1 |
| **Last updated** | 2026-11-15 |
| **Related** | [IDEA.md](./IDEA.md) · [ARCHITECTURE.md](./ARCHITECTURE.md) · [FLOWS.md](./FLOWS.md) |

---

## 1. Problem

**People on small teams can't get trustworthy answers from their own documents: keyword search misses anything not phrased exactly right, and general-purpose chatbots answer confidently without showing where the answer came from — so people either can't find the answer or can't tell whether it's true.**

The cost of a wrong answer is higher than the cost of no answer. One confident, unsourced mistake about a leave policy or a product spec and people stop trusting the tool and go back to Ctrl+F or asking a colleague.

**Not solving:** general web knowledge, writing or summarizing documents, workflow automation, or searching external systems (Drive, Notion, Slack).

## 2. Why this matters

- Team knowledge lives in scattered PDFs, DOCX files, and pages that nobody reads end to end; the answer usually exists, it's just hard to locate.
- Keyword search requires knowing the document's exact wording; questions are asked in the user's wording.
- LLM chat tools are fluent but unverifiable — without citations, every answer has to be double-checked, which removes the time saved.
- Retrieval-augmented generation (RAG) is now a common pattern, but most implementations skip the hard parts: grounding checks, declining when unsure, permission-safe retrieval, and measured quality. Those hard parts are what this project is about.

**Evidence status:** this is currently a hypothesis, not a validated need. See §9 for how it will be validated.

## 3. Audience

**Primary — small groups (5–50 people) sharing documents** with knowledge buried in handbooks, policies, and specs (HR, operations, product). They need shared collections, roles, and answers they can verify in one click. Collections are shared person by person; there is no team or workspace entity in v1 ([ADR 0001](./adr/0001-collections-without-teams.md)).

**Secondary — site owners** who want a cited Q&A widget on their own site, answering only from content they publish.

**Out of scope for v1:** enterprises (SSO, org admin, compliance), and mobile-first users (tablet must still work).

## 4. Success criteria

Docent v1 is done when all of the following are true:

**Answer quality** (measured on a fixed eval set, run in CI on every PR)

| Metric | Target |
|---|---|
| Eval set size | ≥ 100 questions, including ≥ 25 unanswerable |
| Retrieval hit rate @5 | ≥ 90% |
| Faithfulness (citation supports its claim) | ≥ 95% |
| Unanswerable questions correctly declined | ≥ 90% |
| Regression on any metric | Blocks merge |

**Experience**

| Metric | Target |
|---|---|
| Time to first token | < 1.5 s (p50) |
| Full answer | < 8 s (p95) |
| New user: sign up → first cited answer | < 3 minutes, no instructions needed |
| Permission leaks (chunk from an inaccessible doc in any prompt) | 0, verified by automated tests |

**Shipped outcome**

- Live, publicly reachable deployment with a demo collection anyone can try.
- Chat widget embedded and working on at least one real website.
- README publishes eval results, load-test results, cost per answer, and the method behind each.

## 5. Constraints

- **$0 budget.** Free tiers only (hosted Postgres with pgvector, free LLM and embedding API tiers, free hosting, GitHub Actions). Model calls go through one provider interface so a paid model can be swapped in later without code changes.
- **One developer, one modest laptop** (2-core CPU, no GPU). No local models or containers; heavy work (models, evals) runs in the cloud.
- **Free-tier rate limits** cap throughput. Targets that depend on throughput are adjusted in §8.
- **Upload limits** (configurable): 20 MB per file, 300 pages per Document, 100 MB of original files per User. Uploads beyond a limit are rejected with a message naming the limit and how to stay within it.

## 6. Solution (directional)

A browser-based chat grounded in uploaded documents. Detailed behavior lives in [IDEA.md](./IDEA.md) and [FLOWS.md](./FLOWS.md); system design in [ARCHITECTURE.md](./ARCHITECTURE.md).

The core loop, in seven pieces:

1. **Upload** files into a collection; each file shows live status (queued → parsing → embedding → indexed / failed).
2. **Index** in the background: structure-aware chunks with file, page, and heading metadata.
3. **Ask** a question scoped to one or more collections.
4. **Retrieve** with hybrid search (vector + keyword, merged), filtered by permissions inside the query.
5. **Answer** streamed with inline citations `[1]`, `[2]`; claims that a check can't tie to a cited passage are removed.
6. **Verify** by clicking a citation, which opens the source at the highlighted passage.
7. **Decline** when retrieval is weak: "I couldn't find that in your docs," plus the closest matches.

**Principles that override features**

- Declining is better than guessing.
- Document text is data, never instructions.
- Permissions are enforced on the server, before retrieval results exist — never filtered afterward.
- Quality is measured, not felt.

## 7. Non-goals (v1)

- Fine-tuning or training models
- Agents, tool use, web browsing
- Third-party connectors (Drive, Notion, Slack, Confluence)
- OCR, images, audio, video
- Mobile apps and voice
- Billing, plans, SSO, org-level admin
- Multi-language tuning (English is supported and measured; other languages are best-effort)
- PDF export of Conversations (Markdown export ships), date filters, rendered-PDF citation highlighting
- Per-Collection eval sets for Owners

## 8. Milestones

No fixed deadline; each milestone has a target duration to keep scope honest. Each one ends with something deployed and demoable. **The first public release (v0.1) ships at the end of M2**, with a public demo collection built from openly licensed documents; later milestones ship as v0.2+, and v1.0 is M5 complete.

| # | Milestone | Scope | Target | Done when |
|---|---|---|---|---|
| M0 | **Foundation** | Repo, CI (lint, typecheck, test), auth (email + Google), database, deploy pipeline | 1 week | A signed-in user sees an empty library on the live URL |
| M1 | **Ingestion** | Upload PDF, DOCX, MD, TXT; background parse/chunk/embed; per-file status; library view; delete purges chunks | 2 weeks | 20 mixed files ingest with correct status; a bad file fails alone |
| M2 | **Cited answers** | Hybrid retrieval, streaming chat, citations with passage preview, citation verification, "not found" path, follow-up rewriting, eval set v1 (50 questions) in CI | 3 weeks | Eval runs in CI and blocks regressions; a reviewer can verify any answer in one click |
| M3 | **Collections & sharing** | Collections, roles (owner/editor/viewer), personal collection, invites, permission tests | 2 weeks | Automated tests prove zero cross-collection leaks |
| M4 | **Public & embed** | Public toggle with expiry, embeddable widget, small static demo site hosting it, REST `POST /ask` with API keys and rate limits | 2 weeks | Widget live on a real site; API returns the same cited answers as the app |
| M5 | **Prove it** | Eval set to 100+, reranker, URL/HTML ingestion, conversation history (rename, delete, search, pin), Markdown export, debug panel, privacy note, load test, README write-up | 2 weeks | All §4 targets met and published |

**Adjusted for free tiers:** "50 simultaneous askers" and "1,000 pages in under 5 minutes" become **measured and reported** in M5 rather than hard targets; the README states the limits and what a paid tier would change.

## 9. Risks and open questions

| Risk / question | Mitigation |
|---|---|
| **The need is unvalidated** | Before M2 ends, show the working prototype to 5 people who work with internal docs; record what they'd ask and whether they trust the answers. Adjust §3 based on results. |
| Free-tier rate limits throttle ingestion and evals | Batch embeddings; cache by chunk hash; keep the CI eval subset small and run the full set nightly. |
| Free-tier provider may use prompts to improve its models | Demo with public documents only; state this in the README. |
| Free database pauses after inactivity | Scheduled keep-alive ping; document cold-start behavior. |
| PDF/DOCX tables and headings extract poorly | Build an extraction test set in M1 from real-world files; compare parsers early. |
| Faithfulness ≥ 95% may be hard with a free model | Citation verification drops unsupported claims; tune the decline threshold against the eval set. |
| Which LLM, embedding, and reranker providers? | Decide in M0 against current free-tier limits; the provider interface keeps the choice reversible. |

---

## Appendix A — Glossary

- **Collection:** a named group of documents with its own members and roles.
- **Chunk:** a section of a document (with file, page, and heading metadata) that retrieval returns.
- **Hybrid search:** vector similarity and keyword (BM25) results merged with reciprocal rank fusion.
- **Faithfulness:** share of citations whose passage actually supports the claim it's attached to.
- **Hit rate @5:** share of eval questions where a correct source appears in the top 5 retrieved chunks.

## Appendix B — Decision log

| Date | Decision | Why |
|---|---|---|
| 2026-11-15 | Primary audience: small teams; site owners secondary | Collections, roles, and sharing serve teams; the widget serves site owners without extra core work |
| 2026-11-15 | $0 budget, free tiers only | Personal project; provider interface keeps paid upgrades a config change |
| 2026-11-15 | Hosted services only, no local models or containers | Development laptop has 2 cores and no GPU |
| 2026-11-15 | Throughput targets measured, not gated | Free-tier rate limits make them unenforceable in v1 |
| 2026-11-15 | Portfolio emphasis: full-stack product, AI engineering in the lead | Evals, grounding, and declining are the differentiators |
| 2026-11-15 | No Team entity; a Document belongs to one Collection | [ADR 0001](./adr/0001-collections-without-teams.md), [ADR 0002](./adr/0002-document-belongs-to-one-collection.md) |
| 2026-11-15 | Re-upload never updates silently; the user chooses Replace; identical content is flagged | Filename matching guesses wrong; the user knows their intent |
| 2026-11-15 | Conflicting Documents are ordered by a user-set Effective Date (default: upload date) | Upload dates are wrong for older policies; extracting dates is unreliable |
| 2026-11-15 | One transferable Owner per Collection; account deletion requires transfer or delete first | No orphaned Collections |
| 2026-11-15 | Visitors have no saved history; their answers still go to the Answer Log | Owners can review quality without anonymous accounts |
| 2026-11-15 | Public v0.1 after M2; demo uses openly licensed documents | A live demo with published evals early is the strongest portfolio signal |
| 2026-11-15 | Python (FastAPI) API, workers, evals; Next.js (TypeScript) web and widget | [ADR 0003](./adr/0003-python-backend-typescript-frontend.md) |
| 2026-11-15 | Citations keep the passage they were based on, even after Replace | [ADR 0004](./adr/0004-citations-keep-replaced-passages.md) |
| 2026-11-15 | Losing access hides cited passage text in past Conversations; answer text stays | Revocation applies from now on; what was read can't be unread |
| 2026-11-15 | Scope can change mid-Conversation; each answer records its Scope | Matches user expectation; keeps the Answer Log accurate |
| 2026-11-15 | Personal Collection is always private; Documents can be Moved between Collections | Sharing happens through regular Collections |
| 2026-11-15 | Anonymous traffic: per-IP limits plus a global daily cap; signed-in users keep reserved quota | Protects the free model quota from bots |
| 2026-11-15 | Conflicting Documents handled in the answer prompt, measured with ≥ 5 conflict questions | Cheap and measurable; upgrade to a dedicated check if scores are poor |
| 2026-11-15 | Sign-in: magic link + Google; no passwords | No password reset flow to build; safer |
| 2026-11-15 | Eval Set: drafted from demo docs, every item human-reviewed; unanswerable and conflict items hand-written | Review makes the measurement trustworthy |
| 2026-11-15 | Backend on Render free tier, kept awake by a scheduled ping | No card required; one always-on service fits the free hours |
| 2026-11-15 | One backend service (API + worker loop), Postgres job queue, no Redis | [ADR 0005](./adr/0005-single-backend-service-postgres-queue.md) |
| 2026-11-16 | API on Vercel's Python runtime (Singapore); background work in short scheduled batches. Supersedes the Render and worker-loop decisions above | Free always-on Python hosts now require a card; [ADR 0008](./adr/0008-api-on-vercel-functions.md) |
| 2026-11-16 | Application tables in a private `app` schema with row level security on; access only through the API | [ADR 0009](./adr/0009-private-app-schema.md) |
| 2026-11-16 | Migrations with Alembic, applied in CI to a fresh database and to production during the API's production build only | Previews never touch production data |
| 2026-11-16 | The User and Personal Collection are created by the API on first authenticated request, not by a database trigger | Portable and testable; safe under concurrent first requests |
| 2026-11-16 | Answers from Groq `openai/gpt-oss-120b`, falling back to Gemini `gemini-3.5-flash-lite`; embeddings from Gemini `gemini-embedding-001` (1024 dimensions); Voyage kept for reranking. Supersedes the Voyage-for-embeddings decision below | Measured: Voyage allows 3 requests/min without a card, Gemini 100 texts/min; [ADR 0010](./adr/0010-model-choice-by-measured-quota.md) |
| 2026-11-17 | PDFs read with PDFium (pypdfium2), Word with python-docx; headings rebuilt from layout, running headers dropped, page kept per passage | Only candidate to read two-column pages and tables correctly, ~10x faster; [ADR 0011](./adr/0011-pdf-extraction-with-pdfium.md) |
| 2026-11-15 | Supabase for database, auth, and file storage | [ADR 0006](./adr/0006-supabase-for-database-auth-storage.md) |
| 2026-11-15 | Upload limits: 20 MB/file, 300 pages/Document, 100 MB/User | Fits free storage; configurable |
| 2026-11-15 | Voyage for embeddings and reranking; answer LLM chosen in M0 between Gemini and Groq by measured quota, the other as fallback | Free limits are unpublished or inconsistent; measure, don't assume |
| 2026-11-15 | Citations verified by quote matching after streaming; removals shown | [ADR 0007](./adr/0007-citations-verified-by-quote-matching.md) |
| 2026-11-15 | Faithfulness measured by a model judge (different model from the generator), 20% human spot-check per release, agreement rate published | The judge itself must be shown trustworthy |
| 2026-11-15 | Citation opens extracted text at the highlighted passage, with page number; rendered-PDF highlighting is post-v1 | Mapping text back to PDF coordinates is high effort, low necessity |
| 2026-11-15 | Decline in two layers: retrieval-score threshold before the LLM, plus model-level decline; threshold tuned on the Eval Set | Saves quota; balances decline rate against false declines |
| 2026-11-15 | Monorepo: apps/web, apps/api, packages/client, evals, docs | One place for reviewers and CI |
| 2026-11-15 | Demo Collection: 30–50 docs from the GitLab Handbook (CC BY-SA) and GOV.UK guidance (Open Government Licence), licenses verified per source, attributed in app and README | Covers HTML, Markdown, PDF, DOCX; real old/new versions give conflict cases |
| 2026-11-15 | API Keys belong to one Collection, ask-only, revocable, rate-limited per key | A leaked key is contained to one Collection |
| 2026-11-15 | One Eval Set on the Demo Collection; only the maintainer promotes items, only from the Demo Collection | Private data never enters the repo or CI |
| 2026-11-15 | CI evals: temperature 0, pinned models; block if a metric drops > 2 points vs main or below target; 30-question subset per PR, full set nightly and pre-release | Tolerates model nondeterminism; fits free quota |
| 2026-11-15 | Debug panel: Owners and Editors on their Collections, everyone on the Demo Collection | Showing how grounding works is a demo strength |
| 2026-11-15 | Visitor IPs stored only as salted hashes; Answer Log retained 90 days (Eval Set items kept); account deletion anonymizes log entries; plain-language privacy note | Minimal personal data; metrics stay intact |
| 2026-11-15 | English supported and measured; other languages best-effort | Multi-language tuning is a non-goal |
| 2026-11-15 | PDF export and date filters moved post-v1 | M5 scope; Markdown export covers the need |
| 2026-11-15 | Widget's "real website": a small static demo site built in M4 on a free host; switch to the maintainer's portfolio site if one exists by then | No portfolio site confirmed; decision is cheap to revisit at M4 |
