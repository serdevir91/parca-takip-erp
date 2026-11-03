"""Per-module permissions. A role gives the defaults; an admin can override any module per user
(User.permissions = {"purchasing": "edit", "stock": "none", ...}). The admin role always has everything,
so the system can never be locked out."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status

from .models import ROLE_ADMIN, ROLE_DESIGNER, ROLE_PLANNER, ROLE_VIEWER, User

NONE, VIEW, EDIT = "none", "view", "edit"
LEVELS = (NONE, VIEW, EDIT)
LEVEL_LABELS = {NONE: "Yok", VIEW: "Görüntüle", EDIT: "Düzenle"}
_RANK = {NONE: 0, VIEW: 1, EDIT: 2}

# (key, label, menu group); order is the order of the permission matrix in Yönetim > Kullanıcılar
MODULES: list[tuple[str, str, str]] = [
    ("projects", "Projeler ve BOM", "Mühendislik"),
    ("parts", "Parça listesi", "Mühendislik"),
    ("fasteners", "Bağlantı elemanları", "Mühendislik"),
    ("drawings", "Teknik resimler", "Mühendislik"),
    ("control", "Kontrol listesi ve T-35", "Mühendislik"),
    ("planning", "İhtiyaç ve maliyet", "Planlama"),
    ("purchasing", "Satın alma", "Planlama"),
    ("workorders", "İş emirleri", "Üretim"),
    ("stock", "Stok", "Üretim"),
    ("hr", "Personel ve zaman", "Üretim"),
    ("contacts", "Cari kartlar (müşteri, tedarikçi)", "Ticari"),
    ("sales", "Satış (teklif, sipariş)", "Ticari"),
    ("finance", "Fatura ve ödemeler", "Ticari"),
    ("chat", "Sohbet (mesaj ve dosya)", "Sistem"),
    ("admin", "Yönetim (kullanıcılar, ayarlar, yedek)", "Sistem"),
]
MODULE_KEYS = [m[0] for m in MODULES]

_ENG = ("projects", "parts", "fasteners", "drawings", "control")
_OPS = ("planning", "purchasing", "workorders", "stock", "hr", "contacts", "sales", "finance")
# Defaults follow the job: wages (hr), money (finance) and customer deals (sales) stay with the roles that
# work on them. Every employee still sees their own personnel card (GET /hr/me) without hr rights.
ROLE_DEFAULTS: dict[str, dict[str, str]] = {
    ROLE_ADMIN: {k: EDIT for k in MODULE_KEYS},
    ROLE_DESIGNER: {**{k: EDIT for k in _ENG}, **{k: NONE for k in _OPS},
                    "planning": VIEW, "purchasing": VIEW, "workorders": VIEW, "stock": VIEW,
                    "chat": EDIT, "admin": NONE},
    # Planning/purchasing edits part tracking (progress, procurement) but does not upload BOMs or drawings
    ROLE_PLANNER: {**{k: VIEW for k in _ENG}, "parts": EDIT, "fasteners": EDIT, "control": EDIT,
                   **{k: EDIT for k in ("planning", "purchasing", "workorders", "stock", "contacts")},
                   "sales": VIEW, "finance": NONE, "hr": NONE, "chat": EDIT, "admin": NONE},
    # Everyone may chat; "view" on chat means read-only (no sending)
    ROLE_VIEWER: {**{k: VIEW for k in _ENG}, **{k: NONE for k in _OPS},
                  "planning": VIEW, "workorders": VIEW, "stock": VIEW, "chat": EDIT, "admin": NONE},
}


def clean_overrides(raw: object) -> dict[str, str]:
    """Keep only known modules and levels (bad input is dropped, not an error)."""
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k in MODULE_KEYS and v in LEVELS}


def effective(user: User) -> dict[str, str]:
    if user.role == ROLE_ADMIN:
        return dict(ROLE_DEFAULTS[ROLE_ADMIN])
    base = dict(ROLE_DEFAULTS.get(user.role, ROLE_DEFAULTS[ROLE_VIEWER]))
    base.update(clean_overrides(user.permissions))
    return base


def can(user: User, module: str, level: str = VIEW) -> bool:
    return _RANK[effective(user).get(module, NONE)] >= _RANK[level]


def require(module: str, level: str = VIEW):
    """FastAPI dependency: the current user needs `level` on `module`."""
    from .auth import current_user

    def dep(user: User = Depends(current_user)) -> User:
        if not can(user, module, level):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Bu işlem için yetkiniz yok")
        return user

    dep.__name__ = f"require_{module}_{level}"
    return dep


def catalog() -> dict:
    return {"modules": [{"key": k, "label": label, "group": g} for k, label, g in MODULES],
            "levels": [{"key": lv, "label": LEVEL_LABELS[lv]} for lv in LEVELS],
            "role_defaults": ROLE_DEFAULTS}
