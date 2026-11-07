"""Technical drawings: upload (files or zip), matching, manual assign, download, thumbnail, delete."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import session_token, user_from_token
from ..core.drawmatch import split_ext
from ..models import Drawing, DrawingVersion, User
from ..services import assembly, assembly_pdf, audit
from ..services import drawings as svc
from ..services.state import ProjectView
from ..permissions import can, require
from .assembly import base_url as assembly_base_url
from .deps import get_db, project_or_404
from app.core.i18n import tx

drawings_edit = require("drawings", "edit")

router = APIRouter(tags=["drawings"])


def file_user(token: str | None = Depends(session_token), db: Session = Depends(get_db)) -> User:
    """Cookie or Bearer header only: tokens in URLs end up in logs and history and make links replayable."""
    user = user_from_token(token, db)
    if not can(user, "drawings", "view"):
        raise HTTPException(403, tx("Bu işlem için yetkiniz yok"))
    return user


class AssignIn(BaseModel):
    part_no: str | None = Field(None, description="Boş bırakılırsa eşleşme kaldırılır")


class DeleteIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=20000)


class ZipIn(BaseModel):
    part_nos: list[str] | None = None
    main_group: str | None = None
    mode: str = "pdf"


def _drawing_or_404(db: Session, did: int) -> Drawing:
    d = db.get(Drawing, did)
    if d is None:
        raise HTTPException(404, tx("Resim bulunamadı"))
    return d


def _version_or_404(db: Session, vid: int) -> DrawingVersion:
    v = db.get(DrawingVersion, vid)
    if v is None:
        raise HTTPException(404, tx("Resim sürümü bulunamadı"))
    return v


def _current(d: Drawing) -> DrawingVersion:
    v = next((x for x in d.versions if x.version_no == d.current_version), None)
    if v is None:
        raise HTTPException(404, tx("Resmin dosyası yok"))
    return v


def _send(v: DrawingVersion) -> FileResponse:
    p = Path(v.storage_path)
    if not p.is_file():
        raise HTTPException(404, tx("Dosya diskte bulunamadı"))
    d = v.drawing
    inline = d.ext in svc.INLINE_EXTS
    return FileResponse(p, media_type=svc.media_type(d.ext), filename=d.filename,
                        content_disposition_type="inline" if inline else "attachment")


@router.post("/projects/{pid}/drawings", status_code=201)
def upload(pid: int, files: list[UploadFile] = File(...), db: Session = Depends(get_db),
                 user: User = Depends(drawings_edit)) -> dict[str, Any]:
    """Upload one or more drawings (PDF/DWG/DXF/images) or zip archives of them.

    Sync on purpose: hashing, disk copies, zip extraction and DB work run in the threadpool."""
    project = project_or_404(db, pid)
    view = ProjectView.load(db, project)
    matcher, revs = svc.project_matcher(view), svc.bom_revs(view)
    results: list[dict[str, Any]] = []
    for f in files:
        name = (f.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        ext = split_ext(name)[1]
        if ext not in svc.ZIP_EXTS and ext not in svc.DRAWING_EXTS:
            results.append({"filename": name, "status": "rejected",
                            "error": tx("Desteklenmeyen dosya türü: .{0}", ext or "?")})
            continue
        try:
            tmp, size, sha = svc.save_upload_sync(f)
        except svc.DrawingError as e:
            results.append({"filename": name, "status": "rejected", "error": str(e)})
            continue
        if ext in svc.ZIP_EXTS:
            try:
                for inner, itmp, isize, isha, err in svc.iter_zip(tmp):
                    if err or itmp is None:
                        results.append({"filename": inner or name, "status": "rejected", "error": err, "zip": name})
                        continue
                    r = svc.ingest(db, matcher, inner, itmp, isize, isha, user, pid, revs)
                    r["zip"] = name
                    results.append(r)
            finally:
                tmp.unlink(missing_ok=True)
        else:
            results.append(svc.ingest(db, matcher, name, tmp, size, sha, user, pid, revs))
    db.commit()
    ok = [r for r in results if r["status"] != "rejected"]
    return {
        "results": results,
        "counts": {
            "total": len(results), "stored": sum(1 for r in ok if r["status"] in ("created", "new_version")),
            "unchanged": sum(1 for r in ok if r["status"] == "unchanged"),
            "matched": sum(1 for r in ok if r.get("part_no")), "unmatched": sum(1 for r in ok if not r.get("part_no")),
            "rev_mismatch": sum(1 for r in ok if r.get("rev_mismatch")),
            "rejected": len(results) - len(ok),
        },
    }


@router.get("/projects/{pid}/drawings")
def project_list(pid: int, db: Session = Depends(get_db), user: User = Depends(file_user)) -> dict[str, Any]:
    """Drawings of the project's current BOM, global unmatched files and parts without a drawing."""
    view = ProjectView.load(db, project_or_404(db, pid))
    return svc.project_listing(db, view)


