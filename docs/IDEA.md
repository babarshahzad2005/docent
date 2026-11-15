# What we’re building

The idea behind Docent, a chatbot that answers questions from your own documents, with citations.

- A ChatGPT-style chat in the browser, grounded in files you upload
- Teams sign in, organize docs into collections, and share them
- Every answer cites the exact source passages, or says it doesn’t know

## Core feature 1: Document ingestion

- Upload PDF, DOCX, Markdown, TXT, HTML; paste a URL for web pages
- Drag-and-drop bulk upload with per-file status: queued, parsing, indexed, failed
- Extraction keeps structure: headings, tables, lists, page numbers
- Structure-aware chunking with overlap; metadata per chunk: file, page, heading path
- Re-uploading a changed file updates it; duplicates caught by content hash
- Ingestion runs in the background; the UI never blocks

## Core feature 2: Retrieval

- Hybrid search: vector + keyword (BM25), merged with reciprocal rank fusion
- Reranker over top candidates before the LLM sees them
- Follow-ups rewritten into standalone queries (“what about the second one?”)
- Filters by collection, file, date
- Debug panel: retrieved chunks, scores, final prompt

## Core feature 3: Chat with citations

- Streaming answers; stop, regenerate, copy
- Inline citations `[1]`, `[2]`; click opens the source scrolled to the exact passage, highlighted
- Multi-turn chat keeps context
- Weak retrieval → “I couldn’t find that in your docs” plus closest matches; no guessing from model memory
- Thumbs up/down with reason; feedback feeds the eval set

## Core feature 4: Collections and sharing

- Sign up / sign in with email or Google
- Collections group docs (“HR policies”, “Product specs”); a chat scopes to one or several
- Roles per collection: owner, editor (upload/delete), viewer (ask only)
- Private personal collection for every user
- Public toggle per collection with optional expiry: anyone with the link can ask, not edit

## Core feature 5: Library and conversations

- Library of docs with status, size, chunk count, last indexed; preview, re-index, delete
- Search across doc titles and the text inside docs
- Conversation history: rename, delete, search, pin
- Export a conversation to Markdown or PDF, citations intact

## Core feature 6: Embed and API

- Embeddable chat widget (script snippet) for any website, backed by a public collection
- REST API: `POST /ask` with streaming, API keys, per-key rate limits
- Widget and API return the same cited answers as the app

## Answers have to be grounded

- Users will ask things the docs don’t cover; that’s the normal case, not an edge case
- Every claim cites a retrieved passage; a check verifies the cited text exists, and unsupported claims are dropped or flagged
- No relevant source → decline, never improvise
- Docs disagree (old vs new policy) → show both with dates, don’t silently pick one
- Text inside documents is data, never instructions; prompt injection is ignored
- Permissions enforced inside the retrieval query, on the server: chunks from docs you can’t access never reach the prompt
- Quality is measured, not felt: eval set of 100+ questions including unanswerable ones, run in CI, regressions block merges
- Why it matters: one confident wrong answer and people stop trusting it and go back to Ctrl+F

## Ingestion, storage, and freshness

- Original files in object storage (e.g. S3 or R2); chunks, embeddings, and metadata in a vector store (e.g. pgvector)
- Incremental re-index: only changed chunks get re-embedded
- Delete a doc → its chunks and vectors go too; no ghost answers
- Embedding model and version stored per chunk; model swap = background re-embed, no downtime
- Chats save automatically; no “save” button
- Every answer logged: question, retrieved chunks, prompt, model, answer, latency; replay any past question against the current index

## Performance targets

- First token under 1.5 s; p95 full answer under 8 s
- Retrieval hit rate@5 ≥ 90% on the eval set
- Faithfulness ≥ 95%: every citation actually supports its claim
- ≥ 90% of unanswerable questions correctly declined
- 1,000 pages ingested in under 5 minutes
- 50 simultaneous askers without noticeable lag
- Cost per answer measured and reported
- Eval and load-test results and the approach behind them written up in the README

## What we’re NOT building (v1)

- Fine-tuning or training models
- Agents, tool use, web browsing
- Third-party connectors (Drive, Notion, Slack, Confluence); upload and URL only
- OCR for scans; image, audio, or video understanding
- Voice and mobile apps (the web app should still be usable on a tablet)
- Billing, pricing plans, SSO, organization-level admin
- Multi-language tuning

## End result

A working product: sign in, upload a pile of docs, ask questions, and get streamed answers with citations that open the exact passage, “not found” instead of guesses, permissions that hold, published eval scores, and a chat widget live on a real website.
