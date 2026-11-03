"""Plain file storage for photos and chat attachments: stream to disk with a size limit, no versioning."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import UploadFile

CHUNK = 1024 * 1024
IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "heic", "heif"}
# Shown inline by browsers (heic/heif are kept but only downloadable)
PREVIEW_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}
# The only types served with their own media type; everything else is application/octet-stream as an
# attachment. Never trust the uploader's Content-Type: text/html or image/svg+xml would run scripts.
SAFE_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
              "webp": "image/webp", "bmp": "image/bmp", "pdf": "application/pdf"}


class UploadTooLarge(ValueError):
    pass


def ext_of(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def is_image(name: str, content_type: str | None = None) -> bool:
    """By extension only; `content_type` comes from the client and is ignored."""
    return ext_of(name) in IMAGE_EXTS


def media_for(name: str) -> tuple[str, bool]:
    """(media type, may be shown inline) for a stored file, decided by its extension."""
    t = SAFE_TYPES.get(ext_of(name))
    return (t, True) if t else ("application/octet-stream", False)


def safe_name(name: str | None, fallback: str = "dosya") -> str:
    """Base name only (no folders), trimmed to the column size."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    return (base or fallback)[:300]


async def store(file: UploadFile, folder: Path, max_mb: int) -> tuple[Path, int]:
    """Stream `file` to `folder/<random>.<ext>`. Returns (path, size); removes the partial file on error."""
    folder.mkdir(parents=True, exist_ok=True)
    ext = ext_of(file.filename or "")
    path = folder / (uuid.uuid4().hex + (f".{ext}" if ext and len(ext) <= 10 else ""))
    size, limit = 0, max_mb * 1024 * 1024
    try:
        with path.open("wb") as out:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise UploadTooLarge(f"Dosya çok büyük (en fazla {max_mb} MB).")
                out.write(chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path, size


def remove(*paths: str | None) -> None:
    for p in paths:
        if p:
            Path(p).unlink(missing_ok=True)
