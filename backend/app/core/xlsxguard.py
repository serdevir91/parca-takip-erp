"""Decompression-bomb check for uploaded .xlsx files before openpyxl loads them into memory."""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import IO

MAX_UNPACKED = 300 * 1024 * 1024   # a real BOM/T-35 workbook is a few MB unpacked
MAX_RATIO = 200
MAX_ENTRIES = 10_000


def check_xlsx(src: str | Path | IO[bytes]) -> None:
    """Raise ValueError when the workbook would unpack to an unreasonable size. Non-zip input passes
    (openpyxl reports it as unreadable)."""
    try:
        zf = zipfile.ZipFile(src)
    except (zipfile.BadZipFile, OSError):
        return
    with zf:
        infos = zf.infolist()
        unpacked = sum(i.file_size for i in infos)
        packed = sum(i.compress_size for i in infos) or 1
        if len(infos) > MAX_ENTRIES or unpacked > MAX_UNPACKED or unpacked / packed > MAX_RATIO:
            raise ValueError("Excel dosyası açıldığında çok büyük; dosya bozuk veya zararlı olabilir.")
    if hasattr(src, "seek"):
        src.seek(0)
