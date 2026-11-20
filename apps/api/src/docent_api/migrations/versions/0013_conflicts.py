"""Documents that disagree (#48).

`messages.conflict` and `answer_logs.conflict` record, when an answer's Documents disagree,
each version: the passage, what it says, its Document, and its Effective Date, newest first.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-20
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table app.messages add column conflict jsonb")
    op.execute("alter table app.answer_logs add column conflict jsonb")


def downgrade() -> None:
    op.execute("alter table app.answer_logs drop column conflict")
    op.execute("alter table app.messages drop column conflict")
