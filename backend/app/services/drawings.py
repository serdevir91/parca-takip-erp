"""Technical drawing storage, matching, versioning and zip export (spec 7).

Drawings are global (one row per file name); a project sees the drawings whose
part number appears in its current BOM. Same file name uploaded again becomes
a new DrawingVersion; old versions stay on disk and can be downloaded.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import uuid
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.drawmatch import DRAWING_EXTS, DrawingMatcher, rev_mismatch, split_ext
from ..core.normalize import fuzzy_suggest, safe_filename, tr_casefold, tr_sort_key
from ..models import BomRow, Drawing, DrawingVersion, Part, PartAlias, User
from . import audit
from .state import ProjectView
from .thumbs import make_thumb

CHUNK = 1 << 20
ZIP_EXTS = {"zip"}
INLINE_EXTS = {"pdf", "png", "jpg", "jpeg"}
MEDIA_TYPES = {
    "pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "dxf": "image/vnd.dxf", "dwg": "image/vnd.dwg", "step": "model/step", "stp": "model/step",
}
ZIP_MODES = {"pdf": {"pdf"}, "pdf_dwg": {"pdf", "dwg"}, "all": None}


class DrawingError(ValueError):
    """User-facing error (Turkish message); the API returns it as 400."""


def media_type(ext: str) -> str:
    return MEDIA_TYPES.get(ext.lower(), "application/octet-stream")


def _max_bytes() -> int:
    return get_settings().max_upload_mb * 1024 * 1024


def tmp_dir() -> Path:
    d = get_settings().drawing_dir / "_tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _tmp_path() -> Path:
    return tmp_dir() / uuid.uuid4().hex


# ---------- streaming to disk ----------
async def save_upload(file: UploadFile) -> tuple[Path, int, str]:
    """Stream an upload to a temp file. Returns (path, size, sha256)."""
    path, size, h, limit = _tmp_path(), 0, hashlib.sha256(), _max_bytes()
    try:
        with path.open("wb") as out:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise DrawingError(f"Dosya çok büyük (en fazla {get_settings().max_upload_mb} MB).")
                h.update(chunk)
                out.write(chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path, size, h.hexdigest()


def _copy_stream(src: IO[bytes], too_big: str = "Zip içindeki dosya çok büyük") -> tuple[Path, int, str]:
    """Copy a binary stream to a temp file in 1 MB chunks. Returns (path, size, sha256)."""
    path, size, h, limit = _tmp_path(), 0, hashlib.sha256(), _max_bytes()
    try:
        with path.open("wb") as out:
            while chunk := src.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise DrawingError(f"{too_big} (en fazla {get_settings().max_upload_mb} MB).")
                h.update(chunk)
                out.write(chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path, size, h.hexdigest()


def save_upload_sync(file: UploadFile) -> tuple[Path, int, str]:
    """Sync twin of save_upload for sync endpoints (runs in the threadpool)."""
    file.file.seek(0)
    return _copy_stream(file.file, "Dosya çok büyük")


ZIP_MAX_ENTRIES = 5000
ZIP_MAX_RATIO = 20


def iter_zip(path: Path) -> Iterator[tuple[str, Path | None, int, str, str | None]]:
    """Yield (name, tmp_path, size, sha256, error) for every drawing file inside a zip."""
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        yield "", None, 0, "", "Zip dosyası okunamadı."
        return
    with zf:
        infos = zf.infolist()
        # Zip bomb guard: entry count and total unpacked size (header sizes, then the bytes really read)
        budget = max(ZIP_MAX_RATIO * path.stat().st_size, 64 * 1024 * 1024)
        if len(infos) > ZIP_MAX_ENTRIES:
            yield "", None, 0, "", f"Zip içinde çok fazla dosya var (en fazla {ZIP_MAX_ENTRIES})."
            return
        if sum(i.file_size for i in infos) > budget:
            yield "", None, 0, "", "Zip açıldığında çok büyük (sıkıştırma oranı şüpheli)."
            return
        used = 0
        for info in infos:
            if used > budget:
                yield info.filename, None, 0, "", "Zip açıldığında çok büyük; kalan dosyalar atlandı."
                return
            name = info.filename
            base = name.replace("\\", "/").rsplit("/", 1)[-1]
            if info.is_dir() or not base or name.startswith("__MACOSX/") or base.startswith("._"):
                continue
            ext = split_ext(base)[1]
            if ext not in DRAWING_EXTS:
                yield name, None, 0, "", f"Desteklenmeyen dosya türü: .{ext or '?'}"
                continue
            try:
                with zf.open(info) as src:
                    tmp, size, sha = _copy_stream(src)
                used += size
            except DrawingError as e:
                yield name, None, 0, "", str(e)
                continue
            except (zipfile.BadZipFile, RuntimeError, OSError) as e:
                yield name, None, 0, "", f"Zip içindeki dosya açılamadı: {e}"
                continue
            yield name, tmp, size, sha, None


# ---------- matching ----------
def project_matcher(view: ProjectView) -> DrawingMatcher:
    part_nos = list(dict.fromkeys(r.part_no for r in view.rows if not r.fastener_key))
    return DrawingMatcher(part_nos, view.aliases)


def global_matcher(db: Session) -> DrawingMatcher:
    aliases = {a.alias: a.part_no for a in db.scalars(select(PartAlias))}
    return DrawingMatcher(list(db.scalars(select(Part.part_no))), aliases)


def bom_revs(view: ProjectView) -> dict[str, str]:
    out: dict[str, str] = {}
    for r in view.rows:
        if r.fastener_key:
            continue
        if not out.get(r.part_no):
            out[r.part_no] = r.rev or ""
    return out


def _storage_path(drawing: Drawing, version_no: int) -> Path:
    folder = get_settings().drawing_dir / f"{drawing.id:06d}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"v{version_no:03d}_{safe_filename(drawing.filename)}"


def ingest(db: Session, matcher: DrawingMatcher, filename: str, tmp: Path, size: int, sha: str,
           user: User | None, project_id: int | None = None,
           revs: dict[str, str] | None = None) -> dict[str, Any]:
    """Store one uploaded file as a Drawing / new DrawingVersion. Consumes `tmp`."""
    revs = revs or {}
    base = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    stem, ext = split_ext(base)
    if ext not in DRAWING_EXTS or not stem:
        tmp.unlink(missing_ok=True)
        return {"filename": filename, "status": "rejected", "error": f"Desteklenmeyen dosya türü: .{ext or '?'}"}
    m = matcher.match(base)
    key = tr_casefold(base)
    d = db.scalar(select(Drawing).where(Drawing.filename_key == key))
    status = "created"
    if d is None:
        d = Drawing(filename=base, filename_key=key, base_name=m.parsed.base, ext=ext, rev=m.parsed.rev,
                    part_no=m.part_no, match_via=m.via, current_version=0,
                    project_id=project_id)
        db.add(d)
        db.flush()
        audit.record(db, user, "drawing", d.id, "upload", None, base, project_id, action="create")
    else:
        cur = next((v for v in d.versions if v.version_no == d.current_version), None)
        if cur is not None and cur.sha256 == sha:
            tmp.unlink(missing_ok=True)
            return _result(d, cur, "unchanged", m.suggestions, revs)
        status = "new_version"
        if d.part_no is None and m.part_no:
            d.part_no, d.match_via = m.part_no, m.via
        d.rev = m.parsed.rev if d.match_via != "manual" or m.parsed.rev else d.rev
    vno = (db.scalar(select(func.max(DrawingVersion.version_no)).where(DrawingVersion.drawing_id == d.id)) or 0) + 1
    dest = _storage_path(d, vno)
    os.replace(tmp, dest)
    v = DrawingVersion(drawing_id=d.id, version_no=vno, size=size, sha256=sha, storage_path=str(dest),
                       uploaded_by=user.username if user else "")
    db.add(v)
    d.current_version = vno
    db.flush()
    db.refresh(d)
    if status == "new_version":
        audit.record(db, user, "drawing", d.id, "version", vno - 1, vno, project_id)
    return _result(d, v, status, m.suggestions, revs)


def _result(d: Drawing, v: DrawingVersion, status: str, suggestions: list[tuple[str, float]],
            revs: dict[str, str]) -> dict[str, Any]:
    bom_rev = revs.get(d.part_no or "")
    return {"filename": d.filename, "status": status, "drawing_id": d.id, "version_no": v.version_no,
            "part_no": d.part_no, "via": d.match_via, "rev": d.rev, "bom_rev": bom_rev,
            "rev_mismatch": bool(d.part_no) and d.part_no in revs and rev_mismatch(d.rev, bom_rev),
            "suggestions": [{"part_no": p, "score": s} for p, s in suggestions] if not d.part_no else []}


# ---------- views ----------
def version_out(v: DrawingVersion) -> dict[str, Any]:
    return {"id": v.id, "version_no": v.version_no, "size": v.size, "sha256": v.sha256,
            "uploaded_by": v.uploaded_by, "uploaded_at": v.uploaded_at.isoformat() if v.uploaded_at else None}


def drawing_out(d: Drawing, revs: dict[str, str] | None = None, versions: bool = False) -> dict[str, Any]:
    revs = revs or {}
    cur = next((v for v in d.versions if v.version_no == d.current_version), None)
    bom_rev = revs.get(d.part_no or "") if d.part_no else None
    out = {
        "id": d.id, "filename": d.filename, "base_name": d.base_name, "ext": d.ext, "rev": d.rev,
        "part_no": d.part_no, "match_via": d.match_via, "current_version": d.current_version,
        "version_count": len(d.versions), "size": cur.size if cur else None,
        "uploaded_by": cur.uploaded_by if cur else "",
        "uploaded_at": cur.uploaded_at.isoformat() if cur and cur.uploaded_at else None,
        "bom_rev": bom_rev,
        "rev_mismatch": bool(d.part_no) and (d.part_no in revs) and rev_mismatch(d.rev, bom_rev),
        "inline": d.ext in INLINE_EXTS, "has_thumb": d.ext in INLINE_EXTS,
    }
    if versions:
        out["versions"] = [version_out(v) for v in sorted(d.versions, key=lambda v: -v.version_no)]
    return out


def project_listing(db: Session, view: ProjectView) -> dict[str, Any]:
    revs = bom_revs(view)
    part_set = set(revs)
    items: list[dict[str, Any]] = []
    for pno in sorted(part_set & set(view.drawings), key=tr_sort_key):
        for d in sorted(view.drawings[pno], key=lambda d: (d.ext, tr_sort_key(d.filename))):
            o = drawing_out(d, revs)
            o["part_no"] = pno           # canonical (alias resolved)
            o["rev_mismatch"] = rev_mismatch(d.rev, revs.get(pno))
            items.append(o)
    by_part: dict[str, dict[str, Any]] = {}
    for o in items:
        p = by_part.setdefault(o["part_no"], {"part_no": o["part_no"], "bom_rev": revs.get(o["part_no"], ""),
                                              "types": {}, "rev_mismatch": False})
        p["types"].setdefault(o["ext"], []).append(o["id"])
        p["rev_mismatch"] = p["rev_mismatch"] or o["rev_mismatch"]
    candidates = list(part_set)
    unmatched = []
    for d in db.scalars(select(Drawing).where(Drawing.part_no.is_(None)).order_by(Drawing.filename)):
        o = drawing_out(d)
        o["suggestions"] = [{"part_no": p, "score": s} for p, s in fuzzy_suggest(d.base_name, candidates)]
        unmatched.append(o)
    no_drawing = [p["part_no"] for p in view.parts(include_in_purchased=False)
                  if p["needs_drawing"] and not p["has_drawing"]]
    return {
        "items": items, "parts": list(by_part.values()), "unmatched": unmatched, "no_drawing": no_drawing,
        "counts": {"matched": len(items), "parts_with_drawing": len(by_part), "unmatched": len(unmatched),
                   "rev_mismatch": sum(1 for o in items if o["rev_mismatch"]), "no_drawing": len(no_drawing)},
    }


# ---------- edits ----------
def canonical_part(db: Session, part_no: str) -> str | None:
    """Resolve alias and check that the part number is known (Part master or any BOM row)."""
    pno = part_no.strip()
    alias = db.scalar(select(PartAlias).where(PartAlias.alias == pno))
    if alias is not None:
        pno = alias.part_no
    if db.scalar(select(Part.id).where(Part.part_no == pno)) is not None:
        return pno
    if db.scalar(select(BomRow.id).where(BomRow.part_no == pno).limit(1)) is not None:
        return pno
    return None


def _remove_files(v: DrawingVersion) -> None:
    for p in (v.storage_path, v.thumb_path):
        if p:
            Path(p).unlink(missing_ok=True)


def delete_version(db: Session, v: DrawingVersion, user: User | None) -> Drawing | None:
    """Delete one version. Returns the drawing, or None when it had no versions left and was removed."""
    d = v.drawing
    audit.record(db, user, "drawing", d.id, "version", v.version_no, None, action="delete")
    _remove_files(v)
    db.delete(v)
    db.flush()
    db.refresh(d)
    if not d.versions:
        audit.record(db, user, "drawing", d.id, "file", d.filename, None, action="delete")
        db.delete(d)
        db.flush()
        return None
    d.current_version = max(x.version_no for x in d.versions)
    db.flush()
    return d


def delete_drawing(db: Session, d: Drawing, user: User | None) -> None:
    for v in d.versions:
        _remove_files(v)
    audit.record(db, user, "drawing", d.id, "file", d.filename, None, action="delete")
    db.delete(d)
    db.flush()
    folder = get_settings().drawing_dir / f"{d.id:06d}"
    shutil.rmtree(folder, ignore_errors=True)


def thumb_for(db: Session, v: DrawingVersion) -> Path | None:
    """Cached first-page PNG for a PDF version, generated on first request. PNG/JPG drawings are their
    own preview."""
    if v.thumb_path and Path(v.thumb_path).is_file():
        return Path(v.thumb_path)
    if v.drawing.ext in INLINE_EXTS and v.drawing.ext != "pdf":
        return Path(v.storage_path) if Path(v.storage_path).is_file() else None
    if v.drawing.ext != "pdf":
        return None
    dst = get_settings().thumb_dir / f"dv{v.id}.png"
    if not make_thumb(Path(v.storage_path), dst):
        return None
    v.thumb_path = str(dst)
    db.commit()
    return dst


def build_zip(view: ProjectView, part_nos: list[str] | None, main_group: str | None, mode: str) -> tuple[Path, int]:
    """Zip the current version of the selected parts' drawings. Returns (path, file count)."""
    exts = ZIP_MODES.get(mode, ZIP_MODES["all"])
    wanted: set[str] = set()
    for r in view.rows:
        if r.fastener_key:
            continue
        if part_nos is not None and r.part_no not in part_nos:
            continue
        if main_group and r.main_group != main_group:
            continue
        wanted.add(r.part_no)
    path = tmp_dir() / f"{uuid.uuid4().hex}.zip"
    n = 0
    used: set[str] = set()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for pno in sorted(wanted & set(view.drawings), key=tr_sort_key):
            for d in view.drawings[pno]:
                if exts is not None and d.ext not in exts:
                    continue
                cur = next((v for v in d.versions if v.version_no == d.current_version), None)
                if cur is None or not Path(cur.storage_path).is_file():
                    continue
                arc = safe_filename(d.filename)
                if arc.casefold() in used:
                    arc = f"{d.id}_{arc}"
                used.add(arc.casefold())
                zf.write(cur.storage_path, arc)
                n += 1
    return path, n
