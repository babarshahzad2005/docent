"""One Owner per Collection (#77).

GLOSSARY: Owner, "the single Member who controls a Collection". Transfers demote the old
Owner before promoting the new one, so this holds at every step; racing transfers that slipped
past the application's check would now fail instead of leaving two Owners.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-22
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "create unique index memberships_one_owner on app.memberships (collection_id) "
        "where role = 'owner'"
    )


def downgrade() -> None:
    op.execute("drop index app.memberships_one_owner")
