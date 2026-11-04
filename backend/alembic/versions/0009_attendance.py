"""Attendance: shifts with clock-in and clock-out.

Idempotent like 0006: on a fresh install 0001 already builds this table from the models.

Revision ID: 0009_attendance
Revises: 0008_part_names
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "0009_attendance"
down_revision = "0008_part_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "attendance" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "attendance",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("employee_id", sa.Integer, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
            sa.Column("work_date", sa.Date, nullable=False),
            sa.Column("clock_in", sa.DateTime, nullable=False),
            sa.Column("clock_out", sa.DateTime, nullable=True),
            sa.Column("break_minutes", sa.Integer, nullable=False, server_default="0"),
            sa.Column("note", sa.String(300), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(64), nullable=False, server_default=""),
            sa.Column("updated_by", sa.String(64), nullable=False, server_default=""),
        )
        op.create_index("ix_attendance_employee_id", "attendance", ["employee_id"])
        op.create_index("ix_attendance_work_date", "attendance", ["work_date"])


def downgrade() -> None:
    op.drop_table("attendance")
