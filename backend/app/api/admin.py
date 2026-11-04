"""Admin screen: users and roles, firms, business-rule settings, audit log and backups."""
from __future__ import annotations

import json
import os
import re
import signal
import tarfile
import threading
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import hash_password
from ..config import get_settings
from ..db import SessionLocal
from ..permissions import MODULES, catalog, clean_overrides, effective, require
from ..models import (ROLE_ADMIN, ROLE_LABELS, ROLES, AuditLog, Firm, Invoice, Part, Payment, PurchaseOrder, SalesOrder,
                      User)
from ..services import audit, backup as backup_svc, loginguard, maintenance, system, tls, uploads
from ..core.status import DEFAULT_TEMIN_TYPES, FIXED_TEMINS, KIND_HAZIR, KIND_IMALAT
from ..services.tracking import material_status_choices
from ..services.settings import (get_setting, part_no_patterns, purchased_assemblies, set_setting, temin_types,
                                 signup_enabled)
from .auth import _is_default_password, check_email, check_password_rules
from .deps import admin, get_db

contacts_view, contacts_edit = require("contacts", "view"), require("contacts", "edit")

router = APIRouter(prefix="/admin", tags=["admin"])
MAX_BACKUP_MB = 50_000

FIRM_KINDS = ("manufacturer", "supplier", "both", "customer")
FIRM_KIND_LABELS = {"manufacturer": "Üretici", "supplier": "Tedarikçi", "both": "Üretici + Tedarikçi",
                    "customer": "Müşteri"}
SETTING_KEYS = ("part_no_patterns", "purchased_assemblies", "status_rules", "signup", "material_status_choices",
                "temin_types", "system")



# ---------- users ----------
def user_out(u: User) -> dict[str, Any]:
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "email": u.email or "",
            "role": u.role, "role_label": ROLE_LABELS.get(u.role, u.role), "active": u.active,
            "pending": bool(u.pending), "created_at": u.created_at.isoformat() if u.created_at else None,
            "overrides": clean_overrides(u.permissions), "permissions": effective(u)}


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str
    full_name: str = ""
    email: str = ""
    role: str = "viewer"
    permissions: dict[str, str] | None = None


class UserUpdate(BaseModel):
    full_name: str | None = None
    email: str | None = None
    role: str | None = None
    active: bool | None = None
    permissions: dict[str, str] | None = None  # {} clears every override


class PasswordReset(BaseModel):
    password: str


def _check_role(role: str) -> None:
    if role not in ROLES:
        raise HTTPException(400, f"Geçersiz rol: {role}")


def _check_password(pw: str) -> None:
    check_password_rules(pw)


def _user_or_404(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Kullanıcı bulunamadı")
    return u


def _active_admins(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User)
                     .where(User.role == ROLE_ADMIN, User.active.is_(True))) or 0


def _guard_self(me: User, u: User, new_role: str, new_active: bool) -> None:
    """An admin must not lock themselves out (deactivate or demote their own account)."""
    if u.id == me.id and (not new_active or new_role != ROLE_ADMIN):
        raise HTTPException(400, "Kendi hesabınızı pasif yapamaz veya yönetici rolünü kaldıramazsınız")


def _guard_last_admin(db: Session, u: User, new_role: str, new_active: bool) -> None:
    losing = u.role == ROLE_ADMIN and u.active and (new_role != ROLE_ADMIN or not new_active)
    if losing and _active_admins(db) <= 1:
        raise HTTPException(400, "Son aktif yönetici pasif yapılamaz veya rolü değiştirilemez")


@router.get("/roles")
def list_roles(_: User = Depends(admin)) -> list[dict[str, str]]:
    return [{"value": r, "label": ROLE_LABELS[r]} for r in ROLES]


@router.get("/permissions")
def permission_catalog(_: User = Depends(admin)) -> dict:
    """Modules, levels and the role defaults for the permission matrix."""
    return catalog()


