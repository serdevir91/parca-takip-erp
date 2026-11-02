"""Drawing file name -> part number matching (spec 7)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .normalize import fuzzy_suggest, part_key

DRAWING_EXTS = {"pdf", "dwg", "dxf", "slddrw", "sldprt", "sldasm", "step", "stp", "png", "jpg", "jpeg"}

# Revision suffix forms: "_RevD", " Rev D", " (Rev C)", "-RevC", "-D" (single letter)
_REV_RES = [
    re.compile(r"^(?P<base>.+?)\s*\(\s*rev\.?\s*(?P<rev>[A-Za-z0-9]{1,3})\s*\)$", re.I),
    re.compile(r"^(?P<base>.+?)[\s_\-]+rev\.?[\s_\-]*(?P<rev>[A-Za-z0-9]{1,3})$", re.I),
    re.compile(r"^(?P<base>.+?)-(?P<rev>[A-Z])$"),
]


@dataclass
class ParsedName:
    original: str
    stem: str
    ext: str
    base: str        # stem without revision suffix
    rev: str | None


def split_ext(filename: str) -> tuple[str, str]:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if "." in name:
        stem, ext = name.rsplit(".", 1)
        return stem.strip(), ext.lower()
    return name, ""


def parse_filename(filename: str) -> ParsedName:
    stem, ext = split_ext(filename)
    for rx in _REV_RES:
        m = rx.match(stem)
        if m:
            return ParsedName(filename, stem, ext, m["base"].strip(), m["rev"].upper())
    return ParsedName(filename, stem, ext, stem, None)


@dataclass
class MatchResult:
    parsed: ParsedName
    part_no: str | None
    via: str | None          # exact | alias | rev-stripped
    suggestions: list[tuple[str, float]]


class DrawingMatcher:
    def __init__(self, part_nos: list[str], aliases: dict[str, str] | None = None):
        """aliases: alias part_no -> canonical part_no."""
        self.part_nos = list(part_nos)
        self.by_key = {part_key(p): p for p in self.part_nos}
        self.alias_by_key = {part_key(a): c for a, c in (aliases or {}).items()}

    def _lookup(self, name: str) -> tuple[str | None, str | None]:
        k = part_key(name)
        if k in self.by_key:
            return self.by_key[k], "exact"
        if k in self.alias_by_key:
            return self.alias_by_key[k], "alias"
        return None, None

    def match(self, filename: str) -> MatchResult:
        p = parse_filename(filename)
        # Whole stem first: "T01_2000_0002-P" must not lose "-P" to the rev parser
        pno, via = self._lookup(p.stem)
        if pno:
            return MatchResult(ParsedName(p.original, p.stem, p.ext, p.stem, None), pno, via, [])
        if p.rev is not None:
            pno, via = self._lookup(p.base)
            if pno:
                return MatchResult(p, pno, "rev-stripped" if via == "exact" else via, [])
        sugg = fuzzy_suggest(p.base, self.part_nos)
        return MatchResult(p, None, None, sugg)


def rev_mismatch(drawing_rev: str | None, bom_rev: str | None) -> bool:
    if not drawing_rev:
        return False
    return (drawing_rev or "").strip().upper() != (bom_rev or "").strip().upper()
