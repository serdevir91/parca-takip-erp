"""Excel exports (Parça Takip, Takip Listesi, fastener order form) and re-import with diff (SPEC §9)."""
from __future__ import annotations

import io
import os
import tempfile
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Project, User
from ..services import excel_export as ex
from ..services import excel_import as im
from ..services.state import ProjectView
from ..permissions import require
from .deps import get_db, project_or_404

parts_view, parts_edit = require("parts", "view"), require("parts", "edit")

router = APIRouter(prefix="/excel", tags=["excel"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _view(db: Session, project_id: int) -> tuple[Project, ProjectView]:
    p = project_or_404(db, project_id)
    v = ProjectView.load(db, p)
    if v.version is None:
        raise HTTPException(400, "Projede onaylı BOM sürümü yok")
    return p, v


def _send(project: Project, kind: str, wb: Any) -> StreamingResponse:
    name = ex.export_filename(project, kind)
    return StreamingResponse(io.BytesIO(ex.to_bytes(wb)), media_type=XLSX,
                             headers={"Content-Disposition": ex.content_disposition(name)})


@router.get("/{project_id}/takip-listesi")
def takip_listesi(project_id: int, db: Session = Depends(get_db), _: User = Depends(parts_view)):
    """Full tracking list: summary, all rows, fastener detail and summary."""
    p, v = _view(db, project_id)
    return _send(p, "takip-listesi", ex.build_takip_listesi(db, v))


@router.get("/{project_id}/parca-takip")
def parca_takip(project_id: int, db: Session = Depends(get_db), _: User = Depends(parts_view)):
    """Parts-only list (one line per part number)."""
    p, v = _view(db, project_id)
    return _send(p, "parca-takip", ex.build_parca_takip(db, v))


@router.get("/{project_id}/baglanti-siparis")
def baglanti_siparis(project_id: int, db: Session = Depends(get_db), _: User = Depends(parts_view)):
    """Fastener order form."""
    p, v = _view(db, project_id)
    return _send(p, "baglanti-siparis", ex.build_fastener_order(db, v))


class VisibleIn(BaseModel):
    part_nos: list[str] = Field(default_factory=list)


@router.post("/{project_id}/gorunen")
def gorunen(project_id: int, body: VisibleIn, db: Session = Depends(get_db), _: User = Depends(parts_view)):
    """Parça Takip limited to the part numbers currently shown (filtered) in the UI."""
    if not body.part_nos:
        raise HTTPException(400, "Dışa aktarılacak parça seçilmedi")
    p, v = _view(db, project_id)
    return _send(p, "gorunen", ex.build_parca_takip(db, v, only=set(body.part_nos)))


async def _save_upload(file: UploadFile) -> str:
    """Stream the upload to a temp file in 1 MB chunks, enforcing max_upload_mb."""
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(400, "Sadece .xlsx dosyası yüklenebilir")
    limit = get_settings().max_upload_mb << 20
    fd, path = tempfile.mkstemp(suffix=".xlsx", prefix="excel_import_")
    size = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = await file.read(1 << 20)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"Dosya çok büyük (en fazla {limit >> 20} MB).")
                out.write(chunk)
    except BaseException:
        os.unlink(path)
        raise
    if size == 0:
        os.unlink(path)
        raise HTTPException(400, "Dosya boş")
    return path


@router.post("/{project_id}/import")
async def import_preview(project_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                         _: User = Depends(parts_edit)) -> dict[str, Any]:
    """Diff of an edited export against the DB: changes, unknown part numbers, invalid values. Writes nothing."""
    p = project_or_404(db, project_id)
    path = await _save_upload(file)
    try:
        return await run_in_threadpool(im.preview, db, p, path)   # openpyxl parsing is blocking
    except im.ImportError_ as e:
        raise HTTPException(400, str(e)) from e
    finally:
        os.unlink(path)


class ChangeIn(BaseModel):
    kind: str
    key: str
    field: str
    new: Any = None
    old: Any = None


class ApplyIn(BaseModel):
    changes: list[ChangeIn] = Field(default_factory=list)


@router.post("/{project_id}/import/apply")
def import_apply(project_id: int, body: ApplyIn, db: Session = Depends(get_db),
                 user: User = Depends(parts_edit)) -> dict[str, Any]:
    """Apply the selected preview changes (each one audited); changes edited meanwhile are skipped."""
    p = project_or_404(db, project_id)
    if p.current_version_id is None:
        raise HTTPException(400, "Projede onaylı BOM sürümü yok")
    if not body.changes:
        raise HTTPException(400, "Uygulanacak değişiklik seçilmedi")
    res = im.apply(db, p, user, [c.model_dump(exclude_unset=True) for c in body.changes])
    db.commit()
    return res
