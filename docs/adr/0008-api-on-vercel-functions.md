# The API runs as Vercel Functions; background work runs in short scheduled batches

Supersedes [ADR 0005](./0005-single-backend-service-postgres-queue.md).

The free plans that run an always-on Python service (Render, Koyeb, Fly.io, Hugging Face Docker Spaces) now require a payment card or a paid plan, which the $0 constraint rules out. The FastAPI app therefore deploys to Vercel's Python runtime as its own project, in the Singapore region beside the database: no card, no idle sleep, 2 GB of memory, but a 5-minute limit per invocation and no long-running process. Background work (ingestion) keeps the Postgres job queue from ADR 0005, but instead of a worker loop it is processed in resumable batches that each finish well inside 5 minutes: one batch is started right after an upload, and a scheduler in the database triggers a batch every minute for anything left over. Moving to an always-on host later only means running the same batch function in a loop.
