"""Montaj föyü: remembers which printed part codes were confirmed on a plan.

Revision ID: 0015_assembly_scans
Revises: 0014_assembly_plans
Create Date: 2026-11-07
"""
import sqlalchemy as sa
from alembic import op

from app.models import AssemblyScan

revision = "0015_assembly_scans"
down_revision = "0014_assembly_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 builds a fresh database from the models, so the table may already be there
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(AssemblyScan.__tablename__):
        AssemblyScan.__table__.create(bind)


def downgrade() -> None:
    op.drop_table("assembly_scans")
