"""API Keys (#98).

An Owner's ask-only credential for one Collection (GLOSSARY: API Key; PRD decision log,
2026-11-15). Only a SHA-256 hash of the secret is stored: the secret is long and random, so a
fast hash is enough to make a stolen table useless. Revoking a key marks it (revoked_at), so the
Answer Log can still say which key asked (#99); deleting the Collection deletes its keys.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-26
"""

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table app.api_keys (
            id uuid primary key default gen_random_uuid(),
            collection_id uuid not null references app.collections (id) on delete cascade,
            name text not null check (char_length(name) between 1 and 80),
            key_hash bytea not null unique,
            created_by uuid references app.users (id) on delete set null,
            created_at timestamptz not null default now(),
            last_used_at timestamptz,
            revoked_at timestamptz
        )
        """
    )
    op.execute("create index api_keys_collection_id_idx on app.api_keys (collection_id)")
    op.execute("alter table app.api_keys enable row level security")


def downgrade() -> None:
    op.execute("drop table app.api_keys")
