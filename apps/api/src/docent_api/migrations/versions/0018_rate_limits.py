"""Rate limits (#94).

One row per bucket and time window, counting requests: a Visitor's hashed network address
per hour, and every Visitor together per day; API Keys will use it too. Rows are deleted once
their window is long past. No raw network address is ever stored (PRD decision log,
2026-11-15).

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-23
"""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table app.rate_limits (
            bucket text not null,
            window_start timestamptz not null,
            hits integer not null default 1,
            primary key (bucket, window_start)
        )
        """
    )
    op.execute("create index rate_limits_window_start_idx on app.rate_limits (window_start)")
    op.execute("alter table app.rate_limits enable row level security")


def downgrade() -> None:
    op.execute("drop table app.rate_limits")
