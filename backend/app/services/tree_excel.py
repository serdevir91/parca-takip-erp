"""Compare any spreadsheet with the product tree on screen (SPEC §5.4).

Columns are guessed from their titles and from which values are numbers in the tree, like the part list
comparison. Nothing is written here: the page applies what the user selects, so undo keeps working and the
draft saves as usual. A level or parent column places new rows in the tree; without one the user picks where.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.normalize import strip_cad_ext
from . import excel_compare as cp
from .excel_import import _txt
from app.core.i18n import tx

F_PART, F_NAME, F_QTY, F_MATERIAL, F_WEIGHT = "part_no", "name", "qty", "material", "weight"
F_REV, F_TEMIN, F_COATING, F_LEVEL, F_PARENT, F_TYPE = "rev", "temin", "coating", "level", "parent", "type"

HEADERS: dict[str, tuple[str, ...]] = {
    F_PART: cp.HEADERS[cp.F_PART],
    F_NAME: ("parca adi", "parca ismi", "ad", "adi", "isim", "tanim", "tanimi", "aciklama", "urun adi", "malzeme adi",
             "name", "description", "desc"),
    F_QTY: ("adet", "miktar", "miktari", "birim adet", "qty", "quantity", "count"),
    F_MATERIAL: ("malzeme", "malzemesi", "hammadde", "material"),
    F_WEIGHT: ("agirlik", "kutle", "weight", "mass"),
    F_REV: ("rev", "revizyon", "revision"),
    F_TEMIN: cp.HEADERS[cp.F_TEMIN],
    F_COATING: ("kaplama", "yuzey islem", "yuzey", "coating", "finish"),
    F_LEVEL: ("seviye", "level", "kademe", "lvl", "hiyerarsi"),
    F_PARENT: ("ust montaj", "ust parca", "ust kod", "parent", "parent no", "parent part", "ana montaj"),
    F_TYPE: ("tip", "tur", "turu", "type", "kalem turu"),
}
TITLE_FIELD = {t: f for f, titles in HEADERS.items() for t in titles}
TITLES_LONGEST = sorted((t for t in TITLE_FIELD if len(t) >= 5), key=len, reverse=True)
TEXT_LIMITS = {F_NAME: 300, F_MATERIAL: 200, F_REV: 32, F_COATING: 200}
ASSEMBLY_WORDS = ("montaj", "assembly", "asm", "sldasm", "grup")
PART_NO_LIMIT = 200


def _title_field(title: str) -> str | None:
    if title in TITLE_FIELD:
        return TITLE_FIELD[title]
    return next((TITLE_FIELD[t] for t in TITLES_LONGEST if title.startswith(t + " ")), None)


def _key(raw: Any) -> str:
    return cp.Matcher._loose(_txt(raw))


def _number(raw: Any) -> float | None:
    """1,5 and 1.5 and 1.250,5 kg. None when the cell is not a number."""
    s = re.sub(r"\s*(kg|gr|g|adet|ad|pcs|pc)\.?\s*$", "", _txt(raw).strip(), flags=re.I).replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def _grams(raw: Any, title: str) -> float | None:
    n = _number(raw)
    if n is None:
        return None
    kilos = "kg" in _txt(raw).lower() or "kg" in title.split()
    return round(n * 1000 if kilos else n, 3)


@dataclass
class Row:
    sheet: str
    row: int
    part_no: str
    values: dict[str, Any] = field(default_factory=dict)   # the tree fields the row fills in
    qty: int | None = None
    assembly: bool | None = None
    parent: str | None = None                              # None: the file does not say


def walk(node: dict[str, Any], parent: str | None = None):
    """(node, number of its parent); the root has parent None."""
    yield node, parent
    for child in node.get("children") or []:
        yield from walk(child, _txt(node.get("part_no")))


def _detect(t: cp.Table, known: set[str]) -> dict[str, Any]:
    header = cp._find_header(t, _title_field)
    width = max(cp._columns(t, header), len(t.rows[header - 1]) if header else 0)
    titles = {c: cp.norm(t.at(header, c)) for c in range(1, width + 1)} if header else {}
    fields = {c: _title_field(n) for c, n in titles.items() if n}
    hits: dict[int, set[str]] = {}
    for line in t.rows[header:header + cp.DETECT_ROWS]:
        for c, v in enumerate(line, 1):
            if not cp._blank(v) and _key(v) in known:
                hits.setdefault(c, set()).add(_key(v))
    cols: dict[str, int] = {}
    if hits:
        cols[F_PART] = max(hits, key=lambda c: (len(hits[c]), fields.get(c) == F_PART, -c))
    else:
        cols[F_PART] = next((c for c, f in fields.items() if f == F_PART), 0)
    for c, f in fields.items():
        if f and f != F_PART and c != cols[F_PART]:
            cols.setdefault(f, c)
    if not cols[F_PART]:
        del cols[F_PART]
    return {"name": t.name, "header": header, "cols": cols, "use": F_PART in cols,
            "headers": [{"col": c, "title": _txt(t.at(header, c)) if header else ""} for c in range(1, width + 1)]}


def _depth(raw: Any) -> int | None:
    """'1.2.3' and 3 both say how deep a row sits. None when the cell says neither."""
    s = _txt(raw).strip().rstrip(".")
    if re.fullmatch(r"\d+(\.\d+)+", s):
        return s.count(".") + 1
    return int(s) if s.isdigit() else None


def _read(t: cp.Table, layout: dict[str, Any], temins: list[str], invalid: list[dict[str, Any]]) -> list[Row]:
    cols = layout["cols"]
    titles = {h["col"]: cp.norm(h["title"]) for h in layout["headers"]}
    path: list[str] = []          # the part open at each depth while reading a level column
    out: list[Row] = []

    def bad(r: int, part: str, label: str, value: Any, message: str) -> None:
        invalid.append({"sheet": t.name, "row": r, "part_no": part, "field": label, "value": _txt(value), "message": message})

    for r in range(layout["header"] + 1, len(t.rows) + 1):
        raw = t.at(r, cols[F_PART])
        if cp._blank(raw):
            continue
        text = _txt(raw).strip()
        part = strip_cad_ext(text).replace("\n", " ").strip()
        if len(part) > PART_NO_LIMIT:
            bad(r, part[:40], F_PART, part[:40], tx("Parça no çok uzun"))
            continue
        row = Row(t.name, r, part)
        if text.upper().endswith(".SLDASM"):
            row.assembly = True
        elif text.upper().endswith(".SLDPRT"):
            row.assembly = False
        for f, limit in TEXT_LIMITS.items():
            if f in cols and not cp._blank(v := t.at(r, cols[f])):
                row.values[f] = _txt(v).strip()[:limit]
        if F_WEIGHT in cols and not cp._blank(v := t.at(r, cols[F_WEIGHT])):
            grams = _grams(v, titles.get(cols[F_WEIGHT], ""))
            if grams is None or grams < 0:
                bad(r, part, F_WEIGHT, v, tx("Sayı bekleniyordu"))
            else:
                row.values[F_WEIGHT] = grams
        if F_QTY in cols and not cp._blank(v := t.at(r, cols[F_QTY])):
            n = _number(v)
            if n is None or n < 1 or n != int(n) or n > 1_000_000:
                bad(r, part, F_QTY, v, tx("Adet 1 veya daha büyük bir tam sayı olmalı"))
            else:
                row.qty = int(n)
        if F_TEMIN in cols and not cp._blank(v := t.at(r, cols[F_TEMIN])):
            name = cp.read_temin(v, temins)
            if name in temins:
                row.values["procurement"] = name
            else:
                bad(r, part, F_TEMIN, v, tx("Temin şekli tanımlı değil. Önce sistem ayarlarından ekleyin."))
        if F_TYPE in cols and not cp._blank(v := t.at(r, cols[F_TYPE])):
            row.assembly = any(w in cp.norm(v) for w in ASSEMBLY_WORDS)
        if F_LEVEL in cols:
            depth = _depth(t.at(r, cols[F_LEVEL]))
            if depth is not None:
                del path[depth:]
                row.parent = path[-1] if path else ""
                path.extend([""] * (depth - len(path)))
                path.append(part)
        if F_PARENT in cols:
            v = t.at(r, cols[F_PARENT])
            row.parent = "" if cp._blank(v) else strip_cad_ext(_txt(v)).strip()
        out.append(row)
    return out


def _merged(rows: list[Row]) -> list[Row]:
    """The same part twice under one parent is one line with the quantities added up."""
    seen: dict[tuple[str | None, str], Row] = {}
    for r in rows:
        k = (None if r.parent is None else _key(r.parent), _key(r.part_no))
        first = seen.setdefault(k, r)
        if first is r:
            continue
        first.qty = (first.qty or 1) + (r.qty or 1)
        first.values = {**r.values, **first.values}
        first.assembly = first.assembly if first.assembly is not None else r.assembly
    return list(seen.values())


def _parents_first(adds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out, left = [], list(adds)
    while left:
        waiting = {_key(a["part_no"]) for a in left}
        ready = [a for a in left if _key(a["parent_no"]) not in waiting or _key(a["parent_no"]) == _key(a["part_no"])]
        ready = ready or left                       # a loop in the file: keep the order it came in
        out += ready
        left = [a for a in left if not any(a is x for x in ready)]
    return out


def compare(path: str | Path, tree: dict[str, Any], config: dict[str, Any], temins: list[str]) -> dict[str, Any]:
    tables = cp.read_tables(path)
    spots: dict[str, list[tuple[dict[str, Any], str | None]]] = {}
    for node, parent in walk(tree):
        if k := _key(node.get("part_no")):
            spots.setdefault(k, []).append((node, parent))

    given = config.get("sheets") if isinstance(config.get("sheets"), dict) else {}
    layouts, rows, invalid = [], [], []
    for t in tables:
        layout = cp._merge(_detect(t, set(spots)), given.get(t.name), HEADERS)
        layout["rows"] = layout["matched"] = 0
        layouts.append(layout)
        if layout["use"] and F_PART in layout["cols"]:
            read = _read(t, layout, temins, invalid)
            rows += read
            layout["rows"] = len(read)
            layout["matched"] = len({_key(r.part_no) for r in read} & set(spots))

    rows = _merged(rows)
    root_no = _txt(tree.get("part_no"))
    top = [r for r in rows if r.parent == ""]
    new_root = None
    if len(top) == 1 and not root_no:               # an empty tree takes its root from the file
        new_root = {"part_no": top[0].part_no, "name": top[0].values.get(F_NAME, ""), "qty": 1, "assembly": True,
                    **{k: v for k, v in top[0].values.items() if k != F_NAME}}
        rows.remove(top[0])
        root_no = top[0].part_no
    changes: list[dict[str, Any]] = []
    adds: list[dict[str, Any]] = []

    def in_tree(no: str) -> str:
        """The number as the tree writes it, which the page looks nodes up with."""
        return _txt(spots[_key(no)][0][0].get("part_no")) if _key(no) in spots else no

    for r in rows:
        if r.parent == "" and _key(r.part_no) == _key(root_no):
            parent = None                           # the row of the root itself
        elif r.parent == "":
            parent = root_no
        else:
            parent = r.parent
        known = spots.get(_key(r.part_no), [])
        here = known if parent is None or r.parent is None else [s for s in known if _key(s[1]) == _key(parent)]
        if not here and _key(r.part_no) != _key(root_no):
            adds.append({"id": f"add|{parent or ''}|{r.part_no}", "part_no": r.part_no, "name": "", "material": "",
                         "weight": None, "rev": "", "procurement": "", "coating": "", **r.values, "qty": r.qty or 1,
                         "assembly": bool(r.assembly), "parent_no": in_tree(parent or "")})
            continue
        if not known:
            continue
        node = (here or known)[0][0]
        number = _txt(node.get("part_no"))
        for f, new in r.values.items():
            old = node.get(f)
            same = new == old or (isinstance(new, float) and old is not None and abs(new - old) <= 0.0005)
            if not same:
                changes.append({"id": f"{number}|{f}", "part_no": number, "parent_no": "", "field": f,
                                "old": old, "new": new})
        one_place = len(here) == 1 and here[0][1] is not None
        if r.qty is not None and one_place and r.qty != here[0][0].get("qty"):
            changes.append({"id": f"{number}|{here[0][1]}|qty", "part_no": number, "parent_no": here[0][1],
                            "field": F_QTY, "old": here[0][0].get("qty"), "new": r.qty})
    in_file = {_key(r.part_no) for r in rows} | {_key(root_no)}
    absent, listed = [], set()
    for node, parent in walk(tree):
        k = _key(node.get("part_no"))
        if parent is not None and k and k not in in_file and k not in listed:
            listed.add(k)
            absent.append({"part_no": _txt(node.get("part_no")), "name": _txt(node.get("name")), "qty": node.get("qty")})
    seen_changes = {c["id"]: c for c in changes}    # a part listed under several parents reports a field once
    return {"layouts": layouts, "sheets": [t.name for t in tables], "rows": len(rows),
            "matched": len({_key(r.part_no) for r in rows} & set(spots)), "changes": list(seen_changes.values()),
            "add": _parents_first(adds), "absent": absent, "invalid": invalid, "root": new_root,
            "placed": any(r.parent is not None for r in rows)}
