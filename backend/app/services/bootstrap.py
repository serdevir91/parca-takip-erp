"""First-start seeding: admin user, default fastener rules, T-35 settings and firms.

Every step is idempotent, so it runs on each start and only fills what is missing.
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import hash_password
from ..config import get_settings
from ..core.fastener import DEFAULT_RULES as FASTENER_DEFAULTS
from ..core.t35 import DEFAULT_MANUFACTURERS
from ..models import ROLE_ADMIN, FastenerRule, Firm, Setting, User
from .settings import DEFAULTS

log = logging.getLogger(__name__)


def seed_defaults(db: Session) -> None:
    cfg = get_settings()
    if not db.scalar(select(func.count()).select_from(User)):
        db.add(User(username=cfg.admin_user, full_name="Yönetici", role=ROLE_ADMIN,
                    password_hash=hash_password(cfg.admin_password)))
        log.warning("Admin user '%s' created. Change the password after the first login.", cfg.admin_user)

    if not db.scalar(select(func.count()).select_from(FastenerRule)):
        for r in FASTENER_DEFAULTS:
            db.add(FastenerRule(
                name=r["name"], pattern=r["pattern"], type=r["type"],
                desc=r.get("desc") or "", std=r.get("std") or "", size=r.get("size") or "",
                d=r.get("d") or "", l=r.get("l") or "", maps=r.get("maps") or {},
                priority=r.get("priority", 100), active=True))
    for key, value in DEFAULTS.items():
        if db.get(Setting, key) is None:
            db.add(Setting(key=key, value=value))
    if not db.scalar(select(func.count()).select_from(Firm)):
        for name in DEFAULT_MANUFACTURERS:
            db.add(Firm(name=name, kind="manufacturer"))
    db.commit()
