"""Product tree builder: a nested item tree to and from the BOM CSV that the import pipeline reads.

A node is a dict: part_no, assembly, qty, material, weight, rev, procurement, coating, children.
Generated CSVs go through the same upload, compare and approve steps as a SolidWorks export.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Iterable

from .bomparse import EXPECTED_HEADER
from .normalize import strip_cad_ext

MAX_NODES = 20000
MAX_DEPTH = 30
MAX_ERRORS = 10


def part_no_of(node: dict[str, Any]) -> str:
    return strip_cad_ext(str(node.get("part_no") or "")).replace("\n", " ").strip()


def validate(root: dict[str, Any], temin: Iterable[str]) -> list[str]:
    """Everything that would make a wrong BOM, in Turkish, tree order. Empty when the tree can be sent."""
    errors: list[str] = []
    allowed = set(temin)
    kinds: dict[str, bool] = {}
    count = 0

    def walk(n: dict[str, Any], level: str, parents: tuple[str, ...]) -> None:
        nonlocal count
        count += 1
        pno = part_no_of(n)
        where = f"{level} {pno}".strip()
        children = n.get("children") or []
        if not pno:
            errors.append(f"{level}: parça numarası boş.")
        elif pno in parents:
            errors.append(f"{where}: parça kendi altına eklenemez.")
            return
        elif kinds.setdefault(pno, bool(n.get("assembly"))) != bool(n.get("assembly")):
            errors.append(f"{where}: aynı numara hem parça hem montaj olamaz.")
        if int(n.get("qty") or 0) < 1:
            errors.append(f"{where}: adet en az 1 olmalı.")
        if children and not n.get("assembly"):
            errors.append(f"{where}: alt satırı olan kalem montaj olmalı.")
        if n.get("procurement") and n["procurement"] not in allowed:
            errors.append(f"{where}: geçersiz temin şekli.")
        if level.count(".") + 1 >= MAX_DEPTH and children:
            errors.append(f"{where}: ağaç en fazla {MAX_DEPTH} seviye olabilir.")
            return
        seen: set[str] = set()
        for i, c in enumerate(children, 1):
            cno = part_no_of(c)
            if cno and cno in seen:
                errors.append(f"{level}.{i} {cno}: aynı montajda iki kez var, adedini artırın.")
            seen.add(cno)
            walk(c, f"{level}.{i}", (*parents, pno))

    walk(root, "1", ())
    if count > MAX_NODES:
        errors.insert(0, f"Ağaçta en fazla {MAX_NODES} satır olabilir.")
    return errors


def to_csv(root: dict[str, Any]) -> bytes:
    buf = io.StringIO()
    out = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    out.writerow(EXPECTED_HEADER)

    def walk(n: dict[str, Any], level: str) -> None:
        children = n.get("children") or []
        ext = "SLDASM" if n.get("assembly") or level == "1" else "SLDPRT"
        weight = n.get("weight")
        out.writerow([level, f"{part_no_of(n)}.{ext}", 1 if level == "1" else n.get("qty", 1), n.get("material") or "",
                      "" if weight is None else weight, n.get("rev") or "", n.get("procurement") or "",
                      n.get("coating") or ""])
        for i, c in enumerate(children, 1):
            walk(c, f"{level}.{i}")

    walk(root, "1")
    return buf.getvalue().encode("utf-8-sig")


def node_of(r: Any) -> dict[str, Any]:
    return {"part_no": r.part_no, "assembly": r.ext == "SLDASM", "qty": r.qty, "material": r.material or "",
            "weight": r.weight, "rev": r.rev or "", "procurement": r.procurement or "",
            "coating": r.coating or "", "children": []}


def from_rows(rows: Iterable[Any]) -> dict[str, Any] | None:
    """Rows in BOM order, a whole version or one sub-assembly. The first row becomes the root; a row whose
    parent is not in `rows` hangs under it, so nothing is lost when a file has several top rows."""
    root: dict[str, Any] | None = None
    at: dict[str, dict[str, Any]] = {}
    for r in rows:
        n = at[r.level] = node_of(r)
        parent = at.get(r.parent_level) if r.parent_level else None
        if root is None:
            root = n
        else:
            (parent or root)["children"].append(n)
    return root
