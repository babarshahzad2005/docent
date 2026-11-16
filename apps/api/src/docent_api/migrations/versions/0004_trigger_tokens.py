"""Tokens that let the database's scheduler start ingestion batches; retryable failures.

`failure_retryable` marks failures a retry could fix (a provider kept erroring), as opposed to
ones it can't (no text in the file), so the Library offers Retry only when it can help.

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
    op.execute(
        "alter table app.documents add column failure_retryable boolean not null default false"
    )


def downgrade() -> None:
    op.execute("alter table app.documents drop column failure_retryable")
    op.execute("drop table app.trigger_tokens")
