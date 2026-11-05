"""Server-side translations. The Turkish source text is the key, as in the web interface.

The language comes from the erp_lang cookie or the X-Lang header; a missing entry falls
back to Turkish. Stored values and the tracking workbook stay Turkish on purpose: the
workbook's formulas and the Excel import depend on that text.
"""
from __future__ import annotations

import json
import re
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

LANGS = ("tr", "en", "es", "de")
_LOCALES = Path(__file__).resolve().parent.parent / "locales"
_PLACEHOLDER = re.compile(r"\{(\d+)\}")
_lang: ContextVar[str] = ContextVar("erp_lang", default="tr")


def set_lang(code: str | None) -> None:
    _lang.set(code if code in LANGS else "tr")


def current_lang() -> str:
    return _lang.get()


@lru_cache(maxsize=None)
def _catalog(code: str) -> dict[str, str]:
    try:
        return json.loads((_LOCALES / f"{code}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def tx(text: str, *args: object) -> str:
    """Translate Turkish source text and fill its {0}, {1} placeholders."""
    code = _lang.get()
    out = text if code == "tr" else _catalog(code).get(text, text)
    if not args:
        return out
    return _PLACEHOLDER.sub(lambda m: str(args[int(m.group(1))]), out)
