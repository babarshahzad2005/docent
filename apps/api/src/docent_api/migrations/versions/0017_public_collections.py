"""Public Collections (#93).

`collections.public` lets anyone with the link ask a Collection without signing in, until
`public_until` if set (GLOSSARY: Public Collection). The Personal Collection is never public.
`answer_logs.channel` says where an answer was asked: in the app, by a Visitor on a Public
Collection, or (later) through the API; Visitor answers have no User and no Message.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-23
"""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        alter table app.collections
            add column public boolean not null default false,
            add column public_until timestamptz,
            add constraint collections_personal_never_public
                check (not public or personal_owner_id is null)
        """
    )
    op.execute(
        """
        alter table app.answer_logs add column channel text not null default 'app'
            check (channel in ('app', 'public', 'api'))
        """
    )


def downgrade() -> None:
    op.execute("alter table app.answer_logs drop column channel")
    op.execute(
        """
        alter table app.collections
            drop constraint collections_personal_never_public,
            drop column public_until,
            drop column public
        """
    )
