"""Declines (#43).

`messages.outcome` says how a finished answer ended ("answered", "declined", "unverified", or
"no_documents"), so a saved Conversation shows a Decline with its closest passages.
`answer_logs.decline_reason` records why: weak retrieval (the model wasn't asked), the model
declining, or nothing in Scope.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-19
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table app.messages add column outcome text")
    op.execute("alter table app.answer_logs add column decline_reason text")


def downgrade() -> None:
    op.execute("alter table app.answer_logs drop column decline_reason")
    op.execute("alter table app.messages drop column outcome")
