"""The API Key that asked, in the Answer Log (#99).

An answer asked through `POST /ask` is logged with its key, not a User. Revoking a key keeps
its row (0020), so the log still says which key asked; deleting the Collection deletes its
keys, and the log entries keep everything but the link.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-26
"""

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        alter table app.answer_logs add column api_key_id uuid
            references app.api_keys (id) on delete set null
        """
    )
    op.execute(
        "create index answer_logs_api_key_id_idx on app.answer_logs (api_key_id)"
        " where api_key_id is not null"
    )


def downgrade() -> None:
    op.execute("alter table app.answer_logs drop column api_key_id")