@router.get("/users")
def list_users(_: User = Depends(admin), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return [user_out(u) for u in db.scalars(select(User).order_by(User.pending.desc(), User.username))]


@router.get("/signups/count")
def signup_count(_: User = Depends(admin), db: Session = Depends(get_db)) -> dict[str, int]:
    """Sign-ups waiting for approval (badge on the Yönetim menu)."""
    return {"pending": db.scalar(select(func.count()).select_from(User).where(User.pending.is_(True))) or 0}


class ApproveIn(BaseModel):
    role: str = "viewer"
    permissions: dict[str, str] | None = None
    full_name: str | None = None


def _pending_or_404(db: Session, user_id: int) -> User:
    u = _user_or_404(db, user_id)
    if not u.pending:
        raise HTTPException(400, "Bu hesap onay beklemiyor")
    return u


@router.post("/users/{user_id}/approve")
def approve_signup(user_id: int, body: ApproveIn, me: User = Depends(admin),
                   db: Session = Depends(get_db)) -> dict[str, Any]:
    """Accept a sign-up: the account becomes active with the chosen role and permissions."""
    u = _pending_or_404(db, user_id)
    _check_role(body.role)
    if body.full_name is not None:
        u.full_name = body.full_name.strip()[:128]
    u.role, u.permissions = body.role, clean_overrides(body.permissions) or None
    u.pending, u.active = False, True
    audit.record(db, me, "user", u.id, "role", None, body.role, action="approve")
    db.commit()
    return user_out(u)


@router.delete("/users/{user_id}/signup")
def reject_signup(user_id: int, me: User = Depends(admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Refuse a sign-up: the request is removed (it never logged in), so the name can be used again."""
    u = _pending_or_404(db, user_id)
    audit.record(db, me, "user", u.id, "username", u.username, None, action="reject")
    db.delete(u)
    db.commit()
    return {"ok": True}


@router.post("/users", status_code=201)
def create_user(body: UserCreate, me: User = Depends(admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    username = body.username.strip()
    if not username:
        raise HTTPException(400, "Kullanıcı adı boş olamaz")
    _check_role(body.role)
    _check_password(body.password)
    if db.scalar(select(User).where(func.lower(User.username) == username.lower())):
        raise HTTPException(409, "Bu kullanıcı adı zaten var")
    u = User(username=username, full_name=body.full_name.strip(), email=check_email(body.email), role=body.role,
             password_hash=hash_password(body.password), active=True,
             permissions=clean_overrides(body.permissions) or None)
    db.add(u)
    db.flush()
    audit.record(db, me, "user", u.id, "username", None, username, action="create")
    audit.record(db, me, "user", u.id, "role", None, body.role, action="create")
    db.commit()
    return user_out(u)


@router.put("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, me: User = Depends(admin),
                db: Session = Depends(get_db)) -> dict[str, Any]:
    u = _user_or_404(db, user_id)
    changes: dict[str, Any] = {}
    if body.full_name is not None:
        changes["full_name"] = body.full_name.strip()
    if body.email is not None:
        changes["email"] = check_email(body.email)
    if body.role is not None:
        _check_role(body.role)
        changes["role"] = body.role
    if body.active is not None:
        changes["active"] = body.active
    if body.permissions is not None:
        changes["permissions"] = clean_overrides(body.permissions) or None
    _guard_self(me, u, changes.get("role", u.role), changes.get("active", u.active))
    _guard_last_admin(db, u, changes.get("role", u.role), changes.get("active", u.active))
    if changes.get("active") is False and u.active:
        u.token_version = (u.token_version or 0) + 1
    audit.record_changes(db, me, u, changes, "user", u.id)
    db.commit()
    return user_out(u)


@router.post("/users/{user_id}/password")
def reset_password(user_id: int, body: PasswordReset, me: User = Depends(admin),
                   db: Session = Depends(get_db)) -> dict[str, Any]:
    u = _user_or_404(db, user_id)
    _check_password(body.password)
    u.password_hash = hash_password(body.password)
    u.token_version = (u.token_version or 0) + 1
    audit.record(db, me, "user", u.id, "password", None, "sıfırlandı")
    db.commit()
    return {"ok": True}


@router.delete("/users/{user_id}")
def deactivate_user(user_id: int, me: User = Depends(admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Users are never deleted (audit log keeps their name); they are deactivated."""
    u = _user_or_404(db, user_id)
    _guard_self(me, u, u.role, False)
    _guard_last_admin(db, u, u.role, False)
    if u.active:
        u.token_version = (u.token_version or 0) + 1
    audit.record_changes(db, me, u, {"active": False}, "user", u.id)
    db.commit()
    return user_out(u)


# ---------- firms ----------
def firm_out(f: Firm) -> dict[str, Any]:
    return {"id": f.id, "name": f.name, "kind": f.kind, "kind_label": FIRM_KIND_LABELS.get(f.kind, f.kind),
            "contact": f.contact, "note": f.note, "active": f.active, "phone": f.phone, "email": f.email,
            "address": f.address, "tax_office": f.tax_office, "tax_no": f.tax_no, "lead_days": f.lead_days}


class FirmIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = "manufacturer"
    contact: str = ""
    note: str = ""
    active: bool = True
    phone: str = Field(default="", max_length=50)
    email: str = Field(default="", max_length=200)
    address: str = ""
    tax_office: str = Field(default="", max_length=100)
    tax_no: str = Field(default="", max_length=30)
    lead_days: int = Field(default=0, ge=0, le=3650)


class FirmUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: str | None = None
    contact: str | None = None
    note: str | None = None
    active: bool | None = None
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=200)
    address: str | None = None
    tax_office: str | None = Field(default=None, max_length=100)
    tax_no: str | None = Field(default=None, max_length=30)
    lead_days: int | None = Field(default=None, ge=0, le=3650)


def _check_kind(kind: str) -> None:
    if kind not in FIRM_KINDS:
        raise HTTPException(400, "Firma türü üretici, tedarikçi, ikisi birden veya müşteri olmalı")


def _firm_name_taken(db: Session, name: str, exclude_id: int | None = None) -> bool:
    key = name.casefold()
    return any(f.name.casefold() == key and f.id != exclude_id for f in db.scalars(select(Firm)))


def _firm_or_404(db: Session, firm_id: int) -> Firm:
    f = db.get(Firm, firm_id)
    if f is None:
        raise HTTPException(404, "Firma bulunamadı")
    return f


@router.get("/firms")
def list_firms(kind: str | None = None, _: User = Depends(contacts_view),
               db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    q = select(Firm).order_by(Firm.name)
    if kind:
        q = q.where(Firm.kind.in_([kind, "both"]) if kind != "both" else Firm.kind == "both")
    return [firm_out(f) for f in db.scalars(q)]


@router.post("/firms", status_code=201)
def create_firm(body: FirmIn, me: User = Depends(contacts_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Firma adı boş olamaz")
    _check_kind(body.kind)
    if _firm_name_taken(db, name):
        raise HTTPException(409, "Bu firma zaten var")
    f = Firm(**{**body.model_dump(), "name": name, "contact": body.contact.strip()})
    db.add(f)
    db.flush()
    audit.record(db, me, "firm", f.id, "name", None, name, action="create")
    db.commit()
    return firm_out(f)


@router.put("/firms/{firm_id}")
def update_firm(firm_id: int, body: FirmUpdate, me: User = Depends(contacts_edit),
                db: Session = Depends(get_db)) -> dict[str, Any]:
    f = _firm_or_404(db, firm_id)
    changes = body.model_dump(exclude_none=True)
    if "name" in changes:
        changes["name"] = changes["name"].strip()
        if not changes["name"]:
            raise HTTPException(400, "Firma adı boş olamaz")
        if _firm_name_taken(db, changes["name"], f.id):
            raise HTTPException(409, "Bu firma zaten var")
    if "kind" in changes:
        _check_kind(changes["kind"])
    audit.record_changes(db, me, f, changes, "firm", f.id)
    db.commit()
    return firm_out(f)


@router.delete("/firms/{firm_id}")
def delete_firm(firm_id: int, me: User = Depends(contacts_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Tracking rows keep the firm name as text, so deleting a firm loses no history."""
    f = _firm_or_404(db, firm_id)
    if any(db.scalar(select(m.id).where(m.firm_id == f.id).limit(1)) for m in (Invoice, Payment, PurchaseOrder, SalesOrder)):
        raise HTTPException(400, "Bu firmanın fatura, ödeme veya sipariş kaydı var. Silmek yerine pasife alın.")
    audit.record(db, me, "firm", f.id, "name", f.name, None, action="delete")
    db.delete(f)
    db.commit()
    return {"ok": True}


# ---------- settings ----------
def _settings_out(db: Session) -> dict[str, Any]:
    return {"part_no_patterns": part_no_patterns(db),
            "purchased_assemblies": sorted(purchased_assemblies(db)),
            "status_rules": get_setting(db, "status_rules") or {"big_drop_ratio": 0.10},
            "signup": {"enabled": signup_enabled(db)},
            "material_status_choices": material_status_choices(db),
            "temin_types": temin_types(db),
            "system": system.system(db),
            "modules": [{"key": k, "label": label, "locked": k in system.ALWAYS_ON} for k, label, _ in MODULES]}


class SettingIn(BaseModel):
    value: Any


def _clean_str_list(v: Any, what: str) -> list[str]:
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise HTTPException(400, f"{what} bir metin listesi olmalı")
    out: list[str] = []
    for x in (s.strip() for s in v):
        if x and x not in out:
            out.append(x)
    return out


def _clean_temin_types(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise HTTPException(400, "Temin şekilleri bir liste olmalı")
    fixed = {t["name"]: t for t in DEFAULT_TEMIN_TYPES if t["name"] in FIXED_TEMINS}
    out: dict[str, dict[str, Any]] = {}
    for t in value:
        name = str((t or {}).get("name") or "").strip() if isinstance(t, dict) else ""
        if not name or len(name) > 64:
            raise HTTPException(400, "Temin şekli adı boş olamaz ve 64 karakteri geçemez")
        if name in out:
            raise HTTPException(400, f"Aynı temin şekli iki kez yazılmış: {name}")
        if t.get("kind") not in (KIND_IMALAT, KIND_HAZIR) and name not in fixed:
            raise HTTPException(400, f"{name}: davranış İmalat veya Hazır Alım olmalı")
        # The fixed types keep their meaning; only their settings for drawing and planning change
        out[name] = {"name": name, "kind": fixed[name]["kind"] if name in fixed else t["kind"],
                     "drawing": bool(t.get("drawing")), "order": bool(t.get("order"))}
    missing = [n for n in fixed if n not in out]
    if missing:
        raise HTTPException(400, f"Bu temin şekilleri silinemez: {', '.join(missing)}")
    return list(out.values())


def _validate_setting(key: str, value: Any) -> Any:
    if key == "temin_types":
        return _clean_temin_types(value)
    if key == "part_no_patterns":
        pats = _clean_str_list(value, "Parça numarası desenleri")
        if not pats:
            raise HTTPException(400, "En az bir parça numarası deseni gerekli")
        for p in pats:
            try:
                re.compile(p)
            except re.error as e:
                raise HTTPException(400, f"Geçersiz desen '{p}': {e}") from e
        return pats
    if key == "purchased_assemblies":
        return sorted(_clean_str_list(value, "Satın alınan montaj listesi"))
    if key == "system":
        return system.clean(value)
    if key == "material_status_choices":
        choices = _clean_str_list(value, "Malzeme durumları")
        if not choices:
            raise HTTPException(400, "En az bir malzeme durumu gerekli")
        return choices
    if key == "signup":
        if not isinstance(value, dict):
            raise HTTPException(400, "Hesap oluşturma ayarı bir nesne olmalı")
        return {"enabled": bool(value.get("enabled", False))}
    if key == "status_rules":
        if not isinstance(value, dict):
            raise HTTPException(400, "Durum kuralları bir nesne olmalı")
        out = dict(value)
        try:
            ratio = float(out.get("big_drop_ratio", 0.10))
        except (TypeError, ValueError) as e:
            raise HTTPException(400, "big_drop_ratio sayı olmalı") from e
        if not 0 < ratio <= 1:
            raise HTTPException(400, "big_drop_ratio 0 ile 1 arasında olmalı")
        out["big_drop_ratio"] = ratio
        return out
    raise HTTPException(404, f"Bilinmeyen ayar: {key}")


def _mirror_purchased(db: Session, wanted: list[str]) -> None:
    """Part.is_purchased_assembly is the source the BOM parser reads; keep it in sync."""
    want = set(wanted)
    for p in db.scalars(select(Part).where(Part.is_purchased_assembly.is_(True))):
        if p.part_no not in want:
            p.is_purchased_assembly = False
    existing = {p.part_no: p for p in db.scalars(select(Part).where(Part.part_no.in_(want)))} if want else {}
    for pno in wanted:
        p = existing.get(pno)
        if p is None:
            db.add(Part(part_no=pno, is_purchased_assembly=True))
        else:
            p.is_purchased_assembly = True


def _for_audit(value: Any) -> str:
    """The logo is a long data URL; the log only needs to show that it changed."""
    if isinstance(value, dict) and (value.get("company") or {}).get("logo"):
        value = {**value, "company": {**value["company"], "logo": "(logo)"}}
    return json.dumps(value, ensure_ascii=False)


@router.get("/settings")
def get_settings_view(_: User = Depends(admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    return _settings_out(db)


@router.put("/settings/{key}")
def put_setting(key: str, body: SettingIn, me: User = Depends(admin),
                db: Session = Depends(get_db)) -> dict[str, Any]:
    if key not in SETTING_KEYS:
        raise HTTPException(404, f"Bilinmeyen ayar: {key}")
    value = _validate_setting(key, body.value)
    old = system.saved(db) if key == "system" else _settings_out(db)[key]
    if key == "purchased_assemblies":
        _mirror_purchased(db, value)
    set_setting(db, key, value)
    if old != value:
        audit.record(db, me, "setting", key, key, _for_audit(old), _for_audit(value))
    db.commit()
    system.apply_runtime(db)
    return _settings_out(db)


# ---------- audit log ----------
def _parse_when(s: str | None, end: bool) -> datetime | None:
    if not s:
        return None
    try:
        if len(s) == 10:
            d = date.fromisoformat(s)
            dt = datetime.combine(d + timedelta(days=1) if end else d, time.min)
        else:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as e:
        raise HTTPException(400, f"Geçersiz tarih: {s}") from e
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def audit_out(a: AuditLog) -> dict[str, Any]:
    return {"id": a.id, "ts": a.ts.isoformat() if a.ts else None, "user_id": a.user_id, "username": a.username,
            "project_id": a.project_id, "entity": a.entity, "entity_id": a.entity_id, "field": a.field,
            "old": a.old, "new": a.new, "action": a.action}


@router.get("/audit")
def list_audit(user: str | None = None, project_id: int | None = None, action: str | None = None,
               entity: str | None = None, entity_id: str | None = None, q: str | None = None,
               date_from: str | None = None, date_to: str | None = None,
               page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=1000),
               _: User = Depends(admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    """date_from/date_to: YYYY-MM-DD (date_to inclusive) or ISO datetime."""
    conds = []
    if user:
        conds.append(AuditLog.username == user)
    if project_id is not None:
        conds.append(AuditLog.project_id == project_id)
    if action:
        conds.append(AuditLog.action == action)
    if entity:
        conds.append(AuditLog.entity == entity)
    if entity_id:
        conds.append(AuditLog.entity_id == entity_id)
    if q:
        like = f"%{q}%"
        conds.append(or_(AuditLog.entity_id.ilike(like), AuditLog.field.ilike(like),
                         AuditLog.old.ilike(like), AuditLog.new.ilike(like)))
    start, end = _parse_when(date_from, False), _parse_when(date_to, True)
    if start:
        conds.append(AuditLog.ts >= start)
    if end:
        conds.append(AuditLog.ts < end if date_to and len(date_to) == 10 else AuditLog.ts <= end)
    total = db.scalar(select(func.count()).select_from(AuditLog).where(*conds)) or 0
    rows = db.scalars(select(AuditLog).where(*conds).order_by(AuditLog.ts.desc(), AuditLog.id.desc())
                      .offset((page - 1) * page_size).limit(page_size))
    return {"total": total, "page": page, "page_size": page_size, "items": [audit_out(a) for a in rows]}


@router.get("/audit/facets")
def audit_facets(_: User = Depends(admin), db: Session = Depends(get_db)) -> dict[str, list[str]]:
    """Distinct values for the audit filter dropdowns."""
    def distinct(col) -> list[str]:
        return sorted(v for v in db.scalars(select(col).distinct()) if v)
    return {"users": distinct(AuditLog.username), "actions": distinct(AuditLog.action),
            "entities": distinct(AuditLog.entity)}


# ---------- backups ----------
@router.get("/backups")
def list_backups(_: User = Depends(admin)) -> dict[str, Any]:
    return backup_svc.status()


@router.post("/backups", status_code=201)
def backup_now(me: User = Depends(admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        info = backup_svc.create_backup()
    except backup_svc.BackupError as e:
        raise HTTPException(409 if isinstance(e, backup_svc.BackupBusy) else 500, str(e)) from e
    audit.record(db, me, "backup", info.name, "size", None, info.size, action="create")
    db.commit()
    return info.to_dict()


@router.post("/backups/upload", status_code=201)
async def upload_backup(file: UploadFile = File(...), me: User = Depends(admin),
                        db: Session = Depends(get_db)) -> dict[str, Any]:
    """A backup from another computer: it joins the list and is restored from there."""
    folder = get_settings().backup_dir / "incoming"
    try:
        tmp, size = await uploads.store(file, folder, MAX_BACKUP_MB)
    except uploads.UploadTooLarge as e:
        raise HTTPException(413, str(e)) from e
    try:
        info = backup_svc.adopt_upload(tmp)
    except (ValueError, OSError, tarfile.TarError, KeyError) as e:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, f"Bu dosya geçerli bir yedek değil: {e}") from e
    audit.record(db, me, "backup", info.name, "size", None, size, action="upload")
    db.commit()
    return info.to_dict()


class RestoreIn(BaseModel):
    confirm: str = ""            # the backup's name: a stray request cannot wipe the data


@router.post("/backups/{name}/restore")
def restore_backup(name: str, body: RestoreIn, me: User = Depends(admin),
                   db: Session = Depends(get_db)) -> dict[str, Any]:
    if body.confirm != name:
        raise HTTPException(400, "Geri yükleme onaylanmadı")
    try:
        path = backup_svc.backup_path(name)
    except backup_svc.BackupError as e:
        raise HTTPException(404, str(e)) from e
    who = me.username
    db.close()
    try:
        with maintenance.exclusive():
            result = backup_svc.restore_live(path)
    except TimeoutError as e:
        raise HTTPException(409, str(e)) from e
    except (backup_svc.BackupError, ValueError, OSError, tarfile.TarError) as e:
        raise HTTPException(500, f"Geri yükleme başarısız, veriler eski haline getirildi: {e}") from e
    _is_default_password.cache_clear()
    loginguard.reset()
    with SessionLocal() as s:
        system.apply_runtime(s)
        u = s.scalar(select(User).where(User.username == who))
        if u is not None:
            audit.record(s, u, "backup", name, "restore", None, result["safety_backup"], action="restore")
        s.commit()
    return {"ok": True, "safety_backup": result["safety_backup"], "created_at": result.get("created_at")}


# ---------- HTTPS ----------
class HttpsIn(BaseModel):
    enabled: bool


def _https_out(request: Request) -> dict[str, Any]:
    on = tls.enabled()
    return {"enabled": on, "active": request.url.scheme == "https", "fingerprint": tls.fingerprint(),
            "supervised": os.environ.get("ERP_SUPERVISED") == "1"}


@router.get("/https")
def https_status(request: Request, _: User = Depends(admin)) -> dict[str, Any]:
    return _https_out(request)


@router.put("/https")
def https_set(body: HttpsIn, request: Request, me: User = Depends(admin),
              db: Session = Depends(get_db)) -> dict[str, Any]:
    before = tls.enabled()
    tls.enable() if body.enabled else tls.disable()
    if before != body.enabled:
        audit.record(db, me, "setting", "https", "enabled", before, body.enabled)
        db.commit()
    return _https_out(request)


@router.post("/server/restart")
def restart_server(_: User = Depends(admin)) -> dict[str, bool]:
    """Only under a service manager that starts the process again (the systemd unit of server_install.sh)."""
    if os.environ.get("ERP_SUPERVISED") != "1":
        raise HTTPException(409, "Bu sunucu kendini yeniden başlatamıyor. Sunucuyu elle yeniden başlatın.")
    threading.Timer(1, os.kill, (os.getpid(), signal.SIGTERM)).start()
    return {"ok": True}


@router.get("/backups/{name}")
def download_backup(name: str, me: User = Depends(admin), db: Session = Depends(get_db)) -> FileResponse:
    try:
        p = backup_svc.backup_path(name)
    except backup_svc.BackupError as e:
        raise HTTPException(404, str(e)) from e
    audit.record(db, me, "backup", name, "download", None, None, action="download")
    db.commit()
    return FileResponse(p, media_type="application/x-tar", filename=name)
