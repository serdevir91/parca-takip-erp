"""Turkish-aware text helpers: casefold, sort keys, part-number normalisation, fuzzy match."""
from __future__ import annotations

import difflib
import re
import unicodedata

_TR_ALPHABET = "abcçdefgğhıijklmnoöprsştuüvyz"
_TR_ORDER = {ch: i for i, ch in enumerate(_TR_ALPHABET)}

CAD_EXT_RE = re.compile(r"\.(sldprt|sldasm)$", re.IGNORECASE)


def tr_lower(s: str | None) -> str:
    if not s:
        return ""
    return s.replace("I", "ı").replace("İ", "i").lower()


def tr_upper(s: str | None) -> str:
    if not s:
        return ""
    return s.replace("i", "İ").replace("ı", "I").upper()


def tr_casefold(s: str | None) -> str:
    """Casefold for search: Turkish lower + NFC, so 'İHMA' matches 'ihma' and 'IŞIK' matches 'ışık'."""
    return unicodedata.normalize("NFC", tr_lower(s))


def tr_sort_key(s: str | None) -> tuple:
    out = []
    for ch in tr_lower(s):
        if ch in _TR_ORDER:
            out.append((1, _TR_ORDER[ch], ""))
        elif ch.isdigit():
            out.append((0, int(ch), ""))
        else:
            out.append((2, 0, ch))
    return tuple(out)


def tr_contains(haystack: str | None, needle: str | None) -> bool:
    return tr_casefold(needle) in tr_casefold(haystack)


def strip_cad_ext(name: str) -> str:
    return CAD_EXT_RE.sub("", name.strip())


def part_key(part_no: str) -> str:
    """Normalised comparison key: Turkish casefold, '-', '_' and spaces unified."""
    s = tr_casefold(part_no.strip())
    s = re.sub(r"[\s_\-]+", "_", s)
    return s.strip("_")


SUFFIX_RE = re.compile(r"^(?P<base>.+?)(?P<suffix>-[A-Za-z0-9]{1,3}|_[0-9]{1,2})$")


def split_suffix(part_no: str) -> tuple[str, str]:
    """'T01_2000_0002-P' -> ('T01_2000_0002', '-P'); 'T01_2000_0002' -> (same, '')."""
    m = SUFFIX_RE.match(part_no)
    if m and re.search(r"\d{4}$", m.group("base")):
        return m.group("base"), m.group("suffix")
    return part_no, ""


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, part_key(a), part_key(b)).ratio()


def fuzzy_suggest(name: str, candidates: list[str], limit: int = 5, cutoff: float = 0.55) -> list[tuple[str, float]]:
    key = part_key(name)
    scored = []
    for c in candidates:
        ck = part_key(c)
        r = difflib.SequenceMatcher(None, key, ck).ratio()
        if ck and (ck in key or key in ck):
            r = max(r, 0.9)
        if r >= cutoff:
            scored.append((c, round(r, 3)))
    scored.sort(key=lambda x: (-x[1], x[0]))
    return scored[:limit]


def safe_filename(s: str) -> str:
    """Keep Turkish letters; drop path separators and control chars."""
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", s).strip(" .")
    return s or "dosya"
