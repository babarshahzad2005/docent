"""The Demo Collection is a Public Collection, with no expiry (#95).

GLOSSARY: Demo Collection. Anyone can try Docent on it without signing in. It has no Owner,
so nobody could turn it off from the app anyway; the check makes that hold for any write.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-23
"""

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("update app.collections set public = true, public_until = null where is_demo")
    op.execute(
        """
        alter table app.collections add constraint collections_demo_always_public
            check (not is_demo or (public and public_until is null))
        """
    )


def downgrade() -> None:
    op.execute("alter table app.collections drop constraint collections_demo_always_public")
    op.execute("update app.collections set public = false where is_demo")
