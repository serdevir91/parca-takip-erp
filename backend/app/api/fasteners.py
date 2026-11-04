"""Bağlantı Elemanları: aggregated summary, raw rows, per-project order settings and recognition rules."""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.fastener import _TPL, FastenerMatch, validate_rule
from ..models import FastenerRule, FastenerSetting, User
from ..services import audit, bomimport
from ..services.settings import fastener_matcher
from ..services.state import FASTENER_COLORS, FASTENER_ORDER_STATUSES, ProjectView
from ..permissions import require
from .deps import admin, get_db, project_or_404

fasteners_view, fasteners_edit = require("fasteners", "view"), require("fasteners", "edit")

router = APIRouter(tags=["fasteners"])

SETTING_FIELDS = ("spare_pct", "supplier", "unit", "unit_price", "order_status", "note", "hidden")
TEMPLATE_FIELDS = ("desc", "std", "size", "d", "l")


class SettingsIn(BaseModel):
    keys: list[str] = Field(min_length=1)
    spare_pct: float | None = Field(None, ge=0, le=1000)
    supplier: str | None = None
    unit: str | None = None
    unit_price: float | None = Field(None, ge=0)
    clear_price: bool = False
    order_status: str | None = None
    note: str | None = None
    hidden: bool | None = None


class RuleIn(BaseModel):
    name: str = Field(min_length=1)
    pattern: str = Field(min_length=1)
    type: str = Field(min_length=1)
    desc: str = ""
    std: str = ""
    size: str = ""
    d: str = ""
    l: str = ""
    maps: dict[str, dict[str, str]] = Field(default_factory=dict)
    priority: int = 100
    active: bool = True


class ReorderIn(BaseModel):
    ids: list[int]


class TestIn(BaseModel):
    text: str
    rule: RuleIn | None = None


def _match_out(m: FastenerMatch | None) -> dict[str, Any] | None:
    if m is None:
        return None
    return {"type": m.type, "desc": m.desc, "std": m.std, "size": m.size, "d": m.d, "l": m.l,
            "key": m.key, "rule": m.rule, "orig": m.orig}


def rule_out(r: FastenerRule) -> dict[str, Any]:
    return {"id": r.id, "name": r.name, "pattern": r.pattern, "type": r.type, "desc": r.desc, "std": r.std,
            "size": r.size, "d": r.d, "l": r.l, "maps": r.maps or {}, "priority": r.priority, "active": r.active}


def check_rule(body: RuleIn) -> dict[str, Any]:
    """Regex must compile and every {n|map} template must point at an existing group and map."""
    rule = body.model_dump()
    ok, msg, _ = validate_rule(rule)
    if not ok:
        raise HTTPException(400, msg)
    groups = re.compile(body.pattern).groups
    for f in TEMPLATE_FIELDS:
        for mm in _TPL.finditer(rule[f] or ""):
            if int(mm.group(1)) > groups:
                raise HTTPException(400, f"'{f}' alanındaki {{{mm.group(1)}}} grubu desende yok "
                                         f"(desende {groups} grup var)")
            if mm.group(2) and mm.group(2) not in body.maps:
                raise HTTPException(400, f"'{f}' alanındaki '{mm.group(2)}' eşleme tablosu tanımlı değil")
    return rule


# ---------- project views ----------
@router.get("/projects/{pid}/fasteners")
def summary(pid: int, db: Session = Depends(get_db), user: User = Depends(fasteners_view)) -> dict[str, Any]:
    """Unique fasteners (type, std, size) with spare and order quantities."""
    view = ProjectView.load(db, project_or_404(db, pid))
    items = view.fasteners()
    prices = [i["total_price"] for i in items if i["total_price"] is not None]
    return {
        "items": items, "statuses": FASTENER_ORDER_STATUSES, "colors": FASTENER_COLORS,
        "totals": {"unique": len(items), "total_qty": sum(i["total_qty"] for i in items),
                   "order_qty": sum(i["order_qty"] for i in items),
                   "total_price": round(sum(prices), 2) if prices else None,
                   "by_status": {s: sum(1 for i in items if i["order_status"] == s) for s in FASTENER_ORDER_STATUSES}},
    }


@router.get("/projects/{pid}/fasteners/rows")
def rows(pid: int, db: Session = Depends(get_db), user: User = Depends(fasteners_view)) -> list[dict[str, Any]]:
    """Every fastener BOM row, including those inside purchased assemblies (not counted)."""
    return ProjectView.load(db, project_or_404(db, pid)).fastener_rows()


@router.get("/projects/{pid}/fasteners/settings")
def get_settings_(pid: int, db: Session = Depends(get_db), user: User = Depends(fasteners_view)) -> list[dict[str, Any]]:
    project_or_404(db, pid)
    return [{"key": s.key, **{f: getattr(s, f) for f in SETTING_FIELDS}}
            for s in db.scalars(select(FastenerSetting).where(FastenerSetting.project_id == pid)
                                .order_by(FastenerSetting.key))]


