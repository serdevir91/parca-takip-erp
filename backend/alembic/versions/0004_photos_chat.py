"""Product photos and chat (rooms, members, messages).

Idempotent like 0002: 0001 builds the schema from the current models, so on a fresh install every
step here is skipped.

Revision ID: 0004_photos_chat
Revises: 0003_sales_finance_hr
Create Date: 2026-11-03
"""
import sqlalchemy as sa
from alembic import op

from app import models

revision = "0004_photos_chat"
down_revision = "0003_sales_finance_hr"
branch_labels = None
depends_on = None

NEW_TABLES = [models.Photo, models.ChatRoom, models.ChatMember, models.ChatMessage]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for m in NEW_TABLES:
        if not insp.has_table(m.__tablename__):
            m.__table__.create(bind)


def downgrade() -> None:
    bind = op.get_bind()
    for m in reversed(NEW_TABLES):
        m.__table__.drop(bind, checkfirst=True)
