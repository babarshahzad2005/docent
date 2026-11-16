"""Tokens that let the database's scheduler start ingestion batches.

Only a hash is stored here; the token itself lives in Supabase Vault, where the scheduled job
reads it. Set up with `docent-setup-scheduler`.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-16
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table app.trigger_tokens (
            name text primary key,
            token_hash text not null,
            created_at timestamptz not null default now()
        )
        """
    )
    op.execute("alter table app.trigger_tokens enable row level security")


def downgrade() -> None:
    op.execute("drop table app.trigger_tokens")
