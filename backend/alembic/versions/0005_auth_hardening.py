"""Token version on users: a password change, reset or deactivation ends older sessions.

Idempotent like 0002: 0001 builds the schema from the current models, so on a fresh install every
step here is skipped.

Revision ID: 0005_auth_hardening
Revises: 0004_photos_chat
Create Date: 2026-11-03
"""
import sqlalchemy as sa
from alembic import op

revision = "0005_auth_hardening"
down_revision = "0004_photos_chat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("users")}
    with op.batch_alter_table("users") as t:
        if "token_version" not in cols:
            t.add_column(sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("users") as t:
        t.drop_column("token_version")