@router.put("/projects/{pid}/fasteners/settings")
def put_settings(pid: int, body: SettingsIn, db: Session = Depends(get_db),
                 user: User = Depends(fasteners_edit)) -> dict[str, Any]:
    """Set spare %, supplier, unit, price, order status or note for one or more fastener keys."""
    view = ProjectView.load(db, project_or_404(db, pid))
    known = {r.fastener_key for r in view.rows if r.fastener_key}
    unknown = [k for k in body.keys if k not in known]
    if unknown:
        raise HTTPException(400, f"Bağlantı elemanı bulunamadı: {', '.join(unknown[:5])}")
    if body.order_status is not None and body.order_status not in FASTENER_ORDER_STATUSES:
        raise HTTPException(400, f"Geçersiz sipariş durumu. Seçenekler: {', '.join(FASTENER_ORDER_STATUSES)}")
    changes: dict[str, Any] = {}
    for f in SETTING_FIELDS:
        v = getattr(body, f)
        if v is not None:
            changes[f] = v.strip() if isinstance(v, str) and f != "note" else v
    if body.clear_price:
        changes["unit_price"] = None
    if not changes:
        raise HTTPException(400, "Değiştirilecek alan yok")
    if "unit" in changes and not changes["unit"]:
        raise HTTPException(400, "Birim boş olamaz")
    n = 0
    for key in dict.fromkeys(body.keys):
        s = view.fastener_settings.get(key)
        if s is None:
            s = FastenerSetting(project_id=pid, key=key, spare_pct=view.fastener_defaults["spare_pct"], supplier="",
                                unit=view.fastener_defaults["unit"],
                                unit_price=None, order_status=FASTENER_ORDER_STATUSES[0], note="")
            db.add(s)
            db.flush()
            view.fastener_settings[key] = s
        n += audit.record_changes(db, user, s, changes, "fastener", key, pid)
    db.commit()
    keys = set(body.keys)
    return {"changed": n, "items": [i for i in view.fasteners() if i["key"] in keys]}


# ---------- rules (admin) ----------
@router.get("/fastener-rules")
def list_rules(db: Session = Depends(get_db), user: User = Depends(fasteners_view)) -> list[dict[str, Any]]:
    return [rule_out(r) for r in db.scalars(select(FastenerRule).order_by(FastenerRule.priority, FastenerRule.id))]


@router.post("/fastener-rules", status_code=201)
def create_rule(body: RuleIn, db: Session = Depends(get_db), user: User = Depends(admin)) -> dict[str, Any]:
    r = FastenerRule(**check_rule(body))
    db.add(r)
    db.flush()
    audit.record(db, user, "fastener_rule", r.id, "pattern", None, r.pattern, action="create")
    bomimport.retag_fasteners(db)
    db.commit()
    return rule_out(r)


@router.put("/fastener-rules/{rid}")
def update_rule(rid: int, body: RuleIn, db: Session = Depends(get_db), user: User = Depends(admin)) -> dict[str, Any]:
    r = db.get(FastenerRule, rid)
    if r is None:
        raise HTTPException(404, "Kural bulunamadı")
    audit.record_changes(db, user, r, check_rule(body), "fastener_rule", r.id)
    bomimport.retag_fasteners(db)
    db.commit()
    return rule_out(r)


@router.delete("/fastener-rules/{rid}")
def delete_rule(rid: int, db: Session = Depends(get_db), user: User = Depends(admin)) -> dict[str, Any]:
    r = db.get(FastenerRule, rid)
    if r is None:
        raise HTTPException(404, "Kural bulunamadı")
    audit.record(db, user, "fastener_rule", r.id, "name", r.name, None, action="delete")
    db.delete(r)
    bomimport.retag_fasteners(db)
    db.commit()
    return {"deleted": True}


@router.post("/fastener-rules/reorder")
def reorder(body: ReorderIn, db: Session = Depends(get_db), user: User = Depends(admin)) -> list[dict[str, Any]]:
    """Set priorities 10, 20, 30… in the given order (lower runs first)."""
    rules = {r.id: r for r in db.scalars(select(FastenerRule))}
    missing = [i for i in body.ids if i not in rules]
    if missing:
        raise HTTPException(400, f"Kural bulunamadı: {', '.join(map(str, missing))}")
    for n, rid in enumerate(dict.fromkeys(body.ids), 1):
        audit.record_changes(db, user, rules[rid], {"priority": n * 10}, "fastener_rule", rid)
    bomimport.retag_fasteners(db)
    db.commit()
    return list_rules(db, user)


@router.post("/fastener-rules/test")
def test_text(body: TestIn, db: Session = Depends(get_db), user: User = Depends(fasteners_view)) -> dict[str, Any]:
    """Run each line of `text` through one draft rule or the saved rule set."""
    lines = [ln.strip() for ln in body.text.splitlines() if ln.strip()]
    if not lines:
        raise HTTPException(400, "Test metni boş")
    results = []
    if body.rule is not None:
        rule = check_rule(body.rule)
        for ln in lines:
            _, _, m = validate_rule(rule, ln)
            results.append({"text": ln, "match": _match_out(m)})
    else:
        matcher = fastener_matcher(db)
        results = [{"text": ln, "match": _match_out(matcher.match(ln))} for ln in lines]
    return {"results": results, "matched": sum(1 for r in results if r["match"]), "total": len(results)}
