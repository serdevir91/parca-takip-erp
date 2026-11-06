"""Automatic control-list checks (spec 8, Kontrol Listesi)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from typing import Iterable

from .bomparse import ParsedBom, TEMIN_IMALAT, TEMIN_NONE
from .normalize import tr_sort_key

KIND_EMPTY_MATERIAL = "Malzeme boş"
KIND_EMPTY_TEMIN = "Temin şekli boş"
KIND_NONSTANDARD = "Standart dışı isim"
KIND_PART_AND_ASM = "Aynı numara hem parça hem montaj"
KIND_DOUBLE_COUNT = "Çift sayım şüphesi"
KIND_MATERIAL_MISMATCH = "Malzeme tutarsızlığı"
KIND_REV = "Revizyon uyarısı"
KIND_NO_DRAWING = "Teknik resmi olmayan imalat parçası"

ALL_KINDS = [KIND_EMPTY_MATERIAL, KIND_EMPTY_TEMIN, KIND_NONSTANDARD, KIND_PART_AND_ASM,
             KIND_DOUBLE_COUNT, KIND_MATERIAL_MISMATCH, KIND_REV, KIND_NO_DRAWING]


@dataclass
class AutoIssue:
    kind: str
    part_no: str
    message: str
    levels: list[str] = field(default_factory=list)
    severity: str = "warning"   # warning | error | info
    choices: list[str] = field(default_factory=list)    # values that would settle it, when the check knows them

    @property
    def key(self) -> str:
        """Stable identity so a resolved issue stays resolved across recomputes."""
        return f"{self.kind}|{self.part_no}"


def _material_family(m: str) -> str:
    """'5083-111' and '5083-H11' -> '5083'. Leading alloy/grade token."""
    m = m.strip().upper()
    tok = re.split(r"[\s\-/,()]+", m, maxsplit=1)[0]
    return tok


def _material_norm(m: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", m.upper())


def _confusable(a: str, b: str) -> bool:
    """Same family and same length after normalising, differing in 1-2 characters
    (typo such as 1 vs H, 0 vs O)."""
    na, nb = _material_norm(a), _material_norm(b)
    if na == nb or len(na) != len(nb) or len(na) < 4:
        return na == nb and a != b
    diff = sum(1 for x, y in zip(na, nb) if x != y)
    return diff <= 2


def check_bom(bom: ParsedBom, drawing_parts: set[str] | None = None,
              produced_parts: set[str] | None = None,
              procurement_of: dict[str, str] | None = None,
              drawing_temins: Iterable[str] = (TEMIN_IMALAT,)) -> list[AutoIssue]:
    """drawing_parts: part numbers that have at least one drawing file (None = skip check).
    produced_parts: parts with progress Tamamlandı (for revision warnings).
    procurement_of: effective procurement per part (overrides CSV)."""
    procurement_of = procurement_of or {}
    issues: list[AutoIssue] = []
    rows = [r for r in bom.rows if r.depth > 0 and not r.fastener and not r.in_purchased]

    by_part: dict[str, list] = {}
    for r in rows:
        by_part.setdefault(r.part_no, []).append(r)

    for pno in sorted(by_part, key=tr_sort_key):
        rs = by_part[pno]
        first = rs[0]
        levels = [r.level for r in rs]
        is_asm = all(r.is_assembly for r in rs)
        temin = procurement_of.get(pno) or next((r.procurement for r in rs if r.procurement), "")
        if not is_asm and not any(r.material for r in rs):
            issues.append(AutoIssue(KIND_EMPTY_MATERIAL, pno, "Malzeme bilgisi girilmemiş.", levels))
        if not is_asm and (not temin or temin == TEMIN_NONE):
            issues.append(AutoIssue(KIND_EMPTY_TEMIN, pno, "Temin şekli seçilmemiş.", levels, "error"))
        if any(r.nonstandard for r in rs):
            issues.append(AutoIssue(KIND_NONSTANDARD, pno,
                                    f"'{first.file_name}' parça numarası standardına uymuyor.", levels, "info"))
        exts = {r.ext for r in rs}
        if len(exts) > 1:
            issues.append(AutoIssue(KIND_PART_AND_ASM, pno,
                                    "Aynı numara hem parça (.SLDPRT) hem montaj (.SLDASM) olarak kullanılmış.",
                                    levels, "error"))
        revs = {r.rev for r in rs}
        if len(revs) > 1:
            issues.append(AutoIssue(KIND_REV, pno,
                                    "Farklı satırlarda farklı revizyon: " + ", ".join(sorted(x or "(boş)" for x in revs)),
                                    levels, choices=sorted(x for x in revs if x)))
        if drawing_parts is not None and not is_asm and temin in drawing_temins and pno not in drawing_parts:
            issues.append(AutoIssue(KIND_NO_DRAWING, pno, "İmalat parçasının teknik resmi yok.", levels))

    # Double count: an assembly's child also appears as a direct sibling of that assembly
    children: dict[str, list] = {}
    for r in bom.rows:
        if r.parent_level is not None:
            children.setdefault(r.parent_level, []).append(r)
    reported: set[str] = set()
    for r in rows:
        if not r.is_assembly or r.parent_level is None:
            continue
        sib_parts = {s.part_no for s in children.get(r.parent_level, []) if s.level != r.level}
        for c in children.get(r.level, []):
            if c.fastener or c.part_no not in sib_parts or c.part_no in reported:
                continue
            reported.add(c.part_no)
            sib_levels = [s.level for s in children[r.parent_level] if s.part_no == c.part_no]
            issues.append(AutoIssue(
                KIND_DOUBLE_COUNT, c.part_no,
                f"'{r.part_no}' montajının içinde ve aynı üst montajda ayrıca listelenmiş; iki kez sayılıyor olabilir.",
                [c.level, *sib_levels]))

    # Material inconsistency: confusable spellings inside the same family
    mats: dict[str, set[str]] = {}
    for r in rows:
        if r.material:
            mats.setdefault(_material_family(r.material), set()).add(r.material)
    for fam, ms in mats.items():
        ms_sorted = sorted(ms, key=tr_sort_key)
        for i, a in enumerate(ms_sorted):
            for b in ms_sorted[i + 1:]:
                if _confusable(a, b):
                    na = sum(1 for r in rows if r.material == a)
                    nb = sum(1 for r in rows if r.material == b)
                    issues.append(AutoIssue(
                        KIND_MATERIAL_MISMATCH, f"{a} / {b}",
                        f"Benzer malzeme adları: '{a}' ({na} satır) ve '{b}' ({nb} satır). Yazım hatası olabilir.",
                        choices=[a, b]))

    if produced_parts:
        pass  # revision-after-production warnings come from BOM compare (see compare.py)
    return issues
