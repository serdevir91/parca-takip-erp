"""Audit log helpers. Every user-visible change goes through `record` so the
part detail timeline and the admin audit screen stay complete."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditLog, User


def _s(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return "Evet" if v else "Hayır"
    return str(v)


def record(db: Session, user: User | None, entity: str, entity_id: str | int | None,
           field: str = "", old: Any = None, new: Any = None,
           project_id: int | None = None, action: str = "update") -> AuditLog:
    log = AuditLog(user_id=user.id if user else None, username=user.username if user else "sistem",
                   project_id=project_id, entity=entity, entity_id=str(entity_id) if entity_id is not None else "",
                   field=field, old=_s(old), new=_s(new), action=action)
    db.add(log)
    return log


def record_changes(db: Session, user: User | None, obj: Any, changes: dict[str, Any], entity: str,
                   entity_id: str | int, project_id: int | None = None) -> int:
    """Apply `changes` to `obj` attribute by attribute, logging each real change.
    Returns the number of fields that changed."""
    n = 0
    for f, new in changes.items():
        old = getattr(obj, f)
        if old == new:
            continue
        setattr(obj, f, new)
        record(db, user, entity, entity_id, f, old, new, project_id)
        n += 1
    return n
