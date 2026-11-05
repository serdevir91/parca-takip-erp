"""SolidWorks BOM CSV parser (';' separated, utf-8-sig).

Header: Level;Dosya Adı;Reference Count;Malzeme;Ağırlık;Revizyon;TeminSekli;Kaplama Bilgisi
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Iterable

from .fastener import FastenerMatch, FastenerMatcher
from .normalize import strip_cad_ext
from app.core.i18n import tx

EXPECTED_HEADER = ["Level", "Dosya Adı", "Reference Count", "Malzeme", "Ağırlık", "Revizyon", "TeminSekli", "Kaplama Bilgisi"]

ROW_PART = "Parça"
ROW_ASSEMBLY = "Montaj"
ROW_FASTENER = "Bağlantı Elemanı"
ROW_IN_PURCHASED = "Satın alınan montajın içi"

TEMIN_IMALAT = "İmalat"
TEMIN_HAZIR = "Hazır Alım"
TEMIN_NONE = "Belirtilmemiş"
TEMIN_CHOICES = [TEMIN_IMALAT, TEMIN_HAZIR, TEMIN_NONE]

ROOT_GROUP = "(Ana montaj)"

DEFAULT_PART_NO_PATTERNS = [
    r"^T\d{2}_\d{4}_\d{4}(?:-[A-Za-z0-9]{1,3}|_\d{1,2})?$",   # in-house part numbers
    r"^\d+(?:\.\d+)+(?:\.R\d+)?(?:_\d+)?$",                    # supplier catalogue codes
]

_UNSPECIFIED = ("not specified", "belirli değil")

# Turkish Excel turns 1.1 into 1 January and saves the CSV with the date text: "1.Oca" (1.1), "Oca.13" (1.13),
# "01.01.2001" (1.1.1). The same happens to small weights: "12.May" (12.05), "Ara.50" (12.50).
_TR_MONTHS = {m: i for i, m in enumerate(("oca", "şub", "mar", "nis", "may", "haz", "tem", "ağu", "eyl", "eki", "kas", "ara"), 1)}
_RX_DAY_MONTH = re.compile(r"(\d{1,2})[.\- ]([^\W\d_]{3})[^\W\d_]*")
_RX_MONTH_YEAR = re.compile(r"([^\W\d_]{3})[^\W\d_]*[.\- ](\d{2})")
_RX_FULL_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.((?:19|20)\d{2})")


class BomParseError(ValueError):
    pass


@dataclass
class BomRow:
    seq: int
    level: str
    depth: int
    parent_level: str | None
    file_name: str
    part_no: str
    ext: str
    qty: int
    multiplier: int
    total_qty: int
    material: str
    weight: float | None
    rev: str
    procurement: str
    coating: str
    parent_part_no: str
    main_group: str
    in_purchased: bool
    is_purchased_assembly: bool
    fastener: FastenerMatch | None
    nonstandard: bool
    row_type: str = ""

    @property
    def is_assembly(self) -> bool:
        return self.ext == "SLDASM"


@dataclass
class ParsedBom:
    rows: list[BomRow]
    root_part_no: str
    warnings: list[str] = field(default_factory=list)

    @property
    def fastener_rows(self) -> list[BomRow]:
        return [r for r in self.rows if r.fastener and not r.in_purchased]

    @property
    def non_fastener_rows(self) -> list[BomRow]:
        return [r for r in self.rows if not r.fastener]

    def fastener_totals(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.fastener_rows:
            out[r.fastener.key] = out.get(r.fastener.key, 0) + r.total_qty
        return out

    def part_totals(self, include_in_purchased: bool = False) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.rows:
            if r.fastener or (r.in_purchased and not include_in_purchased):
                continue
            out[r.part_no] = out.get(r.part_no, 0) + r.total_qty
        return out


def clean_material(mat: str) -> str:
    m = (mat or "").strip()
    if not m:
        return ""
    low = m.lower()
    if any(u in low for u in _UNSPECIFIED):
        return ""
    return m


def _parse_weight(w: str) -> float | None:
    w = (w or "").strip()
    if not w:
        return None
    try:
        return float(w.replace(",", ".")) if w.count(",") == 1 and "." not in w else float(w)
    except ValueError:
        return None


def _excel_pair(v: str) -> tuple[int, int] | None:
    """The two numbers behind an Excel date text such as '1.Oca' or 'Oca.13', None for anything else."""
    if m := _RX_DAY_MONTH.fullmatch(v):
        month = _TR_MONTHS.get(m[2].lower())
        return (int(m[1]), month) if month else None
    if m := _RX_MONTH_YEAR.fullmatch(v):
        month = _TR_MONTHS.get(m[1].lower())
        return (month, int(m[2])) if month else None
    return None


def _restore_level(lvl: str) -> str:
    if pair := _excel_pair(lvl):
        return f"{pair[0]}.{pair[1]}"
    if m := _RX_FULL_DATE.fullmatch(lvl):
        return f"{int(m[1])}.{int(m[2])}.{int(m[3]) % 100}"
    return lvl


def _restore_weight(w: str) -> str:
    """SolidWorks writes weights with two decimals, so the pair gives the exact value back."""
    pair = _excel_pair(w)
    return f"{pair[0]}.{pair[1]:02d}" if pair else w


def decode_csv(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1254", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise BomParseError(tx("CSV kodlaması çözülemedi"))


def read_rows(text: str) -> list[list[str]]:
    reader = csv.reader(io.StringIO(text), delimiter=";")
    try:
        header = next(reader)
    except StopIteration as e:
        raise BomParseError(tx("CSV boş")) from e
    header = [h.strip().lstrip("﻿") for h in header]
    if [h.lower() for h in header[:8]] != [h.lower() for h in EXPECTED_HEADER]:
        raise BomParseError(tx("Beklenmeyen başlık: ") + ";".join(header))
    rows = []
    for x in reader:
        if x and x[0].strip():
            cells = [c.strip() for c in x] + [""] * 8
            rows.append(cells[:8])
    if not rows:
        raise BomParseError(tx("CSV satır içermiyor"))
    return rows


def parse_bom(
    data: bytes | str,
    purchased_assemblies: Iterable[str] = (),
    matcher: FastenerMatcher | None = None,
    part_no_patterns: Iterable[str] = DEFAULT_PART_NO_PATTERNS,
    buy_temins: Iterable[str] = (TEMIN_HAZIR,),
) -> ParsedBom:
    """Parse a BOM. `purchased_assemblies` are part numbers the user flagged as a single purchased item
    (their effective temin becomes 'Hazır Alım'); their children become 'Satın alınan montajın içi'."""
    text = decode_csv(data) if isinstance(data, bytes) else data
    raw = read_rows(text)
    bought = set(buy_temins)
    matcher = matcher or FastenerMatcher()
    flagged = set(purchased_assemblies)
    pn_rx = [re.compile(p) for p in part_no_patterns]

    out: list[BomRow] = []
    qty_at: dict[str, int] = {}
    name_at: dict[str, str] = {}
    hazir_at: list[str] = []
    warnings: list[str] = []
    seen_levels: set[str] = set()
    restored = 0

    for seq, (lvl, name, cnt, mat, w, rev, temin, kap) in enumerate(raw):
        fixed_lvl, fixed_w = _restore_level(lvl), _restore_weight(w)
        restored += (fixed_lvl != lvl) + (fixed_w != w)
        lvl, w = fixed_lvl, fixed_w
        if not re.fullmatch(r"\d+(?:\.\d+)*", lvl):
            raise BomParseError(tx("Satır {0}: geçersiz seviye '{1}'", seq + 2, lvl))
        if lvl in seen_levels:
            raise BomParseError(tx("Satır {0}: tekrarlanan seviye '{1}'", seq + 2, lvl))
        seen_levels.add(lvl)
        depth = lvl.count(".")
        par = lvl.rsplit(".", 1)[0] if depth else None
        if par is not None and par not in qty_at:
            raise BomParseError(tx("Satır {0}: üst seviye '{1}' bulunamadı", seq + 2, par))
        mult = qty_at.get(par, 1) if par else 1
        try:
            q = int(float(cnt.replace(",", "."))) if cnt else 0
        except ValueError as e:
            raise BomParseError(tx("Satır {0}: geçersiz adet '{1}'", seq + 2, cnt)) from e
        tot = q * mult
        qty_at[lvl] = tot
        base = strip_cad_ext(name)
        name_at[lvl] = base
        ext = name.rsplit(".", 1)[-1].upper() if "." in name else ""
        if ext not in ("SLDPRT", "SLDASM"):
            ext = "SLDPRT"
        in_hazir = par is not None and any(par == h or par.startswith(h + ".") for h in hazir_at)
        eff_temin = temin
        if ext == "SLDASM" and base in flagged:
            eff_temin = TEMIN_HAZIR
        is_purch = ext == "SLDASM" and eff_temin in bought and not in_hazir
        if is_purch:
            hazir_at.append(lvl)
        top = name_at.get(".".join(lvl.split(".")[:2])) if depth >= 1 else base
        fx = matcher.match(name) if ext == "SLDPRT" else None
        nonstd = not fx and not in_hazir and depth > 0 and not any(rx.match(base) for rx in pn_rx)
        row = BomRow(
            seq=seq, level=lvl, depth=depth, parent_level=par, file_name=name, part_no=base, ext=ext, qty=q,
            multiplier=mult, total_qty=tot, material=clean_material(mat), weight=_parse_weight(w), rev=rev,
            procurement=eff_temin, coating=kap, parent_part_no=name_at.get(par, "") if par else "",
            main_group=top if depth > 1 else ROOT_GROUP, in_purchased=in_hazir,
            is_purchased_assembly=is_purch, fastener=fx, nonstandard=nonstd)
        if in_hazir:
            row.row_type = ROW_IN_PURCHASED
        elif fx:
            row.row_type = ROW_FASTENER
        elif ext == "SLDASM":
            row.row_type = ROW_ASSEMBLY
        else:
            row.row_type = ROW_PART
        out.append(row)

    if restored:
        warnings.append(tx("Excel'in tarihe çevirdiği {0} değer (seviye, ağırlık) geri düzeltildi. Bu sorunu önlemek için SolidWorks'ten alınan CSV'yi Excel'de kaydetmeden yükleyin.", restored))
    root = out[0].part_no if out and out[0].depth == 0 else ""
    return ParsedBom(rows=out, root_part_no=root, warnings=warnings)
