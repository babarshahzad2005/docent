"""Users, Collections, and Memberships, plus the vector extension.

Tables live in the `app` schema, which Supabase does not expose through its auto-generated
Data API: all access goes through the Docent API, where permissions are enforced. Row level
security is enabled with no policies as a second lock on the same door.

Revision ID: 0001
Revises:
Create Date: 2026-11-16
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("create schema if not exists extensions")
    op.execute("create extension if not exists vector with schema extensions")
    op.execute("create schema if not exists app")
    op.execute("create type app.member_role as enum ('owner', 'editor', 'viewer')")
    op.execute(
        """
        create table app.users (
            id uuid primary key,
            email text not null,
            created_at timestamptz not null default now()
        )
        """
    )
    op.execute(
        """
        create table app.collections (
            id uuid primary key default gen_random_uuid(),
            name text not null check (length(trim(name)) between 1 and 120),
            personal_owner_id uuid unique references app.users (id) on delete cascade,
            created_at timestamptz not null default now()
        )
        """
    )
    op.execute(
        """
        create table app.memberships (
            collection_id uuid not null references app.collections (id) on delete cascade,
            user_id uuid not null references app.users (id) on delete cascade,
            role app.member_role not null,
            created_at timestamptz not null default now(),
            primary key (collection_id, user_id)
        )
        """
    )
    op.execute("create index memberships_user_id_idx on app.memberships (user_id)")
    for table in ("users", "collections", "memberships"):
        op.execute(f"alter table app.{table} enable row level security")


def downgrade() -> None:
    op.execute("drop table app.memberships")
    op.execute("drop table app.collections")
    op.execute("drop table app.users")
    op.execute("drop type app.member_role")
