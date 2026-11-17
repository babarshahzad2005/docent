"""Files waiting to be removed from storage after their Document was deleted.

Deleting a Document commits the row deletion first and removes its file afterwards, so a
remaining Document can never lose its file. When storage can't remove the file right away (it
is down, or the browser is still uploading it), the path waits here and ingestion batches
remove it once `delete_after` has passed.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-17
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table app.storage_deletions (
            path text primary key,
            delete_after timestamptz not null default now(),
            attempts integer not null default 0,
            created_at timestamptz not null default now()
        )
        """
    )
    op.execute("alter table app.storage_deletions enable row level security")


def downgrade() -> None:
    op.execute("drop table app.storage_deletions")