@router.post("/projects/{pid}/drawings/zip")
def project_zip(pid: int, body: ZipIn, background: BackgroundTasks, db: Session = Depends(get_db),
                user: User = Depends(file_user)) -> FileResponse:
    """Zip of the current drawings of selected parts (mode: pdf | pdf_dwg | all)."""
    if body.mode not in svc.ZIP_MODES:
        raise HTTPException(400, tx("Geçersiz mod. Seçenekler: pdf, pdf_dwg, all"))
    project = project_or_404(db, pid)
    view = ProjectView.load(db, project)
    path, n = svc.build_zip(view, body.part_nos, body.main_group, body.mode)
    if n == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(404, tx("Seçime uyan resim yok"))
    background.add_task(path.unlink, missing_ok=True)
    return FileResponse(path, media_type="application/zip",
                        filename=f"{svc.safe_filename(project.name)}_resimler.zip")


class PrintIn(BaseModel):
    part_nos: list[str] = Field(min_length=1, max_length=2000)


@router.post("/projects/{pid}/drawings/print")
def project_print(pid: int, body: PrintIn, request: Request, db: Session = Depends(get_db), user: User = Depends(file_user)) -> Response:
    """One PDF of the chosen parts' drawings for double-sided printing, with a QR code on the back of each page."""
    project = project_or_404(db, pid)
    data = assembly_pdf.drawings_with_qr(assembly.context(db, project), body.part_nos, assembly_base_url(request))
    if data is None:
        raise HTTPException(404, tx("Seçime uyan PDF resim yok"))
    name = quote(f"{svc.safe_filename(project.name)}_resimler_qr.pdf")
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{name}"})


@router.get("/drawings/unmatched")
def unmatched(db: Session = Depends(get_db), user: User = Depends(file_user)) -> list[dict[str, Any]]:
    return [svc.drawing_out(d) for d in db.scalars(select(Drawing).where(Drawing.part_no.is_(None))
                                                   .order_by(Drawing.filename))]


@router.get("/drawings/{did}")
def detail(did: int, db: Session = Depends(get_db), user: User = Depends(file_user)) -> dict[str, Any]:
    return svc.drawing_out(_drawing_or_404(db, did), versions=True)


@router.post("/drawings/{did}/assign")
def assign(did: int, body: AssignIn, db: Session = Depends(get_db),
           user: User = Depends(drawings_edit)) -> dict[str, Any]:
    """Manually match (or unmatch) a drawing to a part number."""
    d = _drawing_or_404(db, did)
    pno: str | None = None
    if body.part_no and body.part_no.strip():
        pno = svc.canonical_part(db, body.part_no)
        if pno is None:
            raise HTTPException(400, tx("Parça numarası bulunamadı: {0}", body.part_no.strip()))
    old = d.part_no
    if old != pno:
        audit.record(db, user, "drawing", d.id, "part_no", old, pno)
    d.part_no = pno
    d.match_via = "manual" if pno else None
    db.commit()
    db.refresh(d)
    return svc.drawing_out(d, versions=True)


@router.get("/drawings/{did}/file")
def download(did: int, db: Session = Depends(get_db), user: User = Depends(file_user)) -> FileResponse:
    """Current version; PDFs and images open inline."""
    return _send(_current(_drawing_or_404(db, did)))


@router.get("/drawings/versions/{vid}/file")
def download_version(vid: int, db: Session = Depends(get_db), user: User = Depends(file_user)) -> FileResponse:
    return _send(_version_or_404(db, vid))


@router.get("/drawings/{did}/thumb")
def thumb(did: int, db: Session = Depends(get_db), user: User = Depends(file_user)) -> FileResponse:
    """First-page PNG of a PDF drawing (or the PNG/JPG itself); 404 when no preview can be made."""
    d = _drawing_or_404(db, did)
    v = _current(d)
    p = svc.thumb_for(db, v)
    if p is None:
        raise HTTPException(404, tx("Önizleme yok"))
    media = "image/png" if p.suffix.lower() == ".png" or d.ext == "pdf" else svc.media_type(d.ext)
    return FileResponse(p, media_type=media, headers={"Cache-Control": "private, max-age=3600"})


@router.delete("/drawings/versions/{vid}")
def delete_version(vid: int, db: Session = Depends(get_db), user: User = Depends(drawings_edit)) -> dict[str, Any]:
    """Delete one version; the drawing is removed with its last version."""
    v = _version_or_404(db, vid)
    d = svc.delete_version(db, v, user)
    db.commit()
    if d is None:
        return {"deleted": True, "drawing": None}
    db.refresh(d)
    return {"deleted": True, "drawing": svc.drawing_out(d, versions=True)}


@router.post("/drawings/delete")
def delete_many(body: DeleteIn, db: Session = Depends(get_db), user: User = Depends(drawings_edit)) -> dict[str, Any]:
    """Delete several drawings at once. Drawings are shared by part number, so this reaches every project."""
    found = db.scalars(select(Drawing).where(Drawing.id.in_(body.ids))).all()
    for d in found:
        svc.delete_drawing(db, d, user)
    db.commit()
    return {"deleted": len(found)}


@router.delete("/drawings/{did}")
def delete_drawing(did: int, db: Session = Depends(get_db), user: User = Depends(drawings_edit)) -> dict[str, Any]:
    svc.delete_drawing(db, _drawing_or_404(db, did), user)
    db.commit()
    return {"deleted": True}
