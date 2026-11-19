"""Follow-up rewriting (#44).

`answer_logs.rewritten_question` is the follow-up as rewritten to stand on its own, which is
what was retrieved and answered; null for a first question, or when the rewrite failed.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-19
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table app.answer_logs add column rewritten_question text")


def downgrade() -> None:
    op.execute("alter table app.answer_logs drop column rewritten_question")
