"""Any list screen as an .xlsx file: the rows and columns the user sees now, with filters and frozen headers."""
from __future__ import annotations

import re
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter as L
from pydantic import BaseModel, Field

from ..config import get_settings
from ..models import User
from ..services import excel_export
from .deps import any_user

router = APIRouter(prefix="/export", tags=["export"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
KEEP_SECONDS = 3600


class GridIn(BaseModel):
    columns: list[str] = Field(min_length=1, max_length=200)
    widths: list[float] = Field(default_factory=list, max_length=200)
    rows: list[list[Any]] = Field(max_length=200000)


def _dir() -> Path:
    d = Path(get_settings().data_dir) / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post("/grid")
def grid(body: GridIn, _: User = Depends(any_user)) -> dict:
    """Builds the file and returns an id; the file is then fetched with GET, which every client can save."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Liste"
    ws.append(body.columns)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="E7EDF5")
    for row in body.rows:
        ws.append(row)
    for i, w in enumerate(body.widths[:len(body.columns)], 1):
        ws.column_dimensions[L(i)].width = max(6, min(60, w / 7))
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{L(len(body.columns))}{len(body.rows) + 1}"
    folder = _dir()
    for old in folder.glob("*.xlsx"):
        if time.time() - old.stat().st_mtime > KEEP_SECONDS:
            old.unlink(missing_ok=True)
    fid = uuid.uuid4().hex
    (folder / f"{fid}.xlsx").write_bytes(excel_export.to_bytes(wb))
    return {"id": fid}


@router.get("/grid/{fid}")
def grid_file(fid: str, name: str = "liste", _: User = Depends(any_user)) -> Response:
    path = _dir() / f"{fid}.xlsx"
    if not re.fullmatch(r"[0-9a-f]{32}", fid) or not path.is_file():
        raise HTTPException(404, "Dosya bulunamadı, listeyi yeniden indirin")
    return Response(path.read_bytes(), media_type=XLSX,
                    headers={"Content-Disposition": excel_export.content_disposition(f"{name}.xlsx")})
