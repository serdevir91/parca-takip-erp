"""Chat: edit, reply, forward, delete for me, reactions and a pinned message per room.

Idempotent like 0006: on a fresh install 0001 already builds all of this from the models.

Revision ID: 0012_chat_actions
Revises: 0011_edit_guards
Create Date: 2026-11-05
"""
import sqlalchemy as sa
from alembic import op

from app import models

revision = "0012_chat_actions"
down_revision = "0011_edit_guards"
branch_labels = None
depends_on = None


def _message_columns() -> list[sa.Column]:
    return [sa.Column("edited_at", models.UtcDateTime(), nullable=True),
            sa.Column("reply_to_id", sa.Integer, nullable=True),
            sa.Column("forwarded_from", sa.String(120), nullable=True)]


def _columns(bind: sa.engine.Connection, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    have = _columns(bind, "chat_messages")
    for col in _message_columns():
        if col.name not in have:
            op.add_column("chat_messages", col)
    if "pinned_id" not in _columns(bind, "chat_rooms"):
        op.add_column("chat_rooms", sa.Column("pinned_id", sa.Integer, nullable=True))
    for model in (models.ChatHidden, models.ChatReaction):
        if not sa.inspect(bind).has_table(model.__tablename__):
            model.__table__.create(bind)


def downgrade() -> None:
    op.drop_table("chat_reactions")
    op.drop_table("chat_hidden")
    op.drop_column("chat_rooms", "pinned_id")
    for col in _message_columns():
        op.drop_column("chat_messages", col.name)
