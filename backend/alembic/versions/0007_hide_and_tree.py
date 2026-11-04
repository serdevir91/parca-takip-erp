"""Dimmed parts and fasteners (hidden flag) and the product tree draft on the project.

Idempotent like 0006: on a fresh install 0001 already builds these columns from the models.

Revision ID: 0007_hide_and_tree
Revises: 0006_signup_email
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_hide_and_tree"
down_revision = "0006_signup_email"
branch_labels = None
depends_on = None


def _add(table: str, column: sa.Column) -> None:
    if column.name not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}:
        with op.batch_alter_table(table) as t:
            t.add_column(column)


def upgrade() -> None:
    _add("tracking", sa.Column("hidden", sa.Boolean(), nullable=False, server_default="0"))
    _add("fastener_settings", sa.Column("hidden", sa.Boolean(), nullable=False, server_default="0"))
    _add("projects", sa.Column("bom_draft", sa.JSON(), nullable=True))


def downgrade() -> None:
    for table, name in (("projects", "bom_draft"), ("fastener_settings", "hidden"), ("tracking", "hidden")):
        with op.batch_alter_table(table) as t:
            t.drop_column(name)
