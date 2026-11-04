"""Leave and shift requests, exchange rates, receipts and deliveries, work order materials and route,
user preferences, dismissed notifications, project templates.

Idempotent like 0006: on a fresh install 0001 already builds all of this from the models.

Revision ID: 0010_operations
Revises: 0009_attendance
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

from app import models

revision = "0010_operations"
down_revision = "0009_attendance"
branch_labels = None
depends_on = None

NEW_TABLES = [models.LeaveRequest, models.AttendanceRequest, models.ExchangeRate, models.PurchaseReceipt,
              models.SalesDelivery, models.WorkOrderMaterial, models.WorkOrderOp, models.UserPref,
              models.NotificationRead, models.ProjectTemplate]
NEW_COLUMNS = [("stock_items", sa.Column("reorder_qty", sa.Float, nullable=False, server_default="0")),
               ("stock_items", sa.Column("preferred_firm_id", sa.Integer, nullable=True)),
               ("purchase_orders", sa.Column("rate", sa.Float, nullable=True)),
               ("sales_orders", sa.Column("rate", sa.Float, nullable=True)),
               ("invoices", sa.Column("rate", sa.Float, nullable=True)),
               ("payments", sa.Column("rate", sa.Float, nullable=True)),
               ("sales_order_lines", sa.Column("delivered_qty", sa.Float, nullable=False, server_default="0")),
               ("invoice_lines", sa.Column("source_line_id", sa.Integer, nullable=True)),
               ("employees", sa.Column("annual_leave_days", sa.Float, nullable=True))]


def upgrade() -> None:
    bind = op.get_bind()
    for table, col in NEW_COLUMNS:
        if col.name not in {c["name"] for c in sa.inspect(bind).get_columns(table)}:
            op.add_column(table, col)
    for model in NEW_TABLES:
        model.__table__.create(bind, checkfirst=True)


def downgrade() -> None:
    for model in reversed(NEW_TABLES):
        op.drop_table(model.__tablename__)
    for table, col in reversed(NEW_COLUMNS):
        op.drop_column(table, col.name)
