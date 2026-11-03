"""Per-user permissions, live sync counter, sales orders, invoices, payments, employees, time entries.

Idempotent like 0002: 0001 builds the schema from the current models, so on a fresh install every
step here is skipped.

Revision ID: 0003_sales_finance_hr
Revises: 0002_erp_modules
Create Date: 2026-11-03
"""
import sqlalchemy as sa
from alembic import op

from app import models

revision = "0003_sales_finance_hr"
down_revision = "0002_erp_modules"
branch_labels = None
depends_on = None

NEW_TABLES = [models.SyncState, models.SalesOrder, models.SalesOrderLine, models.Invoice, models.InvoiceLine,
              models.Payment, models.Employee, models.TimeEntry]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "permissions" not in {c["name"] for c in insp.get_columns("users")}:
        with op.batch_alter_table("users") as b:
            b.add_column(sa.Column("permissions", sa.JSON(), nullable=True))
    for m in NEW_TABLES:
        if not insp.has_table(m.__tablename__):
            m.__table__.create(bind)


def downgrade() -> None:
    bind = op.get_bind()
    for m in reversed(NEW_TABLES):
        m.__table__.drop(bind, checkfirst=True)
    with op.batch_alter_table("users") as b:
        b.drop_column("permissions")
