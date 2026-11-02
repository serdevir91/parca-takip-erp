"""BOM version comparison (spec 4.5).

Compares two parsed BOMs by part number. Weight is ignored. Fasteners are
compared per normalized item key (type|std|size) on their total quantity.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .bomparse import ParsedBom, BomRow
from .normalize import split_suffix, tr_sort_key

# Fastener total drop ratio that triggers a warning
BIG_DROP_RATIO = 0.10


@dataclass
class PartAgg:
    part_no: str
    is_assembly: bool
    rev: str
    material: str
    procurement: str
    total_qty: int
    rows: int
    in_purchased: bool  # every occurrence sits inside a purchased assembly


def aggregate_parts(bom: ParsedBom, include_in_purchased: bool = True) -> dict[str, PartAgg]:
    out: dict[str, PartAgg] = {}
    for r in bom.non_fastener_rows:
        if r.depth == 0:
            continue
        if r.in_purchased and not include_in_purchased:
            continue
        a = out.get(r.part_no)
        if a is None:
            out[r.part_no] = PartAgg(r.part_no, r.ext == "SLDASM", r.rev, r.material, r.procurement,
                                     r.total_qty, 1, r.in_purchased)
        else:
            a.total_qty += r.total_qty
            a.rows += 1
            a.in_purchased = a.in_purchased and r.in_purchased
            # keep the first non-empty value
            a.rev = a.rev or r.rev
            a.material = a.material or r.material
            a.procurement = a.procurement or r.procurement
    return out


@dataclass
class FieldChange:
    part_no: str
    old: str | int | None
    new: str | int | None


@dataclass
class FastenerChange:
    key: str
    desc: str
    std: str
    size: str
    old: int
    new: int

    @property
    def delta(self) -> int:
        return self.new - self.old


@dataclass
class AliasSuggestion:
    removed: str
    added: str
    base: str


@dataclass
class CompareResult:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    rev_changed: list[FieldChange] = field(default_factory=list)
    material_changed: list[FieldChange] = field(default_factory=list)
    procurement_changed: list[FieldChange] = field(default_factory=list)
    qty_changed: list[FieldChange] = field(default_factory=list)
    fastener_changes: list[FastenerChange] = field(default_factory=list)
    fastener_total_old: int = 0
    fastener_total_new: int = 0
    alias_suggestions: list[AliasSuggestion] = field(default_factory=list)

    @property
    def fastener_big_drop(self) -> bool:
        if self.fastener_total_old <= 0:
            return False
        drop = self.fastener_total_old - self.fastener_total_new
        return drop > 0 and drop / self.fastener_total_old >= BIG_DROP_RATIO

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.rev_changed or self.material_changed
                    or self.procurement_changed or self.qty_changed or self.fastener_changes)


def _fastener_items(bom: ParsedBom) -> dict[str, tuple[BomRow, int]]:
    items: dict[str, tuple[BomRow, int]] = {}
    for r in bom.fastener_rows:
        k = r.fastener.key
        first, tot = items.get(k, (r, 0))
        items[k] = (first, tot + r.total_qty)
    return items


def suggest_aliases(removed: list[str], added: list[str]) -> list[AliasSuggestion]:
    """Pair removed/added part numbers that differ only by a suffix (-P, -1, _2...)."""
    by_base_added: dict[str, list[str]] = {}
    for a in added:
        by_base_added.setdefault(split_suffix(a)[0], []).append(a)
    added_set = set(added)
    out: list[AliasSuggestion] = []
    used: set[str] = set()
    for r in removed:
        base = split_suffix(r)[0]
        cands = [a for a in by_base_added.get(base, []) if a != r and a not in used]
        # removed has suffix and the base itself was added
        if not cands and base != r and base in added_set and base not in used:
            cands = [base]
        if cands:
            a = sorted(cands, key=tr_sort_key)[0]
            used.add(a)
            out.append(AliasSuggestion(removed=r, added=a, base=base))
    return out


def compare_boms(old: ParsedBom, new: ParsedBom) -> CompareResult:
    res = CompareResult()
    po, pn = aggregate_parts(old), aggregate_parts(new)
    res.added = sorted((k for k in pn if k not in po), key=tr_sort_key)
    res.removed = sorted((k for k in po if k not in pn), key=tr_sort_key)
    for k in sorted((k for k in pn if k in po), key=tr_sort_key):
        a, b = po[k], pn[k]
        if a.rev != b.rev:
            res.rev_changed.append(FieldChange(k, a.rev, b.rev))
        if a.material != b.material:
            res.material_changed.append(FieldChange(k, a.material, b.material))
        if a.procurement != b.procurement:
            res.procurement_changed.append(FieldChange(k, a.procurement, b.procurement))
        if a.total_qty != b.total_qty:
            res.qty_changed.append(FieldChange(k, a.total_qty, b.total_qty))

    fo, fn = _fastener_items(old), _fastener_items(new)
    for k in sorted(set(fo) | set(fn), key=tr_sort_key):
        ro, qo = fo.get(k, (None, 0))
        rn, qn = fn.get(k, (None, 0))
        if qo != qn:
            ref = (rn or ro).fastener
            res.fastener_changes.append(FastenerChange(k, ref.desc, ref.std, ref.size, qo, qn))
    res.fastener_total_old = sum(q for _, q in fo.values())
    res.fastener_total_new = sum(q for _, q in fn.values())
    res.alias_suggestions = suggest_aliases(res.removed, res.added)
    return res
