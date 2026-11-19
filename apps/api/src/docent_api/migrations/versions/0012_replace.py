"""Replace (#47).

A replacement is a Document row of its own while it is processed: `documents.replaces_id`
names the Document it will replace (at most one at a time), and it is hidden from the Library
and from retrieval. Once indexed, its passages move to the Document it replaces, whose own
passages are kept as text with `chunks.superseded_at` set (their vectors are dropped), so
past Citations still show what they cited (ADR 0004). Ordinals are then unique among a
Document's current passages only.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-19
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        alter table app.documents
        add column replaces_id uuid references app.documents (id) on delete cascade
        """
    )
    op.execute(
        "create unique index documents_one_replacement_idx on app.documents (replaces_id) "
        "where replaces_id is not null"
    )
    op.execute("alter table app.chunks add column superseded_at timestamptz")
    op.execute("alter table app.chunks drop constraint chunks_document_id_ordinal_key")
    op.execute(
        "create unique index chunks_current_ordinal_idx on app.chunks (document_id, ordinal) "
        "where superseded_at is null"
    )


def downgrade() -> None:
    op.execute("delete from app.chunks where superseded_at is not null")
    op.execute("drop index app.chunks_current_ordinal_idx")
    op.execute(
        "alter table app.chunks add constraint chunks_document_id_ordinal_key "
        "unique (document_id, ordinal)"
    )
    op.execute("alter table app.chunks drop column superseded_at")
    op.execute("delete from app.documents where replaces_id is not null")
    op.execute("drop index app.documents_one_replacement_idx")
    op.execute("alter table app.documents drop column replaces_id")
