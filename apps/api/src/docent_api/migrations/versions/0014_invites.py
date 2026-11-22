"""Invites (#76).

An Owner invites an email address to a Collection with a Role. Signing in with that address,
through the invite's link or not, makes the User a Member, and marks the invite accepted, so
opening its link again still leads to the Collection. Docent sends
no email: the Owner passes the link on (PRD decision log, 2026-11-22). The link is just the
invite's id, which grants nothing without signing in as the invited address.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-22
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table app.invites (
            id uuid primary key default gen_random_uuid(),
            collection_id uuid not null references app.collections (id) on delete cascade,
            email text not null check (email = lower(email) and length(email) between 3 and 254),
            role app.member_role not null check (role in ('editor', 'viewer')),
            invited_by uuid references app.users (id) on delete set null,
            created_at timestamptz not null default now(),
            expires_at timestamptz not null default now() + interval '14 days',
            accepted_by uuid references app.users (id) on delete cascade,
            accepted_at timestamptz,
            unique (collection_id, email)
        )
        """
    )
    # Signing in looks up a User's invites by address.
    op.execute("create index invites_email_idx on app.invites (email)")
    op.execute("alter table app.invites enable row level security")


def downgrade() -> None:
    op.execute("drop table app.invites")
