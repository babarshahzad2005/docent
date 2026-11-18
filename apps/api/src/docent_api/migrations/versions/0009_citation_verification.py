"""Citation verification (ADR 0007).

`messages.verified` says the answer's Citations were checked against their passages, and
`messages.removed` lists the claims removed because they couldn't be (shown with the answer).
`answer_logs.raw_answer` is the model's whole reply, quotes included, and
`answer_logs.verification` the result for each Citation.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-18
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table app.messages add column verified boolean not null default false")
    op.execute("alter table app.messages add column removed jsonb not null default '[]'")
    op.execute("alter table app.answer_logs add column raw_answer text")
    op.execute("alter table app.answer_logs add column verification jsonb")


def downgrade() -> None:
    op.execute("alter table app.answer_logs drop column verification")
    op.execute("alter table app.answer_logs drop column raw_answer")
    op.execute("alter table app.messages drop column removed")
    op.execute("alter table app.messages drop column verified")
