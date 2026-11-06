"""Add the production steps to a saved temin list. A fresh install gets them from the defaults.

Revision ID: 0013_temin_steps
Revises: 0012_chat_actions
Create Date: 2026-11-06
"""
import sqlalchemy as sa
from alembic import op

revision = "0013_temin_steps"
down_revision = "0012_chat_actions"
branch_labels = None
depends_on = None

STEPS = ("Lazer Kesim", "Büküm", "Kaynak", "Talaşlı İmalat", "Montaj", "Boya", "Isıl İşlem")
settings = sa.table("settings", sa.column("key", sa.String), sa.column("value", sa.JSON))


def upgrade() -> None:
    bind = op.get_bind()
    saved = bind.execute(sa.select(settings.c.value).where(settings.c.key == "temin_types")).scalar()
    if not isinstance(saved, list):
        return
    names = {t.get("name") for t in saved}
    new = [{"name": n, "kind": "İmalat", "drawing": True, "order": True} for n in STEPS if n not in names]
    if new:
        bind.execute(settings.update().where(settings.c.key == "temin_types").values(value=[*saved, *new]))


def downgrade() -> None:
    pass
