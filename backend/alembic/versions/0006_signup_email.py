"""Self sign-up and e-mail: users get an e-mail address and a pending flag (waiting for admin approval).

Idempotent like 0005: on a fresh install 0001 already builds these columns from the models.

Revision ID: 0006_signup_email
Revises: 0005_auth_hardening
Create Date: 2026-11-03
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_signup_email"
down_revision = "0005_auth_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("users")}
    with op.batch_alter_table("users") as t:
        if "email" not in cols:
            t.add_column(sa.Column("email", sa.String(200), nullable=False, server_default=""))
        if "pending" not in cols:
            t.add_column(sa.Column("pending", sa.Boolean(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("users") as t:
        t.drop_column("pending")
        t.drop_column("email")
