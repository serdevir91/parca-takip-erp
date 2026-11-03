"""ERP modules: supplier card fields, stock, purchase orders, work orders.

0001 builds the schema from the current models, so on a fresh install these
tables and columns already exist; every step here is skipped when present.

Revision ID: 0002_erp_modules
Revises: 0001_initial
Create Date: 2026-11-03
"""
import sqlalchemy as sa
from alembic import op

from app import models

revision = "0002_erp_modules"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

NEW_TABLES = [models.StockItem, models.StockMove, models.PurchaseOrder, models.PurchaseOrderLine, models.WorkOrder]
FIRM_COLUMNS = [
    sa.Column("phone", sa.String(50), nullable=False, server_default=""),
    sa.Column("email", sa.String(200), nullable=False, server_default=""),
    sa.Column("address", sa.Text(), nullable=False, server_default=""),
    sa.Column("tax_office", sa.String(100), nullable=False, server_default=""),
    sa.Column("tax_no", sa.String(30), nullable=False, server_default=""),
    sa.Column("lead_days", sa.Integer(), nullable=False, server_default="0"),
]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    have = {c["name"] for c in insp.get_columns("firms")}
    missing = [c for c in FIRM_COLUMNS if c.name not in have]
    if missing:
        with op.batch_alter_table("firms") as b:
            for c in missing:
                b.add_column(c)
    for m in NEW_TABLES:
        if not insp.has_table(m.__tablename__):
            m.__table__.create(bind)


def downgrade() -> None:
    bind = op.get_bind()
    for m in reversed(NEW_TABLES):
        m.__table__.drop(bind, checkfirst=True)
    with op.batch_alter_table("firms") as b:
        for c in FIRM_COLUMNS:
            b.drop_column(c.name)
