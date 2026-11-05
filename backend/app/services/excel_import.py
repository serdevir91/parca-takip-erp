"""Re-import of an exported workbook (SPEC §9): diff of tracking fields against the DB, then apply.

Rows are matched by the hidden 'Anahtar' column (P:<part>, M:<missing id>, F:<fastener key>);
older exports without it fall back to 'Parça No' (and the fastener type/standard/size columns).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.orm import Session

from ..core.bomparse import TEMIN_CHOICES
from ..core.status import PROG_WAIT, PROGRESS_CHOICES
from ..core.xlsxguard import check_xlsx
from ..models import FastenerSetting, MissingRow, Project, Tracking, User
from . import audit
from .bomimport import TRACKING_FIELDS
from .excel_export import (H_FX_STATUS, H_KEY, H_MANUF, H_MATST, H_NOTE, H_PNO, H_PRICE, H_PROG,
                           H_SPARE, H_SUPPLIER, H_T35, H_TEMIN, KEY_FASTENER, KEY_MISSING, KEY_PART,
                           MISSING_SUFFIX)
from .settings import manufacturers
from .state import FASTENER_ORDER_STATUSES, ProjectView
from .tracking import material_status_choices
from app.core.i18n import tx

KIND_TRACKING, KIND_MISSING, KIND_FASTENER = "tracking", "missing", "fastener"

# Excel header -> (kind, model field)
PART_FIELDS: dict[str, str] = {H_PROG: "progress", H_TEMIN: "procurement_override", H_MANUF: "manufacturer",
                               H_MATST: "material_status", H_T35: "t35_note", H_NOTE: "note"}
MISSING_FIELDS: dict[str, str] = {H_PROG: "progress", H_NOTE: "note"}
FASTENER_FIELDS: dict[str, str] = {H_FX_STATUS: "order_status", H_SPARE: "spare_pct", H_PRICE: "unit_price",
                                   H_SUPPLIER: "supplier", H_NOTE: "note"}
assert set(PART_FIELDS.values()) <= set(TRACKING_FIELDS)

LABELS = {"progress": "İlerleme", "procurement_override": "Temin Şekli", "manufacturer": "Üretici",
          "material_status": "Malzeme Durumu", "t35_note": "Durum Notu", "note": "Not",
          "order_status": "Sipariş Durumu", "spare_pct": "Yedek %", "unit_price": "Birim Fiyat",
          "supplier": "Tedarikçi"}
_HEADER_SCAN_ROWS = 15
H_T35_OLD = "T-35 Notu"


class ImportError_(ValueError):
    """Workbook is not an export of this system (message is user facing)."""


def _txt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _num(v: Any) -> float | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return float(str(v).strip().replace(",", "."))


def _find_header(ws: Worksheet, needed: set[str]) -> tuple[int, dict[str, int]] | None:
    for r in range(1, _HEADER_SCAN_ROWS + 1):
        cols = {_txt(c.value): c.column for c in ws[r] if _txt(c.value)}
        if H_T35_OLD in cols:                            # file exported before 1.5.4
            cols.setdefault(H_T35, cols[H_T35_OLD])
        if needed <= set(cols):
            return r, cols
    return None


class _Ctx:
    """Current DB state the sheet is compared with."""

    def __init__(self, db: Session, project: Project):
        self.view = ProjectView.load(db, project)
        self.parts: dict[str, dict[str, Any]] = {}
        self.skip: set[str] = set()                      # root / inside purchased assemblies
        self.proc_shown: dict[str, set[str]] = {}
        for r in self.view.rows:
            if r.fastener_key:
                continue
            v = self.view.row_view(r)
            if r.depth == 0 or r.in_purchased:
                self.skip.add(r.part_no)
                continue
            self.parts.setdefault(r.part_no, v)
            # one part number may be both a .SLDPRT and a .SLDASM row, each showing its own effective temin
            self.proc_shown.setdefault(r.part_no, set()).add(v["procurement"] or "")
        self.skip -= set(self.parts)
        self.missing = {m.id: m for m in self.view.missing}
        self.fasteners = {f["key"]: f for f in self.view.fasteners()}
        self.fx_by_name = {(_txt(f["type"]), _txt(f["std"]), _txt(f["size"])): k for k, f in self.fasteners.items()}
        self.manufacturers = manufacturers(db)
        self.material = material_status_choices(db)

    # ---- current values ----
    def current(self, kind: str, key: str, field: str) -> Any:
        if kind == KIND_TRACKING:
            p = self.parts[key]
            return {"progress": p["progress"], "procurement_override": p["procurement"]}.get(field, p.get(field) or "")
        if kind == KIND_MISSING:
            m = self.missing[int(key)]
            if field == "note":                       # export shows the reason while the note is empty
                return m.note or m.reason or ""
            return getattr(m, field) or ""
        f = self.fasteners[key]
        return f.get(field) if field in ("spare_pct", "unit_price") else (f.get(field) or "")

    # ---- validation: returns normalised value or raises ValueError(message) ----
    def clean(self, kind: str, key: str, field: str, raw: Any) -> Any:
        if field in ("spare_pct", "unit_price"):
            try:
                v = _num(raw)
            except ValueError:
                raise ValueError(tx("Sayı olmalı")) from None
            if v is None:
                return None if field == "unit_price" else 0.0
            if v < 0 or (field == "spare_pct" and v > 1000):
                raise ValueError(tx("Geçersiz sayı"))
            return v
        v = _txt(raw)
        if field == "progress":
            if v not in PROGRESS_CHOICES:
                raise ValueError(tx("Seçenekler: ") + ", ".join(PROGRESS_CHOICES))
        elif field == "procurement_override":
            if v not in TEMIN_CHOICES:
                raise ValueError(tx("Seçenekler: ") + ", ".join(TEMIN_CHOICES))
            p = self.parts[key]
            if p["is_purchased_assembly"] and v != p["procurement"]:
                raise ValueError(tx("Satın alınan montajın temin şekli değiştirilemez"))
        elif field == "manufacturer":
            if v and self.manufacturers and v not in self.manufacturers:
                raise ValueError(tx("Üretici/firma listede yok"))
        elif field == "material_status":
            if v and v not in self.material:
                raise ValueError(tx("Seçenekler: ") + ", ".join(self.material))
        elif field == "order_status":
            if v not in FASTENER_ORDER_STATUSES:
                raise ValueError(tx("Seçenekler: ") + ", ".join(FASTENER_ORDER_STATUSES))
        return v

    def stored(self, kind: str, key: str, field: str, value: Any) -> Any:
        """Value as stored in the DB (temin: override is cleared when equal to the CSV value)."""
        if kind == KIND_TRACKING and field == "procurement_override":
            p = self.parts[key]
            csv = p["procurement_csv"] or ""
            if value == csv or (not csv and value == "Belirtilmemiş" and not p["is_assembly"]):
                return None
            return value
        return value


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) or isinstance(b, (int, float)):
        try:
            return (a is None and b is None) or (a is not None and b is not None and abs(float(a) - float(b)) < 1e-9)
        except (TypeError, ValueError):
            return False
    return _txt(a) == _txt(b)


def _parse_key(raw_key: str, pno: str) -> tuple[str, str] | None:
    k = raw_key.strip()
    if k.startswith(KEY_PART):
        return KIND_TRACKING, k[len(KEY_PART):]
    if k.startswith(KEY_MISSING):
        return KIND_MISSING, k[len(KEY_MISSING):]
    if k.startswith(KEY_FASTENER):
        return KIND_FASTENER, k[len(KEY_FASTENER):]
    p = pno.strip()
    if not p:
        return None
    if p.endswith(MISSING_SUFFIX):
        return None                                      # old export: missing rows cannot be matched
    return KIND_TRACKING, p


def preview(db: Session, project: Project, path: str | Path) -> dict[str, Any]:
    """Compare the workbook with the DB. Nothing is written."""
    try:
        check_xlsx(path)
        wb = load_workbook(path, data_only=False, read_only=False)
    except Exception as e:                                      # noqa: BLE001 - any parse failure
        raise ImportError_(tx("Excel dosyası okunamadı")) from e
    ctx = _Ctx(db, project)
    if ctx.view.version is None:
        raise ImportError_(tx("Projede onaylı BOM sürümü yok"))
    # one item can be on several rows (a part under several assemblies): every value read is kept, and
    # only the values that differ from the DB count; two different new values for one item are a conflict
    seen: dict[tuple[str, str, str], dict[str, Any]] = {}
    unknown: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    sheets_used: list[str] = []
    rows_read = 0

    def take(kind: str, key: str, field: str, raw: Any, sheet: str, row: int, label: str) -> None:
        try:
            new = ctx.clean(kind, key, field, raw)
        except ValueError as e:
            invalid.append({"sheet": sheet, "row": row, "key": label, "field": LABELS[field],
                            "value": _txt(raw), "message": str(e)})
            return
        sig = (kind, key, field)
        if sig not in seen:
            seen[sig] = {"kind": kind, "key": key, "label": label, "field": field, "field_label": LABELS[field],
                         "old": ctx.current(kind, key, field), "vals": []}
        old = seen[sig]["old"]
        shown = ctx.proc_shown.get(key, set()) if field == "procurement_override" else set()
        if len(shown) > 1 and new in shown:
            return                                     # SLDPRT + SLDASM rows each show their own temin
        if not _same(old, new) and not any(_same(v, new) for v, _, _ in seen[sig]["vals"]):
            seen[sig]["vals"].append((new, sheet, row))

    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            continue
        hit = _find_header(ws, {H_PNO, H_PROG})
        if hit:
            hr, cols = hit
            sheets_used.append(ws.title)
            for r in range(hr + 1, ws.max_row + 1):
                pno = _txt(ws.cell(r, cols[H_PNO]).value)
                key_raw = _txt(ws.cell(r, cols[H_KEY]).value) if H_KEY in cols else ""
                parsed = _parse_key(key_raw, pno)
                if parsed is None:
                    continue
                rows_read += 1
                kind, key = parsed
                if kind == KIND_TRACKING:
                    if key not in ctx.parts:
                        if key not in ctx.skip:
                            unknown.append({"sheet": ws.title, "row": r, "part_no": key})
                        continue
                    fields = PART_FIELDS
                else:
                    if not key.isdigit() or int(key) not in ctx.missing:
                        unknown.append({"sheet": ws.title, "row": r, "part_no": pno or key_raw})
                        continue
                    fields = MISSING_FIELDS
                label = pno or key
                for h, field in fields.items():
                    if h not in cols:
                        continue
                    raw = ws.cell(r, cols[h]).value
                    if field == "progress" and _txt(raw) == "":
                        continue                                   # blank selection: keep DB value
                    if field == "procurement_override" and _txt(raw) == "":
                        continue
                    take(kind, key, field, raw, ws.title, r, label)
            continue
        hit = _find_header(ws, {"Tür", "Standart", "Ölçü", H_FX_STATUS})
        if hit:
            hr, cols = hit
            sheets_used.append(ws.title)
            for r in range(hr + 1, ws.max_row + 1):
                key_raw = _txt(ws.cell(r, cols[H_KEY]).value) if H_KEY in cols else ""
                if key_raw.startswith(KEY_FASTENER):
                    key = key_raw[len(KEY_FASTENER):]
                else:
                    name = tuple(_txt(ws.cell(r, cols[h]).value) for h in ("Tür", "Standart", "Ölçü"))
                    if not any(name):
                        continue
                    key = ctx.fx_by_name.get(name, " ".join(n for n in name if n))
                rows_read += 1
                if key not in ctx.fasteners:
                    unknown.append({"sheet": ws.title, "row": r, "part_no": key})
                    continue
                f = ctx.fasteners[key]
                label = " ".join(x for x in (f["type"], f["std"], f["size"]) if x) or key
                for h, field in FASTENER_FIELDS.items():
                    if h not in cols:
                        continue
                    raw = ws.cell(r, cols[h]).value
                    if field == "order_status" and _txt(raw) == "":
                        continue
                    take(KIND_FASTENER, key, field, raw, ws.title, r, label)
    if not sheets_used:
        raise ImportError_(tx("Dosyada tanınan bir sayfa yok (Parça No / İlerleme başlıkları bulunamadı)"))

    changes = []
    for ch in seen.values():
        vals = ch.pop("vals")
        if not vals:
            continue
        if len(vals) > 1:
            for v, sheet, row in vals:
                invalid.append({"sheet": sheet, "row": row, "key": ch["label"], "field": ch["field_label"],
                                "value": _txt(v), "message": tx("Aynı kalem için farklı değerler var")})
            continue
        ch["new"], ch["sheet"], ch["row"] = vals[0]
        changes.append(ch)
    changes.sort(key=lambda c: (c["sheet"], c["row"], c["field"]))
    for c in changes:
        c["id"] = f"{c['kind']}|{c['key']}|{c['field']}"
    return {"sheets": sheets_used, "rows": rows_read, "changes": changes, "unknown": unknown, "invalid": invalid,
            "version_id": ctx.view.version.id}


def apply(db: Session, project: Project, user: User | None, changes: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply selected preview changes. Each item: kind, key, field, new and optional old.
    A change whose `old` no longer matches the DB is skipped (edited meanwhile). Caller commits."""
    ctx = _Ctx(db, project)
    applied, skipped = 0, []
    by_obj: dict[tuple[str, str], dict[str, Any]] = {}
    for ch in changes:
        kind, key, field = ch.get("kind"), str(ch.get("key", "")), ch.get("field")
        label = f"{key} / {LABELS.get(field or '', field)}"
        allowed = {KIND_TRACKING: PART_FIELDS, KIND_MISSING: MISSING_FIELDS, KIND_FASTENER: FASTENER_FIELDS}.get(kind)
        if allowed is None or field not in allowed.values():
            skipped.append({"key": label, "message": tx("Desteklenmeyen alan")})
            continue
        exists = (key in ctx.parts if kind == KIND_TRACKING else
                  (key.isdigit() and int(key) in ctx.missing) if kind == KIND_MISSING else key in ctx.fasteners)
        if not exists:
            skipped.append({"key": label, "message": tx("Kalem güncel BOM'da yok")})
            continue
        try:
            new = ctx.clean(kind, key, field, ch.get("new"))
        except ValueError as e:
            skipped.append({"key": label, "message": str(e)})
            continue
        if "old" in ch and not _same(ctx.current(kind, key, field), ch["old"]):
            skipped.append({"key": label, "message": tx("Değer bu arada değişmiş")})
            continue
        by_obj.setdefault((kind, key), {})[field] = ctx.stored(kind, key, field, new)

    for (kind, key), fields in by_obj.items():
        uname = user.username if user else "sistem"
        if kind == KIND_TRACKING:
            t = ctx.view.tracking.get(key)
            if t is None:
                t = Tracking(project_id=project.id, part_no=key, procurement_override=None, progress=PROG_WAIT,
                             note="", t35_note="", manufacturer="", material_status="", is_new=False)
                db.add(t)
                ctx.view.tracking[key] = t
            n = audit.record_changes(db, user, t, fields, "tracking", key, project.id)
            if n:
                t.updated_by = uname
        elif kind == KIND_MISSING:
            m: MissingRow = ctx.missing[int(key)]
            n = audit.record_changes(db, user, m, fields, "missing", m.part_no, project.id)
        else:
            fs = ctx.view.fastener_settings.get(key)
            if fs is None:
                fs = FastenerSetting(project_id=project.id, key=key, spare_pct=ctx.view.fastener_defaults["spare_pct"],
                                     supplier="", unit=ctx.view.fastener_defaults["unit"],
                                     unit_price=None, order_status=FASTENER_ORDER_STATUSES[0], note="")
                db.add(fs)
                ctx.view.fastener_settings[key] = fs
            n = audit.record_changes(db, user, fs, fields, "fastener", key, project.id)
        applied += n
    audit.record(db, user, "project", project.id, "excel_import", None, f"{applied} değişiklik", project.id,
                 action="excel_import")
    db.flush()
    return {"applied": applied, "skipped": skipped}
