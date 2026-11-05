"""System-wide settings (Yönetim > Sistem Ayarları), kept in one `system` row.

The row holds only what differs from the defaults, so an untouched field keeps following the ERP_* environment
values. Code that has no database session (token lifetime, upload limit, permissions, ...) reads the config
object; apply_runtime() copies the saved values onto it on every authenticated request, which also keeps
several server processes (ERP_WORKERS) in step.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..core import numbers as num
from ..config import Settings, get_settings
from ..permissions import MODULE_KEYS
from .settings import get_setting
from app.core.i18n import tx

ALWAYS_ON = ("admin",)                         # switching this off would lock the settings screen itself
LOGO_PREFIX = "data:image/png;base64,"
LOGO_MAX = 200_000
_PREFIX_KEYS = {"PurchaseOrder": "no_po", "SalesOrder": "no_so", "Invoice": "no_invoice", "WorkOrder": "no_wo"}


@lru_cache
def _env() -> Settings:
    return Settings()


def defaults() -> dict[str, dict[str, Any]]:
    e = _env()
    return {
        "company": {"app_name": "LAB ERP", "logo": "", "name": "", "address": "", "phone": "", "email": "",
                    "web": "", "tax_office": "", "tax_no": ""},
        "commerce": {"currency": "TRY", "vat": 20.0, "payment_days": 30, "quote_days": 15,
                     "pay_methods": ["Havale/EFT", "Nakit", "Kredi kartı", "Çek", "Senet", "Mahsup"],
                     "no_po": "SA", "no_so": "SS", "no_invoice": "FT", "no_wo": "IE", "over_receipt_pct": 0.0,
                     "balance_basis": "today"},
        "production": {"unit": "Adet", "spare_pct": 10.0, "work_hours": 8.0, "week_hours": 45.0, "break_minutes": 60,
                       "annual_leave_days": 14.0},
        "security": {"session_hours": e.jwt_expire_hours, "password_min": e.password_min_length,
                     "login_attempts": e.login_attempts, "lock_minutes": e.login_lock_minutes},
        "files": {"upload_mb": e.max_upload_mb, "keep_days": e.backup_keep_days, "backup_time": e.backup_time},
        "modules": {"off": []},
    }


def saved(db: Session) -> dict[str, Any]:
    return get_setting(db, "system", {}) or {}


def system(db: Session) -> dict[str, dict[str, Any]]:
    stored = saved(db)
    return {sec: {**vals, **(stored.get(sec) or {})} for sec, vals in defaults().items()}


def apply_runtime(db: Session) -> None:
    v = system(db)
    s = get_settings()
    s.jwt_expire_hours = v["security"]["session_hours"]
    s.password_min_length = v["security"]["password_min"]
    s.login_attempts = v["security"]["login_attempts"]
    s.login_lock_minutes = v["security"]["lock_minutes"]
    s.max_upload_mb = v["files"]["upload_mb"]
    s.backup_keep_days = v["files"]["keep_days"]
    s.backup_time = v["files"]["backup_time"]
    s.disabled_modules = list(v["modules"]["off"])


def app_name(db: Session) -> str:
    return system(db)["company"]["app_name"]


def prefix(db: Session, model: Any) -> str:
    return system(db)["commerce"][_PREFIX_KEYS[model.__name__]]


def for_login(db: Session) -> dict[str, Any]:
    """Shown before sign-in, so nothing here may be private."""
    v = system(db)
    return {"app_name": v["company"]["app_name"], "logo": v["company"]["logo"],
            "password_min": v["security"]["password_min"]}


def for_user(db: Session) -> dict[str, Any]:
    """Form defaults every signed-in screen needs."""
    v = system(db)
    c, p = v["commerce"], v["production"]
    return {"currency": c["currency"], "vat": c["vat"], "payment_days": c["payment_days"],
            "quote_days": c["quote_days"], "pay_methods": c["pay_methods"], "unit": p["unit"],
            "work_hours": p["work_hours"], "password_min": v["security"]["password_min"],
            "modules_off": v["modules"]["off"]}


# ---------- validation ----------
def _text(v: Any, label: str, limit: int, required: bool = False) -> str:
    label = tx(label)
    if not isinstance(v, str):
        raise HTTPException(400, tx("{0} metin olmalı", label))
    out = v.strip()
    if len(out) > limit:
        raise HTTPException(400, tx("{0} en fazla {1} karakter olabilir", label, limit))
    if required and not out:
        raise HTTPException(400, tx("{0} boş olamaz", label))
    return out


def _number(v: Any, label: str, low: float, high: float, whole: bool = True) -> float | int:
    label = tx(label)
    try:
        n = float(v)
    except (TypeError, ValueError) as e:
        raise HTTPException(400, tx("{0} sayı olmalı", label)) from e
    if not low <= n <= high or (whole and n != int(n)):
        kind = "tam sayı" if whole else "sayı"
        raise HTTPException(400, tx("{0} {1} ile {2} arasında bir {3} olmalı", label, num.text(low), num.text(high), kind))
    return int(n) if whole else n


def _doc_prefix(v: Any, label: str) -> str:
    label = tx(label)
    out = _text(v, label, 8, required=True)
    if not re.fullmatch(r"[A-Za-z0-9]+", out):
        raise HTTPException(400, tx("{0} yalnızca harf ve rakamdan oluşmalı", label))
    return out


def _company(v: dict[str, Any]) -> dict[str, Any]:
    logo = v["logo"]
    if logo and (not isinstance(logo, str) or not logo.startswith(LOGO_PREFIX) or len(logo) > LOGO_MAX):
        raise HTTPException(400, tx("Logo en fazla 150 KB boyutunda bir PNG olmalı"))
    return {"app_name": _text(v["app_name"], "Uygulama adı", 40, required=True), "logo": logo,
            "name": _text(v["name"], "Şirket adı", 160), "address": _text(v["address"], "Adres", 300),
            "phone": _text(v["phone"], "Telefon", 40), "email": _text(v["email"], "E-posta", 120),
            "web": _text(v["web"], "Web adresi", 120), "tax_office": _text(v["tax_office"], "Vergi dairesi", 80),
            "tax_no": _text(v["tax_no"], "Vergi numarası", 40)}


def _basis(v: Any) -> str:
    if v not in ("today", "doc"):
        raise HTTPException(400, tx("Kur esası bugünkü kur veya belge kuru olmalı"))
    return v


def _commerce(v: dict[str, Any]) -> dict[str, Any]:
    cur = _text(v["currency"], "Para birimi", 3, required=True).upper()
    if not re.fullmatch(r"[A-Z]{3}", cur):
        raise HTTPException(400, tx("Para birimi TRY, EUR, USD gibi üç harfli kod olmalı"))
    raw = v["pay_methods"]
    if not isinstance(raw, list):
        raise HTTPException(400, tx("Ödeme yöntemleri bir liste olmalı"))
    methods = list(dict.fromkeys(m for m in (_text(x, "Ödeme yöntemi", 30) for x in raw) if m))
    if not methods:
        raise HTTPException(400, tx("En az bir ödeme yöntemi gerekli"))
    return {"currency": cur, "vat": _number(v["vat"], "KDV oranı", 0, 100, whole=False),
            "payment_days": _number(v["payment_days"], "Vade", 0, 365),
            "quote_days": _number(v["quote_days"], "Teklif geçerliliği", 0, 365), "pay_methods": methods,
            "no_po": _doc_prefix(v["no_po"], "Satın alma öneki"), "no_so": _doc_prefix(v["no_so"], "Satış öneki"),
            "no_invoice": _doc_prefix(v["no_invoice"], "Fatura öneki"),
            "no_wo": _doc_prefix(v["no_wo"], "İş emri öneki"),
            "over_receipt_pct": _number(v["over_receipt_pct"], "Fazla teslim payı", 0, 100, whole=False),
            "balance_basis": _basis(v["balance_basis"])}


def _production(v: dict[str, Any]) -> dict[str, Any]:
    return {"unit": _text(v["unit"], "Birim", 20, required=True),
            "spare_pct": _number(v["spare_pct"], "Yedek oranı", 0, 1000, whole=False),
            "work_hours": _number(v["work_hours"], "Günlük çalışma saati", 0.5, 24, whole=False),
            "week_hours": _number(v["week_hours"], "Haftalık çalışma saati", 1, 100, whole=False),
            "break_minutes": _number(v["break_minutes"], "Mola süresi", 0, 240),
            "annual_leave_days": _number(v["annual_leave_days"], "Yıllık izin hakkı", 0, 60, whole=False)}


def _security(v: dict[str, Any]) -> dict[str, Any]:
    return {"session_hours": _number(v["session_hours"], "Oturum süresi", 1, 720),
            "password_min": _number(v["password_min"], "En kısa şifre", 6, 64),
            "login_attempts": _number(v["login_attempts"], "Hatalı giriş sınırı", 3, 50),
            "lock_minutes": _number(v["lock_minutes"], "Kilit süresi", 1, 1440)}


def _files(v: dict[str, Any]) -> dict[str, Any]:
    at = _text(v["backup_time"], "Yedek saati", 5, required=True)
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", at):
        raise HTTPException(400, tx("Yedek saati SS:DD biçiminde olmalı (örn. 02:00)"))
    return {"upload_mb": _number(v["upload_mb"], "Yükleme sınırı", 1, 10240),
            "keep_days": _number(v["keep_days"], "Yedek saklama süresi", 1, 3650), "backup_time": at}


def _modules(v: dict[str, Any]) -> dict[str, Any]:
    off = v["off"]
    if not isinstance(off, list) or any(k not in MODULE_KEYS or k in ALWAYS_ON for k in off):
        raise HTTPException(400, tx("Kapatılamayan veya bilinmeyen modül"))
    return {"off": [k for k in MODULE_KEYS if k in off]}


_SECTIONS = {"company": _company, "commerce": _commerce, "production": _production, "security": _security,
             "files": _files, "modules": _modules}


def clean(value: Any) -> dict[str, Any]:
    """Validate a full or partial settings object; only values that differ from the defaults are stored."""
    if not isinstance(value, dict):
        raise HTTPException(400, tx("Sistem ayarları bir nesne olmalı"))
    out: dict[str, Any] = {}
    for sec, base in defaults().items():
        given = value.get(sec) or {}
        if not isinstance(given, dict):
            raise HTTPException(400, tx("Sistem ayarları bir nesne olmalı"))
        checked = _SECTIONS[sec]({**base, **given})
        changed = {k: x for k, x in checked.items() if x != base[k]}
        if changed:
            out[sec] = changed
    return out
