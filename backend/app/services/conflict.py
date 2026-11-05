"""Conflict warning for edit forms.

A form reads `rev` with the record and sends it back. `claim` moves the revision forward in one UPDATE that only
matches the revision the form saw, so of two people saving the same version exactly one gets through, on SQLite and
PostgreSQL alike. The other gets a 409 naming who saved first, and chooses: reload, or save again without `rev`,
which overwrites on purpose. Saves that send no `rev` (old clients, bulk edits, scripts) still bump the revision.
Like `erp`, this does not commit; the caller commits.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from ..models import User
from app.core.i18n import tx


def claim(db: Session, row: Any, base: int | None, user: User | None) -> None:
    model = type(row)
    name = user.username if user else ""
    q = update(model).where(model.id == row.id)
    if base is not None:
        q = q.where(model.edit_rev == base)
    done = db.execute(q.values(edit_rev=model.edit_rev + 1, edit_by=name).execution_options(synchronize_session=False))
    if done.rowcount == 0:
        db.rollback()
        db.refresh(row)
        raise HTTPException(409, detail={"conflict": True, "by": row.edit_by, "rev": row.edit_rev,
                                         "message": tx("Bu kaydı siz düzenlerken {0} değiştirdi", row.edit_by or 'başka biri')})
    db.expire(row, ["edit_rev", "edit_by"])
