"""Admin-editable configuration stored in the `settings` table (JSON values).

Keys:
  t35                -> {rules, default_progress, skip_note}
  part_no_patterns   -> [regex, ...]
  purchased_assemblies -> [part_no, ...]   (global "Hazır Alım montaj" list, also mirrored in parts)
  status_rules       -> {big_drop_ratio}
  signup             -> {enabled}            (login screen offers "Hesap oluştur")
  smtp               -> see services/mailer.py
  temin_types        -> [{name, kind, drawing, order}, ...]   (core/status.DEFAULT_TEMIN_TYPES)
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import t35 as t35core
from ..core.bomparse import DEFAULT_PART_NO_PATTERNS
from ..core.fastener import DEFAULT_RULES as FASTENER_DEFAULTS, FastenerMatcher
from ..core.status import DEFAULT_TEMIN_TYPES, FIXED_TEMINS, KIND_HAZIR
from ..models import FastenerRule, Firm, Part, Setting

DEFAULTS: dict[str, Any] = {
    "t35": {"rules": t35core.DEFAULT_RULES, "default_progress": t35core.DEFAULT_PROGRESS,
            "skip_note": t35core.DEFAULT_SKIP_NOTE},
    "part_no_patterns": list(DEFAULT_PART_NO_PATTERNS),
    "status_rules": {"big_drop_ratio": 0.10},
    "signup": {"enabled": False},
}


def get_setting(db: Session, key: str, default: Any = None) -> Any:
    s = db.get(Setting, key)
    if s is None:
        return DEFAULTS.get(key, default) if default is None else default
    return s.value


def set_setting(db: Session, key: str, value: Any) -> None:
    s = db.get(Setting, key)
    if s is None:
        db.add(Setting(key=key, value=value))
    else:
        s.value = value


def temin_types(db: Session) -> list[dict[str, Any]]:
    """Saved types plus the fixed ones, which the rest of the system relies on."""
    saved = get_setting(db, "temin_types", DEFAULT_TEMIN_TYPES)
    names = {t["name"] for t in saved}
    return [*saved, *(t for t in DEFAULT_TEMIN_TYPES if t["name"] in FIXED_TEMINS and t["name"] not in names)]


def temin_choices(db: Session) -> list[str]:
    return [t["name"] for t in temin_types(db)]


def buy_temins(db: Session) -> list[str]:
    return [t["name"] for t in temin_types(db) if t["kind"] == KIND_HAZIR]


def manufacturers(db: Session) -> list[str]:
    return [f.name for f in db.scalars(select(Firm).where(Firm.active.is_(True),
                                                          Firm.kind.in_(["manufacturer", "both"]))
                                       .order_by(Firm.name))]


def suppliers(db: Session) -> list[str]:
    return [f.name for f in db.scalars(select(Firm).where(Firm.active.is_(True),
                                                          Firm.kind.in_(["supplier", "both"]))
                                       .order_by(Firm.name))]


def t35_config(db: Session) -> t35core.T35Config:
    v = get_setting(db, "t35") or {}
    return t35core.T35Config(
        rules=v["rules"] if v.get("rules") is not None else [dict(r) for r in t35core.DEFAULT_RULES],
        default_progress=v.get("default_progress") or t35core.DEFAULT_PROGRESS,
        skip_note=v.get("skip_note") if v.get("skip_note") is not None else list(t35core.DEFAULT_SKIP_NOTE),
        manufacturers=manufacturers(db) or list(t35core.DEFAULT_MANUFACTURERS),
    )


def fastener_rules(db: Session) -> list[dict[str, Any]]:
    rows = db.scalars(select(FastenerRule).order_by(FastenerRule.priority, FastenerRule.id)).all()
    return [dict(name=r.name, pattern=r.pattern, type=r.type, desc=r.desc, std=r.std, size=r.size,
                 d=r.d, l=r.l, maps=r.maps or {}, priority=r.priority, active=r.active) for r in rows]


def fastener_matcher(db: Session) -> FastenerMatcher:
    rules = fastener_rules(db)
    return FastenerMatcher(rules if rules else [dict(r) for r in FASTENER_DEFAULTS])


def purchased_assemblies(db: Session) -> list[str]:
    return list(db.scalars(select(Part.part_no).where(Part.is_purchased_assembly.is_(True))))


def part_no_patterns(db: Session) -> list[str]:
    return list(get_setting(db, "part_no_patterns") or DEFAULT_PART_NO_PATTERNS)


def big_drop_ratio(db: Session) -> float:
    return float((get_setting(db, "status_rules") or {}).get("big_drop_ratio", 0.10))


def signup_enabled(db: Session) -> bool:
    return bool((get_setting(db, "signup") or {}).get("enabled", False))
