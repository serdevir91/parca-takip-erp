"""External status list (T-35 Güncel Durumu) import: preview, apply and rule config (spec 6)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core import t35 as t35core
from ..core.status import PROG_DONE, PROGRESS_CHOICES
from ..models import Tracking, User
from ..services import audit
from ..services.settings import get_setting, set_setting, t35_config
from ..services.state import ProjectView
from ..services.tracking import apply_changes, clean_changes, material_status_choices, read_upload_sync
from ..permissions import require
from .deps import admin, get_db, project_or_404
from app.core.i18n import tx

control_view, control_edit = require("control", "view"), require("control", "edit")

router = APIRouter(tags=["t35"])

APPLY_FIELDS = ("progress", "manufacturer", "material_status", "t35_note")
RULE_FIELDS = ("progress", "material_status")


class ApplyItem(BaseModel):
    part_no: str
    progress: str | None = None
    manufacturer: str | None = None
    material_status: str | None = None
    t35_note: str | None = None


class ApplyIn(BaseModel):
    items: list[ApplyItem] = Field(default_factory=list)


class RuleIn(BaseModel):
    field: str
    all: list[str]
    value: str
    priority: int = 100
    active: bool = True


class ConfigIn(BaseModel):
    rules: list[RuleIn]
    default_progress: str = t35core.DEFAULT_PROGRESS
    skip_note: list[str] = Field(default_factory=list)


def proposed_note(note: str | None, marked: bool) -> str | None:
    """T-35 note text written to tracking; None means "leave as is"."""
    parts = [p for p in (note, t35core.MARK_NOTE if marked else None) if p]
    return " | ".join(parts) if parts else None


def _bom_parts(view: ProjectView) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    parts = {p["part_no"]: p for p in view.parts(include_in_purchased=False)}
    bom = {pno: {"rev": p["rev"] or "", "total_qty": p["total_qty"], "produced": p["progress"] == PROG_DONE}
           for pno, p in parts.items()}
    return bom, parts


@router.post("/projects/{pid}/t35/preview")
def preview(pid: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                  user: User = Depends(control_edit)) -> dict[str, Any]:
    """Compare the uploaded list with the current BOM and propose tracking updates. Nothing is saved.

    Sync on purpose: openpyxl parsing and DB work run in the threadpool, not on the event loop."""
    view = ProjectView.load(db, project_or_404(db, pid))
    if view.version is None:
        raise HTTPException(400, tx("Projede onaylı BOM yok"))
    data = read_upload_sync(file)
    try:
        rows = t35core.read_t35(data)
    except Exception as e:  # noqa: BLE001 - openpyxl raises many types for bad files
        raise HTTPException(400, tx("Excel dosyası okunamadı: {0}", e)) from e
    if not rows:
        raise HTTPException(400, tx("Listede parça satırı bulunamadı"))
    bom, parts = _bom_parts(view)
    pv = t35core.build_preview(rows, bom, t35_config(db), view.aliases)
    updates = []
    for u in pv.updates:
        cur = parts[u["part_no"]]
        proposed = {"progress": u["progress"], "manufacturer": u["manufacturer"],
                    "material_status": u["material_status"], "t35_note": proposed_note(u["note"], u["marked"])}
        changes = {f: {"old": cur.get(f) or "", "new": v} for f, v in proposed.items()
                   if v is not None and v != (cur.get(f) or "")}
        updates.append({**u, "proposed": proposed, "changes": changes, "changed": bool(changes),
                        "current": {f: cur.get(f) or "" for f in APPLY_FIELDS},
                        "status": cur["status"], "rev": cur["rev"]})
    return {
        "filename": file.filename, "rows": len(rows), "updates": updates,
        "only_in_bom": [{"part_no": p, "is_assembly": parts[p]["is_assembly"], "status": parts[p]["status"]}
                        for p in pv.only_in_bom],
        "only_in_list": pv.only_in_list, "rev_diff": pv.rev_diff, "qty_diff": pv.qty_diff,
        "counts": {"rows": len(rows), "matched": len(updates), "changed": sum(1 for u in updates if u["changed"]),
                   "only_in_bom": len(pv.only_in_bom), "only_in_list": len(pv.only_in_list),
                   "rev_diff": len(pv.rev_diff), "qty_diff": len(pv.qty_diff)},
    }


@router.post("/projects/{pid}/t35/apply")
def apply(pid: int, body: ApplyIn, db: Session = Depends(get_db), user: User = Depends(control_edit)) -> dict[str, Any]:
    """Write the selected preview changes to tracking (each field audited)."""
    project = project_or_404(db, pid)
    view = ProjectView.load(db, project)
    known = {p["part_no"] for p in view.parts(include_in_purchased=False)}
    applied, fields, errors = 0, 0, []
    for it in body.items:
        pno = view.aliases.get(it.part_no, it.part_no)
        if pno not in known:
            errors.append({"part_no": it.part_no, "error": tx("Parça güncel BOM'da yok")})
            continue
        raw = {f: getattr(it, f) for f in APPLY_FIELDS if getattr(it, f) is not None}
        if not raw:
            continue
        try:
            changes = clean_changes(db, raw)
        except HTTPException as e:
            errors.append({"part_no": pno, "error": e.detail})
            continue
        t = view.tracking.get(pno)
        if t is None:
            t = Tracking(project_id=project.id, part_no=pno)
            db.add(t)
            db.flush()
            view.tracking[pno] = t
        n = apply_changes(db, user, t, changes)
        if n:
            applied += 1
            fields += n
    if applied:
        audit.record(db, user, "t35", project.id, "apply", None, f"{applied} parça, {fields} alan", project.id,
                     action="import")
    db.commit()
    return {"applied": applied, "fields": fields, "errors": errors}


@router.get("/t35/config")
def get_config(db: Session = Depends(get_db), user: User = Depends(admin)) -> dict[str, Any]:
    cfg = t35_config(db)
    return {"rules": cfg.rules, "default_progress": cfg.default_progress, "skip_note": cfg.skip_note,
            "manufacturers": cfg.manufacturers, "fields": list(RULE_FIELDS),
            "progress_choices": PROGRESS_CHOICES, "material_status_choices": material_status_choices(db),
            "mark_note": t35core.MARK_NOTE}


@router.put("/t35/config")
def put_config(body: ConfigIn, db: Session = Depends(get_db), user: User = Depends(admin)) -> dict[str, Any]:
    """Replace the keyword rules, default progress and skipped note texts."""
    mats = material_status_choices(db)
    rules = []
    for i, r in enumerate(body.rules, 1):
        kws = [k.strip() for k in r.all if k and k.strip()]
        if r.field not in RULE_FIELDS:
            raise HTTPException(400, tx("Kural {0}: alan '{1}' geçersiz. Seçenekler: {2}", i, r.field, ', '.join(RULE_FIELDS)))
        if not kws:
            raise HTTPException(400, tx("Kural {0}: en az bir anahtar kelime gerekli", i))
        allowed = PROGRESS_CHOICES if r.field == "progress" else mats
        if r.value not in allowed:
            raise HTTPException(400, tx("Kural {0}: '{1}' geçersiz. Seçenekler: {2}", i, r.value, ', '.join(allowed)))
        rules.append({"field": r.field, "all": kws, "value": r.value, "priority": r.priority, "active": r.active})
    if body.default_progress not in PROGRESS_CHOICES:
        raise HTTPException(400, tx("Varsayılan ilerleme geçersiz. Seçenekler: {0}", ', '.join(PROGRESS_CHOICES)))
    old = get_setting(db, "t35")
    new = {"rules": rules, "default_progress": body.default_progress,
           "skip_note": [s.strip() for s in body.skip_note if s and s.strip()]}
    set_setting(db, "t35", new)
    audit.record(db, user, "setting", "t35", "value", old, new)
    db.commit()
    return get_config(db, user)
