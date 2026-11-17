"""A fingerprint of each Document's file, so uploading the same file twice is noticed.

`content_hash` is the SHA-256 of the original file. The browser sends one when it starts an
upload, so a duplicate can be flagged before anything is stored; ingestion replaces it with
the hash of the bytes actually stored, so it can be trusted afterwards.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-17
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table app.documents add column content_hash text")
    op.execute(
        "create index documents_content_hash_idx on app.documents (collection_id, content_hash)"
    )


def downgrade() -> None:
    op.execute("drop index app.documents_content_hash_idx")
    op.execute("alter table app.documents drop column content_hash")
