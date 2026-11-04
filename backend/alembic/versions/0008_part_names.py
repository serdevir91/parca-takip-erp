"""Part names, shared by all projects.

Idempotent like 0006: on a fresh install 0001 already builds this table from the models.

Revision ID: 0008_part_names
Revises: 0007_hide_and_tree
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "0008_part_names"
down_revision = "0007_hide_and_tree"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "part_names" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "part_names",
            sa.Column("part_no", sa.String(200), primary_key=True),
            sa.Column("name", sa.String(300), nullable=False, server_default=""),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_by", sa.String(64), nullable=False, server_default=""),
        )


def downgrade() -> None:
    op.drop_table("part_names")
