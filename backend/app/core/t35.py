"""External status list import (T-35 Güncel Durumu type, spec 6).

Columns: No, Dosya Adı, Reference Count, Malzeme, Ağırlık, Revizyon, Durum.
Free text is mapped to progress / manufacturer / material status by
configurable keyword rules. A rule matches when every keyword in `all` is
contained in the text (Turkish-casefold). Lower priority wins.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

from openpyxl import load_workbook

from .normalize import strip_cad_ext, tr_casefold, tr_contains
from .status import PROG_DONE, PROG_RUN, PROG_WAIT

DEFAULT_RULES: list[dict[str, Any]] = [
    {"field": "progress", "all": ["TAMAMLANDI"], "value": PROG_DONE, "priority": 10},
    {"field": "progress", "all": ["İHMA HAZIR"], "value": PROG_DONE, "priority": 20},
    {"field": "progress", "all": ["ÜRETİMDE"], "value": PROG_RUN, "priority": 30},
    {"field": "progress", "all": ["İMALATTA"], "value": PROG_RUN, "priority": 40},
    {"field": "material_status", "all": ["SİPARİŞ VERİLMEMİŞ", "STOK"], "value": "Stoktan", "priority": 10},
    {"field": "material_status", "all": ["TEKRAR MALZEME"], "value": "Tekrar sipariş edildi", "priority": 20},
    {"field": "material_status", "all": ["DAHA ÖNCE"], "value": "Sipariş verildi", "priority": 30},
    {"field": "material_status", "all": ["MALZEME SÖYLENECEK"], "value": "Malzeme söylenecek", "priority": 40},
]
DEFAULT_PROGRESS = PROG_WAIT
# Texts that are not copied into the T-35 note on their own
DEFAULT_SKIP_NOTE = ["ÜRETİM TAMAMLANDI"]
DEFAULT_MANUFACTURERS = ["ROBOLEGO", "İHMA", "HAS-MAK"]
# Solid fills treated as "marked" (red / orange / amber)
MARK_FILLS = {"FFFF0000", "FFFFC000", "FFFF9900", "FFFF6600", "FFC00000", "FFED7D31", "FFFFA500"}
MARK_NOTE = "dış listede kırmızı işaretli"


@dataclass
class T35Row:
    row: int
    no: str
    plus: bool
    part_no: str
    qty: int | None
    material: str
    weight: float | None
    rev: str
    text: str
    fill: str | None

    @property
    def marked(self) -> bool:
        return bool(self.fill) and self.fill.upper() in MARK_FILLS


@dataclass
class T35Mapping:
    progress: str
    manufacturer: str | None
    material_status: str | None
    note: str | None
    marked: bool


@dataclass
class T35Config:
    rules: list[dict[str, Any]] = field(default_factory=lambda: [dict(r) for r in DEFAULT_RULES])
    default_progress: str = DEFAULT_PROGRESS
    skip_note: list[str] = field(default_factory=lambda: list(DEFAULT_SKIP_NOTE))
    manufacturers: list[str] = field(default_factory=lambda: list(DEFAULT_MANUFACTURERS))


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def read_t35(data: bytes) -> list[T35Row]:
    wb = load_workbook(io.BytesIO(data), data_only=True)
    ws = wb.active
    out: list[T35Row] = []
    for idx, row in enumerate(ws.iter_rows(min_row=2), start=2):
        cells = list(row[:7]) + [None] * (7 - len(row[:7]))
        vals = [c.value if c is not None else None for c in cells]
        a, b, c, d, e, f, g = vals
        if not b or not str(b).strip():
            continue
        fill = None
        bc = cells[1]
        if bc is not None and bc.fill is not None and bc.fill.fill_type == "solid":
            rgb = bc.fill.fgColor.rgb
            fill = rgb if isinstance(rgb, str) else None
        no = "" if a is None else str(a).strip()
        q = _num(c)
        out.append(T35Row(
            row=idx, no=no, plus=no.endswith("+"),
            part_no=strip_cad_ext(str(b).strip()),
            qty=int(q) if q is not None else None,
            material="" if d is None else str(d).strip(),
            weight=_num(e),
            rev="" if f is None else str(f).strip(),
            text=(g or "").strip() if isinstance(g, str) else ("" if g is None else str(g)),
            fill=fill,
        ))
    return out


def _match_rules(text: str, rules: list[dict[str, Any]], fld: str) -> str | None:
    for r in sorted((r for r in rules if r.get("field") == fld and r.get("active", True)),
                    key=lambda r: r.get("priority", 100)):
        kws = r.get("all") or []
        if kws and all(tr_contains(text, k) for k in kws):
            return r["value"]
    return None


def _norm_ws(s: str) -> str:
    return " ".join(tr_casefold(s).split())


def map_text(text: str, cfg: T35Config | None = None, marked: bool = False) -> T35Mapping:
    cfg = cfg or T35Config()
    progress = _match_rules(text, cfg.rules, "progress") or cfg.default_progress
    mat = _match_rules(text, cfg.rules, "material_status")
    manu = None
    for m in sorted(cfg.manufacturers, key=len, reverse=True):
        if m and tr_contains(text, m):
            manu = m
            break
    clean = " | ".join(" ".join(line.split()) for line in text.splitlines() if line.strip())
    note: str | None = clean or None
    if note and any(_norm_ws(note) == _norm_ws(s) for s in cfg.skip_note):
        note = None
    return T35Mapping(progress=progress, manufacturer=manu, material_status=mat, note=note, marked=marked)


@dataclass
class T35Preview:
    only_in_bom: list[str] = field(default_factory=list)
    only_in_list: list[str] = field(default_factory=list)
    rev_diff: list[dict[str, Any]] = field(default_factory=list)   # part_no, bom, list, produced -> DİKKAT
    qty_diff: list[dict[str, Any]] = field(default_factory=list)   # part_no, bom, list
    updates: list[dict[str, Any]] = field(default_factory=list)    # part_no + mapped fields


def build_preview(rows: list[T35Row], bom_parts: dict[str, dict[str, Any]],
                  cfg: T35Config | None = None, aliases: dict[str, str] | None = None) -> T35Preview:
    """bom_parts: part_no -> {rev, total_qty, produced(bool)} for trackable parts.
    aliases: alias part_no -> canonical part_no."""
    cfg = cfg or T35Config()
    aliases = aliases or {}
    pv = T35Preview()
    seen: set[str] = set()
    for r in rows:
        pno = aliases.get(r.part_no, r.part_no)
        if pno not in bom_parts:
            pv.only_in_list.append(r.part_no)
            continue
        seen.add(pno)
        bp = bom_parts[pno]
        if (bp.get("rev") or "") != r.rev:
            pv.rev_diff.append({"part_no": pno, "bom": bp.get("rev") or "", "list": r.rev,
                                "warning": "DİKKAT" if bp.get("produced") else ""})
        if r.qty is not None and bp.get("total_qty") is not None and int(bp["total_qty"]) != r.qty:
            pv.qty_diff.append({"part_no": pno, "bom": int(bp["total_qty"]), "list": r.qty})
        m = map_text(r.text, cfg, r.marked)
        pv.updates.append({"part_no": pno, "row": r.row, "text": r.text, "progress": m.progress,
                           "manufacturer": m.manufacturer, "material_status": m.material_status,
                           "note": m.note, "marked": m.marked})
    pv.only_in_bom = [p for p in bom_parts if p not in seen]
    return pv
