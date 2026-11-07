"""Montaj föyü and montaj hazırlık: plans, documents, field feedback and the quantities behind them."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core import assembly as core
from ..models import AssemblyExtra, AssemblyPlan, AuditLog, Photo, Project, User
from ..permissions import require
from ..services import assembly as svc
from ..services import assembly_excel, assembly_pdf, audit, conflict, discovery, uploads
from .deps import get_db, project_or_404
from app.core.i18n import tx

router = APIRouter(prefix="/projects", tags=["assembly"])
view_level, edit_level = require("assembly", "view"), require("assembly", "edit")
MAX_RETURN_MB = 20
MAX_PHOTO_MB = 25
PHOTO_ENTITY = "assembly"


class ItemIn(BaseModel):
    part_no: str = Field(min_length=1, max_length=200)
    qty: float = Field(gt=0, le=1_000_000)


class PlanIn(BaseModel):
    plan_date: date
    responsible: str = Field(default="", max_length=120)
    checker: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=4000)
    drawing_mode: Literal["none", "pages", "list", "both"] = "none"
    items: list[ItemIn] = Field(default_factory=list, max_length=500)
    rev: int | None = None


class ExtraIn(BaseModel):
    part_no: str = Field(min_length=1, max_length=200)
    qty: float = Field(gt=0, le=1_000_000)
    assembly_no: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=300)


class StatusIn(BaseModel):
    status: Literal["Taslak", "Yayınlandı", "Tamamlandı"]


class OpIn(BaseModel):
    item_id: int
    path: str = Field(max_length=1000)
    part_no: str = Field(max_length=200)
    state: Literal["ready", "run", "none"] | None = None
    ready_qty: float | None = Field(default=None, ge=0)
    mounted: bool | None = None


class StepIn(BaseModel):
    item_id: int
    path: str = Field(max_length=1000)
    done: bool


class FieldIn(BaseModel):
    ops: list[OpIn] = Field(default_factory=list, max_length=5000)
    steps: list[StepIn] = Field(default_factory=list, max_length=2000)


class QuantityIn(BaseModel):
    part_no: str = Field(min_length=1, max_length=200)
    ready_qty: float = Field(ge=0, le=100_000_000)


class QuantitiesIn(BaseModel):
    items: list[QuantityIn] = Field(min_length=1, max_length=5000)


class ChangeIn(BaseModel):
    type: Literal["ready", "state", "mounted", "step", "extra"]
    part_no: str = Field(default="", max_length=200)
    item_id: int | None = None
    path: str = Field(default="", max_length=1000)
    new: Any = None
    qty: float | None = None


class ReturnIn(BaseModel):
    changes: list[ChangeIn] = Field(max_length=5000)


def _plan(db: Session, pid: int, plan_id: int) -> AssemblyPlan:
    plan = db.get(AssemblyPlan, plan_id)
    if plan is None or plan.project_id != pid:
        raise HTTPException(404, tx("Montaj planı bulunamadı"))
    return plan


def _needs_bom(project: Project) -> None:
    if project.current_version_id is None:
        raise HTTPException(409, tx("Önce onaylı bir BOM yükleyin"))


def _fill(db: Session, plan: AssemblyPlan, body: PlanIn, cat: dict[str, core.Part]) -> None:
    plan.plan_date, plan.responsible, plan.checker = body.plan_date, body.responsible.strip(), body.checker.strip()
    plan.notes, plan.drawing_mode = body.notes, body.drawing_mode
    svc.set_items(db, plan, [(i.part_no.strip(), i.qty) for i in body.items], cat)


@router.get("/{pid}/assembly/plans")
def list_plans(pid: int, db: Session = Depends(get_db), _: User = Depends(view_level)) -> dict:
    project = project_or_404(db, pid)
    plans = list(db.scalars(select(AssemblyPlan).where(AssemblyPlan.project_id == pid).order_by(AssemblyPlan.no.desc())))
    if project.current_version_id is None:
        return {"rows": [svc.plan_out(p) for p in plans]}
    drafts = [p for p in plans if p.status != core.PUBLISHED]
    ctx = svc.context(db, project)
    rows = {p.id: svc.plan_out(p, ctx.docs[p.id]) for p in ctx.plans}
    for p in drafts:
        one = svc.context(db, project, p) if p.status == core.DRAFT else None
        rows[p.id] = svc.plan_out(p, one.docs[p.id] if one else None)
    return {"rows": [rows[p.id] for p in plans]}


@router.get("/{pid}/assembly/candidates")
def list_candidates(pid: int, db: Session = Depends(get_db), _: User = Depends(view_level)) -> dict:
    project = project_or_404(db, pid)
    _needs_bom(project)
    ctx = svc.context(db, project)
    return {"rows": svc.candidates(db, project), "lone": svc.lone_parts(ctx.view)}


@router.post("/{pid}/assembly/plans")
def create_plan(pid: int, body: PlanIn, db: Session = Depends(get_db), user: User = Depends(edit_level)) -> dict:
    project = project_or_404(db, pid)
    _needs_bom(project)
    if not body.items:
        raise HTTPException(400, tx("Plana en az bir montaj ekleyin"))
    ctx = svc.context(db, project)
    plan = AssemblyPlan(project_id=pid, no=svc.next_no(db, pid), plan_date=body.plan_date, status=core.DRAFT, created_by=user.username)
    db.add(plan)
    _fill(db, plan, body, ctx.cat)
    db.flush()
    audit.record(db, user, "assembly_plan", plan.id, "Plan oluşturuldu", None, f"plan {plan.no}", pid, action="create")
    db.commit()
    return svc.plan_out(plan)


@router.get("/{pid}/assembly/plans/{plan_id}")
def get_plan(pid: int, plan_id: int, db: Session = Depends(get_db), _: User = Depends(view_level)) -> dict:
    project = project_or_404(db, pid)
    _needs_bom(project)
    plan = _plan(db, pid, plan_id)
    ctx = svc.context(db, project, plan)
    doc = ctx.docs[plan.id]
    return {**svc.plan_out(plan, doc), **svc.doc_out(ctx, doc), "photos": _photos(db, plan)}


@router.put("/{pid}/assembly/plans/{plan_id}")
def update_plan(pid: int, plan_id: int, body: PlanIn, db: Session = Depends(get_db), user: User = Depends(edit_level)) -> dict:
    project = project_or_404(db, pid)
    _needs_bom(project)
    plan = _plan(db, pid, plan_id)
    if plan.status == core.DONE:
        raise HTTPException(409, tx("Tamamlanan plan değiştirilemez"))
    conflict.claim(db, plan, body.rev, user)
    _fill(db, plan, body, svc.context(db, project, plan).cat)
    audit.record(db, user, "assembly_plan", plan.id, "Plan güncellendi", None, ", ".join(f"{i.part_no} × {core.n(i.qty)}" for i in plan.items)[:900], pid)
    db.commit()
    return svc.plan_out(plan)


@router.delete("/{pid}/assembly/plans/{plan_id}")
def delete_plan(pid: int, plan_id: int, db: Session = Depends(get_db), user: User = Depends(edit_level)) -> dict:
    plan = _plan(db, pid, plan_id)
    if plan.status != core.DRAFT:
        raise HTTPException(409, tx("Yalnızca taslak plan silinebilir"))
    audit.record(db, user, "assembly_plan", plan.id, "Plan silindi", f"plan {plan.no}", None, pid, action="delete")
    paths = _drop_photos(db, plan)
    db.delete(plan)
    db.commit()
    uploads.remove(*paths)
    return {"ok": True}


@router.post("/{pid}/assembly/plans/{plan_id}/status")
def set_status(pid: int, plan_id: int, body: StatusIn, db: Session = Depends(get_db), user: User = Depends(edit_level)) -> dict:
    plan = _plan(db, pid, plan_id)
    if body.status == plan.status:
        return svc.plan_out(plan)
    if body.status == core.DRAFT and plan.marks:
        raise HTTPException(409, tx("Sahadan işaret alınmış plan taslağa dönemez"))
    if body.status == core.PUBLISHED and not plan.items:
        raise HTTPException(400, tx("Plana en az bir montaj ekleyin"))
    audit.record(db, user, "assembly_plan", plan.id, "Durum", plan.status, body.status, pid)
    if body.status == core.PUBLISHED and plan.status == core.DRAFT:
        plan.published_at = datetime.now(timezone.utc)
    plan.status = body.status
    db.commit()
    return svc.plan_out(plan)


@router.post("/{pid}/assembly/plans/{plan_id}/extras")
def add_extra(pid: int, plan_id: int, body: ExtraIn, db: Session = Depends(get_db), user: User = Depends(edit_level)) -> dict:
    plan = _plan(db, pid, plan_id)
    if plan.status == core.DONE:
        raise HTTPException(409, tx("Tamamlanan plan değiştirilemez"))
    e = AssemblyExtra(plan_id=plan.id, part_no=body.part_no.strip(), qty=body.qty, assembly_no=body.assembly_no.strip(), note=body.note)
    plan.extras.append(e)
    audit.record(db, user, "assembly_plan", plan.id, f"{e.part_no}: ek adet", None, core.n(e.qty), pid)
    db.commit()
    return {"id": e.id}


@router.put("/{pid}/assembly/plans/{plan_id}/extras/{extra_id}")
def update_extra(pid: int, plan_id: int, extra_id: int, body: ExtraIn, db: Session = Depends(get_db), user: User = Depends(edit_level)) -> dict:
    plan = _plan(db, pid, plan_id)
    e = next((x for x in plan.extras if x.id == extra_id), None)
    if e is None:
        raise HTTPException(404, tx("Ek adet bulunamadı"))
    audit.record(db, user, "assembly_plan", plan.id, "ek adet", f"{e.part_no} +{core.n(e.qty)}", f"{body.part_no} +{core.n(body.qty)}", pid)
    e.part_no, e.qty, e.assembly_no, e.note = body.part_no.strip(), body.qty, body.assembly_no.strip(), body.note
    db.commit()
    return {"ok": True}


@router.delete("/{pid}/assembly/plans/{plan_id}/extras/{extra_id}")
def delete_extra(pid: int, plan_id: int, extra_id: int, db: Session = Depends(get_db), user: User = Depends(edit_level)) -> dict:
    plan = _plan(db, pid, plan_id)
    e = next((x for x in plan.extras if x.id == extra_id), None)
    if e is None:
        raise HTTPException(404, tx("Ek adet bulunamadı"))
    audit.record(db, user, "assembly_plan", plan.id, "ek adet", f"{e.part_no} +{core.n(e.qty)}", None, pid, action="delete")
    plan.extras.remove(e)
    db.commit()
    return {"ok": True}


@router.get("/{pid}/assembly/plans/{plan_id}/history")
def history(pid: int, plan_id: int, db: Session = Depends(get_db), _: User = Depends(view_level)) -> dict:
    _plan(db, pid, plan_id)
    logs = db.scalars(select(AuditLog).where(AuditLog.entity == "assembly_plan", AuditLog.entity_id == str(plan_id),
                                             AuditLog.project_id == pid).order_by(AuditLog.id.desc()).limit(500))
    return {"rows": [{"id": a.id, "ts": a.ts.isoformat(), "username": a.username, "field": a.field, "old": a.old, "new": a.new}
                     for a in logs]}


# ---------- documents ----------

def _base_url(request: Request) -> str:
    """QR codes are read by a phone, so a loopback address is swapped for the LAN one."""
    base = str(request.base_url).rstrip("/")
    if request.url.hostname in ("127.0.0.1", "localhost", "::1"):
        ips = discovery.lan_ipv4()
        if ips:
            return f"{request.url.scheme}://{ips[0]}" + (f":{request.url.port}" if request.url.port else "")
    return base


def _attachment(data: bytes, media: str, name: str) -> Response:
    return Response(data, media_type=media, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@router.get("/{pid}/assembly/plans/{plan_id}/pdf")
def plan_pdf(pid: int, plan_id: int, request: Request, foy: str | None = None, db: Session = Depends(get_db),
             _: User = Depends(view_level)) -> Response:
    project = project_or_404(db, pid)
    _needs_bom(project)
    plan = _plan(db, pid, plan_id)
    ctx = svc.context(db, project, plan)
    doc = ctx.docs[plan.id]
    if foy is not None and doc.foy(foy) is None:
        raise HTTPException(404, tx("Föy bulunamadı"))
    data = assembly_pdf.build(ctx, plan, doc, _base_url(request), foy)
    return _attachment(data, "application/pdf", f"montaj_plani_{plan.no}{'_' + foy if foy else ''}.pdf")


@router.get("/{pid}/assembly/plans/{plan_id}/excel")
def plan_excel(pid: int, plan_id: int, db: Session = Depends(get_db), _: User = Depends(view_level)) -> Response:
    project = project_or_404(db, pid)
    _needs_bom(project)
    plan = _plan(db, pid, plan_id)
    ctx = svc.context(db, project, plan)
    return _attachment(assembly_excel.build(ctx, plan, ctx.docs[plan.id]),
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"montaj_plani_{plan.no}.xlsx")


# ---------- field feedback ----------

@router.post("/{pid}/assembly/plans/{plan_id}/field")
def save_field(pid: int, plan_id: int, body: FieldIn, db: Session = Depends(get_db), user: User = Depends(edit_level)) -> dict:
    project = project_or_404(db, pid)
    _needs_bom(project)
    plan = _plan(db, pid, plan_id)
    if plan.status == core.DRAFT:
        raise HTTPException(409, tx("Önce planı yayınlayın"))
    ctx = svc.context(db, project, plan)
    n = svc.apply_field(db, user, ctx, plan, [o.model_dump() for o in body.ops], [s.model_dump() for s in body.steps], svc.SOURCE_SCREEN)
    db.commit()
    return {"changed": n, "status": plan.status}


@router.post("/{pid}/assembly/plans/{plan_id}/return/preview")
async def return_preview(pid: int, plan_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                         _: User = Depends(edit_level)) -> dict:
    project = project_or_404(db, pid)
    _needs_bom(project)
    plan = _plan(db, pid, plan_id)
    data = await file.read(MAX_RETURN_MB * 1024 * 1024 + 1)
    if len(data) > MAX_RETURN_MB * 1024 * 1024:
        raise HTTPException(413, tx("Dosya {0} MB sınırını aşıyor", MAX_RETURN_MB))
    ctx = svc.context(db, project, plan)
    doc = ctx.docs[plan.id]
    back = assembly_excel.read_back(data, plan, doc)
    return {"changes": back.changes, "issues": core.check(back.sheet, doc, ctx.cat)}


@router.post("/{pid}/assembly/plans/{plan_id}/return/apply")
def return_apply(pid: int, plan_id: int, body: ReturnIn, db: Session = Depends(get_db), user: User = Depends(edit_level)) -> dict:
    project = project_or_404(db, pid)
    _needs_bom(project)
    plan = _plan(db, pid, plan_id)
    if plan.status == core.DRAFT:
        raise HTTPException(409, tx("Önce planı yayınlayın"))
    ctx = svc.context(db, project, plan)
    doc = ctx.docs[plan.id]
    ops: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    for c in body.changes:
        if c.type == "extra":
            if not c.qty or c.qty <= 0:
                raise HTTPException(400, tx("Miktar sıfırdan büyük olmalı"))
            plan.extras.append(AssemblyExtra(plan_id=plan.id, part_no=c.part_no, qty=c.qty, note="Excel"))
            audit.record(db, user, "assembly_plan", plan.id, f"{c.part_no}: ek adet", None, f"{core.n(c.qty)} (Excel, plan {plan.no})", pid)
        elif c.type == "ready":
            pick = doc.pick(c.part_no)
            if pick is None or not isinstance(c.new, (int, float)) or c.new < 0:
                raise HTTPException(400, tx("Föyde bu satır yok: {0}", c.part_no))
            base = ctx.ready(c.part_no)
            svc.set_ready(db, user, ctx, plan, c.part_no, base + c.new - pick.ready, svc.SOURCE_EXCEL)
        elif c.type == "state":
            if c.item_id is None or c.new not in (core.READY, core.RUNNING, core.MISSING):
                raise HTTPException(400, tx("Geçersiz durum"))
            ops.append({"item_id": c.item_id, "path": c.path, "part_no": c.part_no, "state": c.new})
        elif c.type == "mounted":
            ops.append({"item_id": c.item_id, "path": c.path, "part_no": c.part_no, "mounted": bool(c.new)})
        else:
            steps.append({"item_id": c.item_id, "path": c.path, "done": bool(c.new)})
    n = svc.apply_field(db, user, ctx, plan, ops, steps, svc.SOURCE_EXCEL)
    db.commit()
    return {"changed": n + sum(1 for c in body.changes if c.type in ("ready", "extra"))}


# ---------- photos of filled-in sheets ----------

def _photos(db: Session, plan: AssemblyPlan) -> list[dict[str, Any]]:
    rows = db.scalars(select(Photo).where(Photo.entity == PHOTO_ENTITY, Photo.entity_key == str(plan.id)).order_by(Photo.id))
    return [{"id": p.id, "filename": p.filename, "uploaded_by": p.uploaded_by} for p in rows]


def _drop_photos(db: Session, plan: AssemblyPlan) -> list[str | None]:
    rows = db.scalars(select(Photo).where(Photo.entity == PHOTO_ENTITY, Photo.entity_key == str(plan.id))).all()
    paths = [p.storage_path for p in rows]
    for p in rows:
        db.delete(p)
    return paths


@router.post("/{pid}/assembly/plans/{plan_id}/photos")
async def add_photo(pid: int, plan_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                    user: User = Depends(edit_level)) -> dict:
    """The photo is kept next to the field screen to read from. Nothing is read out of it automatically."""
    plan = _plan(db, pid, plan_id)
    name = uploads.safe_name(file.filename, "foy.jpg")
    if not uploads.is_image(name, file.content_type):
        raise HTTPException(400, tx("{0}: yalnızca resim dosyası yüklenebilir (JPG, PNG, WEBP, HEIC…)", name))
    try:
        path, size = await uploads.store(file, get_settings().photo_dir, MAX_PHOTO_MB)
    except uploads.UploadTooLarge as e:
        raise HTTPException(413, str(e)) from e
    p = Photo(entity=PHOTO_ENTITY, entity_key=str(plan.id), filename=name, content_type=file.content_type or "", size=size,
              storage_path=str(path), uploaded_by=user.username)
    db.add(p)
    audit.record(db, user, "assembly_plan", plan.id, "fotoğraf", None, f"{name} (fotoğraf, plan {plan.no})", pid)
    db.commit()
    return {"id": p.id}


@router.get("/{pid}/assembly/plans/{plan_id}/photos/{photo_id}")
def get_photo(pid: int, plan_id: int, photo_id: int, db: Session = Depends(get_db), _: User = Depends(view_level)) -> Response:
    plan = _plan(db, pid, plan_id)
    p = db.get(Photo, photo_id)
    if p is None or p.entity != PHOTO_ENTITY or p.entity_key != str(plan.id) or not Path(p.storage_path).exists():
        raise HTTPException(404, tx("Fotoğraf bulunamadı"))
    media, _inline = uploads.media_for(p.filename)
    return FileResponse(p.storage_path, media_type=media)


# ---------- quantities and dashboard ----------

@router.get("/{pid}/assembly/quantities")
def quantities(pid: int, db: Session = Depends(get_db), _: User = Depends(view_level)) -> dict:
    project = project_or_404(db, pid)
    _needs_bom(project)
    ctx = svc.context(db, project)
    return {"rows": svc.quantities_out(ctx), "convert": svc.convert_preview(ctx)}


@router.post("/{pid}/assembly/quantities")
def save_quantities(pid: int, body: QuantitiesIn, db: Session = Depends(get_db), user: User = Depends(edit_level)) -> dict:
    project = project_or_404(db, pid)
    _needs_bom(project)
    ctx = svc.context(db, project)
    for i in body.items:
        if i.part_no not in ctx.cat:
            raise HTTPException(400, tx("{0} güncel BOM'da yok", i.part_no))
        svc.set_ready(db, user, ctx, None, i.part_no, i.ready_qty, svc.SOURCE_SCREEN)
    db.commit()
    return {"ok": True}


@router.post("/{pid}/assembly/quantities/convert")
def convert_quantities(pid: int, db: Session = Depends(get_db), user: User = Depends(edit_level)) -> dict:
    project = project_or_404(db, pid)
    _needs_bom(project)
    n = svc.convert(db, user, svc.context(db, project))
    db.commit()
    return {"converted": n}


@router.get("/{pid}/assembly/summary")
def assembly_summary(pid: int, db: Session = Depends(get_db), _: User = Depends(view_level)) -> dict:
    project = project_or_404(db, pid)
    if project.current_version_id is None:
        return {"ready": [], "blocking": [], "planned": 0, "completed": 0}
    return svc.summary(db, svc.context(db, project))
