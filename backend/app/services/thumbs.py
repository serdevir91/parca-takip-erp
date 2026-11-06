"""First-page PNG thumbnails for PDF drawings.

Uses pypdfium2 when installed, else PyMuPDF (fitz). Without either, `make_thumb`
returns False and the API answers 404. PNG encoding is done here with zlib so
Pillow is not needed.
"""
from __future__ import annotations

import logging
import os
import struct
import threading
import zlib
from pathlib import Path

log = logging.getLogger(__name__)

THUMB_WIDTH = 480          # px, longest side target for the list and gallery preview
# PDFium is not thread-safe: a drawings page asks for several thumbnails at once, and two renders side by side
# crash the whole server process
_render_lock = threading.Lock()

try:  # pragma: no cover - import guard
    import pypdfium2 as _pdfium
    import pypdfium2.raw as _pdfium_c
except ImportError:  # pragma: no cover
    _pdfium = None
    _pdfium_c = None

try:  # pragma: no cover - import guard
    import fitz as _fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    _fitz = None


def available() -> bool:
    return _pdfium is not None or _fitz is not None


def encode_png(rgb: bytes, width: int, height: int, stride: int | None = None) -> bytes:
    """Encode 8-bit RGB pixels (rows of `stride` bytes) as PNG."""
    stride = stride or width * 3
    raw = bytearray()
    row_len = width * 3
    for y in range(height):
        raw.append(0)  # filter: none
        raw += rgb[y * stride:y * stride + row_len]

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) \
        + chunk(b"IEND", b"")


def _render_pdfium(src: Path) -> bytes | None:
    pdf = _pdfium.PdfDocument(str(src))
    try:
        if len(pdf) == 0:
            return None
        page = pdf[0]
        w, h = page.get_size()
        scale = THUMB_WIDTH / max(w, h, 1)
        bmp = page.render(scale=scale, force_bitmap_format=_pdfium_c.FPDFBitmap_BGR, rev_byteorder=True)
        info = bmp.get_info() if hasattr(bmp, "get_info") else None
        width = bmp.width if info is None else info.width
        height = bmp.height if info is None else info.height
        stride = bmp.stride if info is None else info.stride
        return encode_png(bytes(bmp.buffer), width, height, stride)
    finally:
        pdf.close()


def _render_fitz(src: Path) -> bytes | None:
    doc = _fitz.open(str(src))
    try:
        if doc.page_count == 0:
            return None
        page = doc[0]
        r = page.rect
        scale = THUMB_WIDTH / max(r.width, r.height, 1)
        return page.get_pixmap(matrix=_fitz.Matrix(scale, scale), alpha=False).tobytes("png")
    finally:
        doc.close()


def make_thumb(src: Path, dst: Path) -> bool:
    """Render the first page of PDF `src` to PNG `dst`. False if not possible."""
    if not available() or not src.is_file():
        return False
    try:
        with _render_lock:
            png = _render_pdfium(src) if _pdfium is not None else _render_fitz(src)
    except Exception as e:  # noqa: BLE001 - broken/encrypted PDFs simply get no preview
        log.warning("Thumbnail failed for %s: %s", src, e)
        return False
    if not png:
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(f"{dst.name}.{threading.get_ident()}.tmp")   # a reader never sees half a file
    part.write_bytes(png)
    os.replace(part, dst)
    return True
