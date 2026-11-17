"""Conversations, their messages and Citations, the Answer Log, and keyword search on chunks.

- `chunks.search` is a full-text index of each passage with its headings, so retrieval can
  combine keyword matches with vector similarity (hybrid search, PRD glossary). Ingestion fills
  it; existing chunks are filled here.
- A Citation keeps the passage text it was based on, with where it came from, so it still
  shows what the answer used after the Document is replaced or deleted (ADR 0004).
- The Answer Log records every answer for quality review: its Scope, the passages retrieved,
  the prompt, the model, and timings (GLOSSARY). Entries are kept 90 days (PRD decision log).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-17
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table app.chunks add column search tsvector")
    op.execute(
        """
        update app.chunks
        set search = to_tsvector('english', array_to_string(heading_path, ' ') || ' ' || content)
        """
    )
    op.execute("create index chunks_search_idx on app.chunks using gin (search)")

    op.execute("create type app.message_role as enum ('user', 'assistant')")
    op.execute(
        "create type app.message_status as enum ('streaming', 'complete', 'interrupted', 'failed')"
    )
    op.execute(
        """
        create table app.conversations (
            id uuid primary key default gen_random_uuid(),
            user_id uuid not null references app.users (id) on delete cascade,
            title text not null,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        )
        """
    )
    op.execute("create index conversations_user_id_idx on app.conversations (user_id, updated_at)")
    op.execute(
        """
        create table app.messages (
            id uuid primary key default gen_random_uuid(),
            conversation_id uuid not null references app.conversations (id) on delete cascade,
            role app.message_role not null,
            content text not null default '',
            status app.message_status not null default 'complete',
            scope uuid[] not null default '{}',
            created_at timestamptz not null default now()
        )
        """
    )
    op.execute(
        "create index messages_conversation_idx on app.messages (conversation_id, created_at)"
    )
    op.execute(
        """
        create table app.citations (
            message_id uuid not null references app.messages (id) on delete cascade,
            number integer not null,
            chunk_id uuid references app.chunks (id) on delete set null,
            document_id uuid references app.documents (id) on delete set null,
            document_name text not null,
            heading_path text[] not null default '{}',
            page integer,
            passage text not null,
            primary key (message_id, number)
        )
        """
    )
    op.execute(
        """
        create table app.answer_logs (
            id uuid primary key default gen_random_uuid(),
            message_id uuid references app.messages (id) on delete set null,
            user_id uuid references app.users (id) on delete set null,
            question text not null,
            scope uuid[] not null,
            retrieved jsonb not null,
            prompt text not null,
            answer text not null default '',
            outcome text not null,
            model text,
            model_version text,
            fell_back_from text,
            latency_ms integer,
            first_token_ms integer,
            input_tokens integer,
            output_tokens integer,
            created_at timestamptz not null default now()
        )
        """
    )
    op.execute("create index answer_logs_created_at_idx on app.answer_logs (created_at)")
    for table in ("conversations", "messages", "citations", "answer_logs"):
        op.execute(f"alter table app.{table} enable row level security")


def downgrade() -> None:
    for table in ("answer_logs", "citations", "messages", "conversations"):
        op.execute(f"drop table app.{table}")
    op.execute("drop type app.message_status")
    op.execute("drop type app.message_role")
    op.execute("drop index app.chunks_search_idx")
    op.execute("alter table app.chunks drop column search")
