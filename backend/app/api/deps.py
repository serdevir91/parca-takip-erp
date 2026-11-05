"""Shared dependencies and helpers for API routers (not a router itself)."""
from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import DESIGN_ROLES, EDIT_ROLES, current_user, require_roles
from ..db import get_db
from ..models import ROLE_ADMIN, Project, User
from app.core.i18n import tx

# Ready-made role guards
any_user = current_user
editor = require_roles(*EDIT_ROLES)
designer = require_roles(*DESIGN_ROLES)
admin = require_roles(ROLE_ADMIN)

__all__ = ["any_user", "editor", "designer", "admin", "get_db", "project_or_404", "Session", "User", "Depends"]


def project_or_404(db: Session, project_id: int) -> Project:
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(404, tx("Proje bulunamadı"))
    return p
