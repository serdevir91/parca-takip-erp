"""Product photos: several per part number (shared across projects, like drawings) or per stock item.

The browser sends a small JPEG thumbnail with each upload; lists use it, the viewer loads the original."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import current_user, session_token, user_from_token
from ..config import get_settings
from ..models import Photo, StockItem, User
from ..permissions import can
from ..services import audit, uploads
from .deps import get_db

router = APIRouter(tags=["photos"])

ENTITY_MODULES = {"part": "parts", "stock": "stock"}
MAX_PHOTO_MB = 50
MAX_THUMB_MB = 2


def _check(user: User, entity: str, level: str = "view") -> None:
    module = ENTITY_MODULES.get(entity)
    if module is None:
        raise HTTPException(400, "Bilinmeyen kayıt türü")
    if not can(user, module, level):
        raise HTTPException(403, "Bu işlem için yetkiniz yok")


def _key(db: Session, entity: str, key: str) -> str:
    key = key.strip()
    if not key:
        raise HTTPException(400, "Kayıt anahtarı boş")
    if entity == "stock" and (not key.isdigit() or db.get(StockItem, int(key)) is None):
        raise HTTPException(404, "Stok kartı bulunamadı")
    return key


def _photo_or_404(db: Session, photo_id: int) -> Photo:
    p = db.get(Photo, photo_id)
    if p is None:
        raise HTTPException(404, "Fotoğraf bulunamadı")
    return p


def photo_out(p: Photo) -> dict[str, Any]:
    return {"id": p.id, "entity": p.entity, "key": p.entity_key, "filename": p.filename,
            "content_type": p.content_type, "size": p.size, "caption": p.caption,
            "preview": uploads.ext_of(p.filename) in uploads.PREVIEW_EXTS or p.thumb_path is not None,
            "uploaded_by": p.uploaded_by, "uploaded_at": p.uploaded_at.isoformat() if p.uploaded_at else None}


@router.get("/photos")
def list_photos(entity: str, key: str, db: Session = Depends(get_db),
                user: User = Depends(current_user)) -> list[dict[str, Any]]:
    _check(user, entity)
    rows = db.scalars(select(Photo).where(Photo.entity == entity, Photo.entity_key == key.strip())
                      .order_by(Photo.id)).all()
    return [photo_out(p) for p in rows]


@router.get("/photos/counts")
def photo_counts(entity: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, int]:
    """{key: number of photos}, for a photo column in lists."""
    _check(user, entity)
    return {k: n for k, n in db.execute(select(Photo.entity_key, func.count()).where(Photo.entity == entity)
                                        .group_by(Photo.entity_key)).all()}


@router.post("/photos", status_code=201)
async def upload_photo(entity: str = Form(...), key: str = Form(...), file: UploadFile = File(...),
                       thumb: UploadFile | None = File(None), caption: str = Form(""),
                       db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    _check(user, entity, "edit")
    key = _key(db, entity, key)
    name = uploads.safe_name(file.filename, "foto.jpg")
    if not uploads.is_image(name, file.content_type):
        raise HTTPException(400, f"{name}: yalnızca resim dosyası yüklenebilir (JPG, PNG, WEBP, HEIC…)")
    folder = get_settings().photo_dir
    try:
        path, size = await uploads.store(file, folder, MAX_PHOTO_MB)
        thumb_path = None
        if thumb is not None and thumb.filename:
            thumb.filename = "t.jpg"
            thumb_path = str((await uploads.store(thumb, folder / "thumbs", MAX_THUMB_MB))[0])
    except uploads.UploadTooLarge as e:
        raise HTTPException(413, str(e)) from e
    p = Photo(entity=entity, entity_key=key, filename=name, content_type=file.content_type or "",
              size=size, storage_path=str(path), thumb_path=thumb_path, caption=caption.strip()[:300],
              uploaded_by=user.username)
    db.add(p)
    db.flush()
    audit.record(db, user, "photo", f"{entity}:{key}", "fotoğraf", None, name, action="create")
    db.commit()
    return photo_out(p)


class PhotoPatch(BaseModel):
    caption: str = Field("", max_length=300)


@router.patch("/photos/{photo_id}")
def edit_photo(photo_id: int, body: PhotoPatch, db: Session = Depends(get_db),
               user: User = Depends(current_user)) -> dict[str, Any]:
    p = _photo_or_404(db, photo_id)
    _check(user, p.entity, "edit")
    p.caption = body.caption.strip()
    db.commit()
    return photo_out(p)


@router.delete("/photos/{photo_id}")
def delete_photo(photo_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    p = _photo_or_404(db, photo_id)
    _check(user, p.entity, "edit")
    audit.record(db, user, "photo", f"{p.entity}:{p.entity_key}", "fotoğraf", p.filename, None, action="delete")
    paths = (p.storage_path, p.thumb_path)
    db.delete(p)
    db.commit()
    uploads.remove(*paths)
    return {"ok": True}


def _file_user(token: str | None = Depends(session_token), db: Session = Depends(get_db)) -> User:
    return user_from_token(token, db)


def _send(p: Photo, path: str | None, thumb: bool) -> FileResponse:
    if not path or not Path(path).is_file():
        raise HTTPException(404, "Dosya bulunamadı")
    media, inline = ("image/jpeg", True) if thumb and path == p.thumb_path else uploads.media_for(p.filename)
    return FileResponse(path, media_type=media, filename=None if thumb else p.filename,
                        content_disposition_type="inline" if inline else "attachment", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/photos/{photo_id}/file")
def photo_file(photo_id: int, db: Session = Depends(get_db), user: User = Depends(_file_user)) -> FileResponse:
    p = _photo_or_404(db, photo_id)
    _check(user, p.entity)
    return _send(p, p.storage_path, False)


@router.get("/photos/{photo_id}/thumb")
def photo_thumb(photo_id: int, db: Session = Depends(get_db), user: User = Depends(_file_user)) -> FileResponse:
    p = _photo_or_404(db, photo_id)
    _check(user, p.entity)
    return _send(p, p.thumb_path if p.thumb_path and Path(p.thumb_path).is_file() else p.storage_path, True)
