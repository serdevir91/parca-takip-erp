"""Edit revisions for conflict warnings, invoice discount, credit notes, public holidays.

Idempotent like 0006: on a fresh install 0001 already builds all of this from the models.
Invoices already issued keep the total they were printed with: legacy_total marks them for the old formula.

Revision ID: 0011_edit_guards
Revises: 0010_operations
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

from app import models

revision = "0011_edit_guards"
down_revision = "0010_operations"
branch_labels = None
depends_on = None

REVISIONED = ["projects", "firms", "stock_items", "purchase_orders", "work_orders", "sales_orders", "invoices",
              "employees", "time_entries", "attendance"]


def _invoice_columns() -> list[sa.Column]:
    return [sa.Column("discount_pct", sa.Float, nullable=False, server_default="0"),
            sa.Column("legacy_total", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("credit_of_id", sa.Integer, nullable=True)]


def _columns(bind: sa.engine.Connection, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    for table in REVISIONED:
        have = _columns(bind, table)
        if "edit_rev" not in have:
            op.add_column(table, sa.Column("edit_rev", sa.Integer, nullable=False, server_default="0"))
        if "edit_by" not in have:
            op.add_column(table, sa.Column("edit_by", sa.String(64), nullable=False, server_default=""))
    have = _columns(bind, "invoices")
    for col in _invoice_columns():
        if col.name not in have:
            op.add_column("invoices", col)
            if col.name == "legacy_total":
                op.execute(sa.text("UPDATE invoices SET legacy_total = :yes WHERE status = 'issued'")
                           .bindparams(sa.bindparam("yes", True, sa.Boolean)))
    # "sales_credit" and "purchase_credit" do not fit the old 10. SQLite does not enforce the length.
    if bind.dialect.name != "sqlite":
        op.alter_column("invoices", "kind", type_=sa.String(16), existing_nullable=False)
    if "ix_invoices_credit_of_id" not in {i["name"] for i in sa.inspect(bind).get_indexes("invoices")}:
        op.create_index("ix_invoices_credit_of_id", "invoices", ["credit_of_id"])
    if not sa.inspect(bind).has_table("holidays"):
        models.Holiday.__table__.create(bind)


def downgrade() -> None:
    op.drop_table("holidays")
    op.drop_index("ix_invoices_credit_of_id", table_name="invoices")
    for col in _invoice_columns():
        op.drop_column("invoices", col.name)
    for table in REVISIONED:
        op.drop_column(table, "edit_by")
        op.drop_column(table, "edit_rev")
