"""Montaj föyü: assembly plans, field marks and counted part quantities.

Revision ID: 0014_assembly_plans
Revises: 0013_temin_steps
Create Date: 2026-11-07
"""
import sqlalchemy as sa
from alembic import op

from app.models import AssemblyExtra, AssemblyItem, AssemblyMark, AssemblyPlan, PartQuantity

revision = "0014_assembly_plans"
down_revision = "0013_temin_steps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 builds a fresh database from the models, so these tables may already be there
    bind = op.get_bind()
    for model in (AssemblyPlan, AssemblyItem, AssemblyExtra, AssemblyMark, PartQuantity):
        if not sa.inspect(bind).has_table(model.__tablename__):
            model.__table__.create(bind)


def downgrade() -> None:
    for table in ("part_quantities", "assembly_marks", "assembly_extras", "assembly_items", "assembly_plans"):
        op.drop_table(table)
