"""Any list screen as an .xlsx file: the rows and columns the user sees now, with filters and frozen headers."""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter as L
from pydantic import BaseModel, Field

from ..config import get_settings
from ..models import Base, User
from ..permissions import can
from ..services import audit, excel_export
from .deps import admin, any_user, get_db
from app.core.i18n import tx

router = APIRouter(prefix="/export", tags=["export"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
KEEP_SECONDS = 3600
MAX_CELLS = 1_000_000            # a workbook this size already takes hundreds of MB while it is built
_building = threading.BoundedSemaphore(2)
MAX_TEXT = 32_000                # Excel keeps 32767 characters in a cell
MAX_SHEET_ROWS = 1_048_000
SECRET_COLUMN = re.compile(r"password|secret|token|hash|smtp|storage_path|thumb_path|_path$", re.I)
# table: sheet title, module whose view right it needs
ALL_TABLES: dict[str, tuple[str, str]] = {
    "projects": ("Projeler", "projects"), "bom_versions": ("BOM sürümleri", "projects"), "bom_rows": ("BOM satırları", "projects"),
    "parts": ("Parçalar", "parts"), "tracking": ("Parça takibi", "parts"), "part_names": ("Parça adları", "parts"),
    "missing_rows": ("Eksik parçalar", "parts"), "part_aliases": ("Parça eşleştirmeleri", "parts"),
    "fastener_rules": ("Bağlantı kuralları", "fasteners"), "fastener_settings": ("Bağlantı ayarları", "fasteners"),
    "drawings": ("Teknik resimler", "drawings"), "drawing_versions": ("Resim sürümleri", "drawings"),
    "assembly_plans": ("Montaj planları", "assembly"), "assembly_items": ("Montaj plan kalemleri", "assembly"),
    "assembly_extras": ("Montaj ek adetleri", "assembly"), "assembly_marks": ("Montaj işaretleri", "assembly"),
    "part_quantities": ("Parça adetleri", "assembly"),
    "control_issues": ("Kontrol listesi", "control"), "firms": ("Firmalar", "contacts"),
    "stock_items": ("Stok kartları", "stock"), "stock_moves": ("Stok hareketleri", "stock"),
    "purchase_orders": ("Satın alma", "purchasing"), "purchase_order_lines": ("Satın alma satırları", "purchasing"),
    "purchase_receipts": ("Mal kabul", "purchasing"), "work_orders": ("İş emirleri", "workorders"),
    "work_order_materials": ("İş emri malzemeleri", "workorders"), "work_order_ops": ("İş emri operasyonları", "workorders"),
    "sales_orders": ("Satış siparişleri", "sales"), "sales_order_lines": ("Satış satırları", "sales"),
    "sales_deliveries": ("Sevkiyatlar", "sales"), "invoices": ("Faturalar", "finance"),
    "invoice_lines": ("Fatura satırları", "finance"), "payments": ("Ödemeler", "finance"),
    "exchange_rates": ("Döviz kurları", "finance"), "employees": ("Personel", "hr"), "time_entries": ("Zaman kayıtları", "hr"),
    "holidays": ("Tatiller", "attendance"), "attendance": ("Puantaj", "attendance"), "leave_requests": ("İzinler", "attendance"),
    "attendance_requests": ("Puantaj talepleri", "attendance"), "project_templates": ("Proje şablonları", "projects"),
    "photos": ("Fotoğraflar", "parts"), "audit_log": ("Değişiklik geçmişi", "admin"),
}


class GridIn(BaseModel):
    columns: list[str] = Field(min_length=1, max_length=200)
    widths: list[float] = Field(default_factory=list, max_length=200)
    rows: list[list[Any]] = Field(max_length=200000)
    name: str = Field(default="", max_length=120)


class BookIn(BaseModel):
    sheets: list[GridIn] = Field(min_length=1, max_length=50)


def _dir() -> Path:
    d = Path(get_settings().data_dir) / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post("/grid")
def grid(body: GridIn, me: User = Depends(any_user)) -> dict:
    """Builds the file and returns an id; the file is then fetched with GET, which every client can save."""
    return _build([body], me.id)


@router.post("/book")
def book(body: BookIn, me: User = Depends(any_user)) -> dict:
    """Several tables of one screen, each on its own sheet."""
    return _build(body.sheets, me.id)


def _build(sheets: list[GridIn], owner: int) -> dict:
    if sum(len(s.columns) * len(s.rows) for s in sheets) > MAX_CELLS:
        raise HTTPException(413, tx("Liste Excel için çok büyük. Filtreleyip daha az satır veya sütun indirin."))
    if not _building.acquire(blocking=False):
        raise HTTPException(429, tx("Başka Excel dosyaları hazırlanıyor, biraz sonra tekrar deneyin"))
    try:
        return {"id": _write(sheets, owner)}
    finally:
        _building.release()


def _title(name: str, taken: set[str]) -> str:
    base = re.sub(r"[\\/*?:\[\]]", " ", name).strip()[:28] or "Liste"
    title, n = base, 1
    while title.lower() in taken:
        n += 1
        title = f"{base} {n}"
    taken.add(title.lower())
    return title


def fill(ws: Any, columns: list[str], rows: list[list[Any]], widths: list[float] | None = None) -> None:
    """One table on one sheet: bold frozen title row and filters."""
    width = len(columns)
    ws.append(columns)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="E7EDF5")
    for row in rows:
        ws.append(row[:width])
        for c in ws[ws.max_row]:
            if c.data_type == "f":      # what a table shows is data, whatever it starts with
                c.data_type = "s"
    for i, w in enumerate((widths or [])[:width], 1):
        ws.column_dimensions[L(i)].width = max(6, min(60, w / 7))
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{L(width)}{len(rows) + 1}"


def _write(sheets: list[GridIn], owner: int) -> str:
    wb = Workbook()
    wb.remove(wb.active)
    taken: set[str] = set()
    for s in sheets:
        fill(wb.create_sheet(_title(s.name, taken)), s.columns, s.rows, s.widths)
    return _save(wb, owner)


def _save(wb: Workbook, owner: int) -> str:
    folder = _dir()
    for old in folder.glob("*.xlsx"):
        if time.time() - old.stat().st_mtime > KEEP_SECONDS:
            old.unlink(missing_ok=True)
    fid = uuid.uuid4().hex
    (folder / f"{owner}_{fid}.xlsx").write_bytes(excel_export.to_bytes(wb))
    return fid


@router.post("/all")
def everything(db: Session = Depends(get_db), me: User = Depends(admin)) -> dict:
    """The whole database as one workbook. Only the tables named in ALL_TABLES go out, so a new table stays in until
    someone decides; passwords, settings and private messages never do. Other modules follow the admin's own rights."""
    if not _building.acquire(blocking=False):
        raise HTTPException(429, tx("Başka Excel dosyaları hazırlanıyor, biraz sonra tekrar deneyin"))
    try:
        fid = _write_all(db, me)
    finally:
        _building.release()
    audit.record(db, me, "export", "all", "tables", None, "excel", None, action="export")
    db.commit()
    return {"id": fid}


def _plain(ws: Any, v: Any) -> Any:
    if isinstance(v, (bool, int, float)) or v is None:
        return v
    if isinstance(v, datetime):
        return v.replace(tzinfo=None) if v.tzinfo else v
    if isinstance(v, date):
        return v
    text = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
    cell = WriteOnlyCell(ws, ILLEGAL_CHARACTERS_RE.sub("", text)[:MAX_TEXT])
    cell.data_type = "s"            # data, never a formula, whatever it starts with
    return cell


def _write_all(db: Session, me: User) -> str:
    wb = Workbook(write_only=True)      # a real database does not fit in memory as cells
    taken: set[str] = set()
    for table_name, (title, module) in ALL_TABLES.items():
        if not can(me, module, "view"):
            continue
        cols = [c for c in Base.metadata.tables[table_name].columns if not SECRET_COLUMN.search(c.name)]
        ws = wb.create_sheet(_title(tx(title), taken))
        ws.freeze_panes = "A2"
        ws.append([c.name for c in cols])
        for row in db.execute(select(*cols).limit(MAX_SHEET_ROWS)).yield_per(2000):
            ws.append([_plain(ws, v) for v in row])
    fid = uuid.uuid4().hex
    wb.save(_dir() / f"{me.id}_{fid}.xlsx")
    return fid


@router.get("/grid/{fid}")
def grid_file(fid: str, name: str = "liste", me: User = Depends(any_user)) -> Response:
    path = _dir() / f"{me.id}_{fid}.xlsx"
    if not re.fullmatch(r"[0-9a-f]{32}", fid) or not path.is_file():
        raise HTTPException(404, tx("Dosya bulunamadı, listeyi yeniden indirin"))
    return Response(path.read_bytes(), media_type=XLSX,
                    headers={"Content-Disposition": excel_export.content_disposition(f"{name}.xlsx")})
