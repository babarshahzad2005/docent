"""Lock the migration version table like every other application table.

The migration environment moves `alembic_version` from `public` into `app` before this runs
(ADR 0009). Row level security with no policies keeps it unreadable even if the schema were
ever exposed.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-16
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table app.alembic_version enable row level security")


def downgrade() -> None:
    op.execute("alter table app.alembic_version disable row level security")
