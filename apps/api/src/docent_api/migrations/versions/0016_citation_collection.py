"""The Collection each Citation's passage came from (#80).

Losing access hides a cited passage's text (PRD decision log, 2026-11-15). The passage's chunk
says where it lives now, but a deleted Document takes its chunks with it, and then nothing would
say whose the text was: a User removed from a Collection would see it again. Each Citation now
keeps the Collection its passage was in when cited.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-22
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "alter table app.citations add column collection_id uuid "
        "references app.collections (id) on delete set null"
    )
    op.execute(
        """
        update app.citations c set collection_id = k.collection_id
        from app.chunks k where k.id = c.chunk_id
        """
    )


def downgrade() -> None:
    op.execute("alter table app.citations drop column collection_id")
