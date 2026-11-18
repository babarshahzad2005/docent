"""The Demo Collection, and where a Document came from.

`collections.is_demo` marks the one Demo Collection: openly licensed Documents every User can
ask, read-only (PRD decision log, 2026-11-18). `documents.source_url` and `source_credit` record
where a Document was published and under what licence, so the app can credit it.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-18
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table app.collections add column is_demo boolean not null default false")
    op.execute(
        "create unique index collections_one_demo_idx on app.collections (is_demo) where is_demo"
    )
    op.execute("alter table app.documents add column source_url text")
    op.execute("alter table app.documents add column source_credit text")


def downgrade() -> None:
    op.execute("alter table app.documents drop column source_credit")
    op.execute("alter table app.documents drop column source_url")
    op.execute("drop index app.collections_one_demo_idx")
    op.execute("alter table app.collections drop column is_demo")
