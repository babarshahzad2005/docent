"""Documents and their chunks, with the documents table doubling as the ingestion queue.

A Document's status is its place in the pipeline (FLOWS.md, "Doc status"). Workers claim a
Document by setting `locked_until`; a crashed or timed-out batch simply lets the lease expire
and the next batch picks the Document up where it stopped (ADR 0008).

Each chunk records the Collection it belongs to (ADR 0002), so retrieval can filter on it
directly, and the embedding model that made its vector (ARCHITECTURE.md, "Decisions").

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-16
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create type app.document_status as enum
            ('uploading', 'queued', 'parsing', 'embedding', 'indexed', 'failed')
        """
    )
    op.execute(
        """
        create table app.documents (
            id uuid primary key default gen_random_uuid(),
            collection_id uuid not null references app.collections (id) on delete cascade,
            uploaded_by uuid references app.users (id) on delete set null,
            name text not null check (length(name) between 1 and 255),
            size_bytes bigint not null check (size_bytes >= 0),
            storage_path text not null unique,
            status app.document_status not null default 'uploading',
            failure_reason text,
            attempts integer not null default 0,
            locked_until timestamptz,
            effective_date date not null default current_date,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        )
        """
    )
    op.execute("create index documents_collection_id_idx on app.documents (collection_id)")
    op.execute(
        """
        create index documents_queue_idx on app.documents (created_at)
        where status in ('queued', 'parsing', 'embedding')
        """
    )
    op.execute(
        """
        create table app.chunks (
            id uuid primary key default gen_random_uuid(),
            document_id uuid not null references app.documents (id) on delete cascade,
            collection_id uuid not null references app.collections (id) on delete cascade,
            ordinal integer not null,
            heading_path text[] not null default '{}',
            page integer,
            content text not null,
            content_hash text not null,
            embedding extensions.vector(1024),
            embedding_model text,
            created_at timestamptz not null default now(),
            unique (document_id, ordinal)
        )
        """
    )
    op.execute("create index chunks_collection_id_idx on app.chunks (collection_id)")
    op.execute(
        """
        create index chunks_embedding_idx on app.chunks
        using hnsw (embedding extensions.vector_cosine_ops)
        """
    )
    for table in ("documents", "chunks"):
        op.execute(f"alter table app.{table} enable row level security")


def downgrade() -> None:
    op.execute("drop table app.chunks")
    op.execute("drop table app.documents")
    op.execute("drop type app.document_status")
