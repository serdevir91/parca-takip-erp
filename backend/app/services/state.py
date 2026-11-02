"""Read model of a project: the approved BOM joined with tracking, drawings and fastener settings.

Every screen (Parts, Fasteners, Dashboard, Control, Excel export) builds its rows from
`ProjectView`, so status, effective procurement and counting rules live in one place.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.bomparse import (ROOT_GROUP, ROW_ASSEMBLY, ROW_FASTENER, ROW_IN_PURCHASED, ROW_PART,
                             TEMIN_HAZIR, TEMIN_IMALAT, TEMIN_NONE, BomRow as CoreRow, ParsedBom)
from ..core.fastener import FastenerMatch
from ..core.normalize import tr_sort_key
from ..core.status import (COLORS, KIND_HAZIR, KIND_IMALAT, KIND_MONTAJ, PROG_DONE, PROG_WAIT,
                           STATUS_MAP, STATUS_NO_TEMIN, derive_status, effective_procurement, status_kind)
from ..models import (BomRow, BomVersion, Drawing, FastenerSetting, MissingRow, PartAlias, Project,
                      Tracking)

FASTENER_ORDER_STATUSES = ["Sipariş Verilmedi", "Sipariş Verildi", "Teslim Edildi"]
FASTENER_TYPE_ORDER = ["Cıvata", "Somun", "Pim", "Rondela", "Kama", "Segman"]
FASTENER_COLORS = {"Sipariş Verilmedi": "FFC7CE", "Sipariş Verildi": "FFEB9C", "Teslim Edildi": "C6EFCE"}


def _num_key(s: str | None) -> float:
    try:
        return float(str(s).replace("M", "").replace("Ø", "").split("x")[0])
    except (TypeError, ValueError):
        return 0.0


def fastener_sort_key(item: dict[str, Any]) -> tuple:
    t = item.get("type") or ""
    order = FASTENER_TYPE_ORDER.index(t) if t in FASTENER_TYPE_ORDER else len(FASTENER_TYPE_ORDER)
    size = item.get("size") or ""
    parts = size.replace("M", "").replace("Ø", "").split("x")
    d = _num_key(parts[0]) if parts else 0.0
    ln = _num_key(parts[1]) if len(parts) > 1 else 0.0
    return (order, tr_sort_key(item.get("std") or ""), d, ln, tr_sort_key(size))


@dataclass
class ProjectView:
    project: Project
    version: BomVersion | None
    rows: list[BomRow] = field(default_factory=list)
    tracking: dict[str, Tracking] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)          # alias -> canonical part_no
    drawings: dict[str, list[Drawing]] = field(default_factory=dict)
    missing: list[MissingRow] = field(default_factory=list)
    fastener_settings: dict[str, FastenerSetting] = field(default_factory=dict)

    # ---------- loading ----------
    @classmethod
    def load(cls, db: Session, project: Project, version_id: int | None = None) -> "ProjectView":
        vid = version_id or project.current_version_id
        version = db.get(BomVersion, vid) if vid else None
        rows = list(db.scalars(select(BomRow).where(BomRow.version_id == version.id).order_by(BomRow.seq))) \
            if version else []
        tracking = {t.part_no: t for t in db.scalars(select(Tracking).where(Tracking.project_id == project.id))}
        aliases = {a.alias: a.part_no for a in db.scalars(select(PartAlias))}
        part_nos = {r.part_no for r in rows} | set(tracking)
        drawings: dict[str, list[Drawing]] = defaultdict(list)
        if part_nos:
            for d in db.scalars(select(Drawing).where(Drawing.part_no.is_not(None))):
                pno = aliases.get(d.part_no, d.part_no)
                drawings[pno].append(d)
        missing = list(db.scalars(select(MissingRow).where(MissingRow.project_id == project.id)
                                  .order_by(MissingRow.id)))
        fs = {f.key: f for f in db.scalars(select(FastenerSetting).where(FastenerSetting.project_id == project.id))}
        return cls(project, version, rows, tracking, aliases, dict(drawings), missing, fs)

    # ---------- conversions ----------
    def to_parsed(self) -> ParsedBom:
        out: list[CoreRow] = []
        root = ""
        for r in self.rows:
            fm = None
            if r.fastener_key:
                fm = FastenerMatch(r.fastener_type or "", r.fastener_desc or "", r.fastener_std or "",
                                   r.fastener_size or "", None, None, orig=r.file_name)
            if r.depth == 0:
                root = r.part_no
            out.append(CoreRow(
                seq=r.seq, level=r.level, depth=r.depth, parent_level=r.parent_level, file_name=r.file_name,
                part_no=r.part_no, ext=r.ext, qty=r.qty, multiplier=r.multiplier, total_qty=r.total_qty,
                material=r.material, weight=r.weight, rev=r.rev, procurement=r.procurement, coating=r.coating,
                parent_part_no=r.parent_part_no or "", main_group=r.main_group, in_purchased=r.in_purchased,
                is_purchased_assembly=r.is_purchased_assembly, fastener=fm, nonstandard=r.nonstandard,
                row_type=r.row_type))
        return ParsedBom(out, root)

    # ---------- per part ----------
    def procurement_of(self, part_no: str, csv_temin: str, is_assembly: bool, purchased_asm: bool) -> str:
        if purchased_asm:
            return TEMIN_HAZIR
        t = self.tracking.get(part_no)
        return effective_procurement(csv_temin, t.procurement_override if t else None, is_assembly)

    def drawing_info(self, part_no: str, rev: str) -> dict[str, Any]:
        ds = self.drawings.get(part_no, [])
        revs = sorted({d.rev for d in ds if d.rev}, key=tr_sort_key)
        return {
            "has_drawing": bool(ds),
            "drawing_ids": [d.id for d in ds],
            "drawing_rev": ", ".join(revs),
            "drawing_rev_mismatch": bool(revs) and bool(rev) and rev not in revs,
        }

    def row_view(self, r: BomRow) -> dict[str, Any]:
        is_asm = r.ext == "SLDASM"
        fastener = bool(r.fastener_key)
        t = self.tracking.get(r.part_no)
        proc = self.procurement_of(r.part_no, r.procurement, is_asm, r.is_purchased_assembly)
        progress = t.progress if t else PROG_WAIT
        if fastener:
            fs = self.fastener_settings.get(r.fastener_key or "")
            status = fs.order_status if fs else FASTENER_ORDER_STATUSES[0]
            color = FASTENER_COLORS.get(status, "")
        else:
            status = derive_status(progress, proc, is_asm and not r.is_purchased_assembly, r.in_purchased)
            color = COLORS["in_purchased"] if r.in_purchased else COLORS.get(status, "")
        alias_of = next((a for a, p in self.aliases.items() if p == r.part_no), None)
        v = {
            "id": r.id, "seq": r.seq, "level": r.level, "depth": r.depth, "parent_level": r.parent_level,
            "file_name": r.file_name, "part_no": r.part_no, "ext": r.ext, "is_assembly": is_asm,
            "qty": r.qty, "multiplier": r.multiplier, "total_qty": r.total_qty,
            "material": r.material, "weight": r.weight, "rev": r.rev,
            "procurement_csv": r.procurement, "procurement": proc,
            "procurement_override": t.procurement_override if t else None,
            "coating": r.coating, "parent_part_no": r.parent_part_no, "main_group": r.main_group,
            "row_type": r.row_type, "in_purchased": r.in_purchased,
            "is_purchased_assembly": r.is_purchased_assembly, "nonstandard": r.nonstandard,
            "alias": alias_of,
            "counted": not r.in_purchased and not fastener and r.depth > 0,
            "fastener": fastener, "fastener_key": r.fastener_key, "fastener_type": r.fastener_type,
            "fastener_desc": r.fastener_desc, "fastener_std": r.fastener_std, "fastener_size": r.fastener_size,
            "progress": progress, "status": status, "status_color": color,
            "status_kind": status_kind(proc, is_asm and not r.is_purchased_assembly),
            "note": t.note if t else "", "t35_note": t.t35_note if t else "",
            "manufacturer": t.manufacturer if t else "", "material_status": t.material_status if t else "",
            "is_new": bool(t and t.is_new), "updated_at": t.updated_at.isoformat() if t and t.updated_at else None,
            "updated_by": t.updated_by if t else "",
        }
        v.update(self.drawing_info(r.part_no, r.rev))
        return v

    def all_rows(self) -> list[dict[str, Any]]:
        return [self.row_view(r) for r in self.rows]

    def parts(self, include_in_purchased: bool = True) -> list[dict[str, Any]]:
        """Unique parts (one line per part number) with summed total quantity, as in 'Parça Takip'."""
        agg: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for r in self.rows:
            if r.depth == 0 or r.fastener_key:
                continue
            if r.in_purchased and not include_in_purchased:
                continue
            cur = agg.get(r.part_no)
            if cur is None:
                v = self.row_view(r)
                v["levels"] = [r.level]
                v["main_groups"] = [r.main_group]
                v["row_ids"] = [r.id]
                v["rows"] = 1
                agg[r.part_no] = v
                order.append(r.part_no)
                continue
            cur["levels"].append(r.level)
            cur["row_ids"].append(r.id)
            cur["rows"] += 1
            if r.main_group not in cur["main_groups"]:
                cur["main_groups"].append(r.main_group)
            if not r.in_purchased:
                if cur["in_purchased"]:
                    # first counted occurrence wins the display row
                    keep = {k: cur[k] for k in ("levels", "main_groups", "row_ids", "rows", "total_qty")}
                    cur.update(self.row_view(r))
                    cur.update(keep)
                    cur["total_qty"] = 0
                cur["total_qty"] += r.total_qty
            for k in ("material", "rev", "coating"):
                cur[k] = cur[k] or getattr(r, k)
        out = [agg[p] for p in order]
        for v in out:
            if v["in_purchased"]:
                v["counted"] = False
            v["main_group"] = ", ".join(v["main_groups"])
        return out

    def missing_views(self) -> list[dict[str, Any]]:
        info: dict[str, BomRow] = {}
        for r in self.rows:
            info.setdefault(r.part_no, r)
        out = []
        for m in self.missing:
            r = info.get(m.part_no)
            is_asm = bool(r and r.ext == "SLDASM")
            proc = self.procurement_of(m.part_no, r.procurement if r else "", is_asm,
                                       bool(r and r.is_purchased_assembly))
            status = derive_status(m.progress, proc, is_asm)
            out.append({
                "id": m.id, "part_no": m.part_no, "qty": m.qty, "reason": m.reason, "progress": m.progress,
                "note": m.note, "created_by": m.created_by, "created_at": m.created_at.isoformat() if m.created_at else None,
                "procurement": proc, "status": status, "status_color": COLORS["missing"],
                "material": r.material if r else "", "rev": r.rev if r else "", "in_bom": r is not None,
            })
        return out

    # ---------- fasteners ----------
    def fasteners(self) -> list[dict[str, Any]]:
        """Bağlantı Özeti: unique (type, std, size), counted rows only (not inside purchased assemblies)."""
        items: dict[str, dict[str, Any]] = {}
        for r in self.rows:
            if not r.fastener_key or r.in_purchased:
                continue
            it = items.get(r.fastener_key)
            group = ROOT_GROUP if r.depth <= 1 else (r.main_group or ROOT_GROUP)
            if it is None:
                fs = self.fastener_settings.get(r.fastener_key)
                it = items[r.fastener_key] = {
                    "key": r.fastener_key, "type": r.fastener_type, "desc": r.fastener_desc,
                    "std": r.fastener_std, "size": r.fastener_size, "total_qty": 0, "rows": 0,
                    "groups": [], "names": [],
                    "spare_pct": fs.spare_pct if fs else 10.0, "supplier": fs.supplier if fs else "",
                    "unit": fs.unit if fs else "Adet", "unit_price": fs.unit_price if fs else None,
                    "order_status": fs.order_status if fs else FASTENER_ORDER_STATUSES[0],
                    "note": fs.note if fs else "",
                }
            it["total_qty"] += r.total_qty
            it["rows"] += 1
            if group not in it["groups"]:
                it["groups"].append(group)
            if r.file_name not in it["names"]:
                it["names"].append(r.file_name)
        out = sorted(items.values(), key=fastener_sort_key)
        for it in out:
            spare = int(-(-it["total_qty"] * float(it["spare_pct"] or 0) // 100))  # ceil
            it["spare_qty"] = spare
            it["order_qty"] = it["total_qty"] + spare
            it["total_price"] = round(it["order_qty"] * it["unit_price"], 2) if it["unit_price"] is not None else None
            it["groups"] = sorted(it["groups"], key=lambda g: (g != ROOT_GROUP, tr_sort_key(g)))
            it["status_color"] = FASTENER_COLORS.get(it["order_status"], "")
        return out

    def fastener_rows(self) -> list[dict[str, Any]]:
        return [self.row_view(r) for r in self.rows if r.fastener_key]

    # ---------- dashboard ----------
    def dashboard(self) -> dict[str, Any]:
        parts = [p for p in self.parts(include_in_purchased=False)]
        imalat = [p for p in parts if p["status_kind"] == KIND_IMALAT]
        hazir = [p for p in parts if p["status_kind"] == KIND_HAZIR]
        montaj = [p for p in parts if p["status_kind"] == KIND_MONTAJ]
        no_temin = [p for p in parts if p["status"] == STATUS_NO_TEMIN]

        def count_by(items: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
            labels = list(dict.fromkeys(STATUS_MAP[kind].values()))
            return [{"status": s, "count": sum(1 for p in items if p["status"] == s),
                     "qty": sum(p["total_qty"] for p in items if p["status"] == s),
                     "color": COLORS.get(s, "")} for s in labels]

        produced = [p for p in imalat if p["progress"] == PROG_DONE]
        fast = self.fasteners()
        missing = self.missing_views()

        groups: dict[str, Counter] = defaultdict(Counter)
        for p in parts:
            if p["status_kind"] is None and p["status"] != STATUS_NO_TEMIN:
                continue
            for g in p["main_groups"]:
                groups[g]["total"] += 1
                groups[g][p["status"]] += 1
                if p["progress"] == PROG_DONE:
                    groups[g]["done"] += 1
        group_rows = []
        for g in sorted(groups, key=lambda g: (g != ROOT_GROUP, tr_sort_key(g))):
            c = groups[g]
            total = c.pop("total", 0)
            done = c.pop("done", 0)
            group_rows.append({"group": g, "total": total, "done": done,
                               "pct": round(100 * done / total, 1) if total else 0.0,
                               "by_status": dict(c)})

        all_status = list(dict.fromkeys([*STATUS_MAP[KIND_IMALAT].values(), *STATUS_MAP[KIND_HAZIR].values(),
                                         *STATUS_MAP[KIND_MONTAJ].values(), STATUS_NO_TEMIN]))
        total_parts = len(imalat) + len(hazir) + len(montaj)
        done_parts = sum(1 for p in imalat + hazir + montaj if p["progress"] == PROG_DONE)
        return {
            "version": {"id": self.version.id, "seq": self.version.seq, "filename": self.version.filename,
                        "approved_at": self.version.approved_at.isoformat() if self.version.approved_at else None}
            if self.version else None,
            "kpi": {
                "unique_parts": len(parts),
                "total_qty": sum(p["total_qty"] for p in parts),
                "imalat_count": len(imalat), "imalat_qty": sum(p["total_qty"] for p in imalat),
                "imalat_done": len(produced), "imalat_done_qty": sum(p["total_qty"] for p in produced),
                "imalat_todo": len(imalat) - len(produced),
                "imalat_todo_qty": sum(p["total_qty"] for p in imalat) - sum(p["total_qty"] for p in produced),
                "hazir_count": len(hazir), "hazir_qty": sum(p["total_qty"] for p in hazir),
                "hazir_delivered": sum(1 for p in hazir if p["progress"] == PROG_DONE),
                "montaj_count": len(montaj),
                "montaj_done": sum(1 for p in montaj if p["progress"] == PROG_DONE),
                "no_temin": len(no_temin),
                "fastener_unique": len(fast), "fastener_qty": sum(f["total_qty"] for f in fast),
                "fastener_delivered": sum(1 for f in fast if f["order_status"] == FASTENER_ORDER_STATUSES[2]),
                "missing_rows": len(missing), "missing_qty": sum(m["qty"] for m in missing),
                "imalat_no_drawing": sum(1 for p in imalat if not p["has_drawing"]),
                "new_parts": sum(1 for p in parts if p["is_new"]),
                "progress_pct": round(100 * done_parts / total_parts, 1) if total_parts else 0.0,
            },
            "imalat": count_by(imalat, KIND_IMALAT),
            "hazir": count_by(hazir, KIND_HAZIR),
            "montaj": count_by(montaj, KIND_MONTAJ),
            "groups": group_rows,
            "status_order": all_status,
            "status_colors": {s: COLORS.get(s, "") for s in all_status},
            "fastener_by_type": [{"type": t, "count": sum(1 for f in fast if f["type"] == t),
                                  "qty": sum(f["total_qty"] for f in fast if f["type"] == t)}
                                 for t in dict.fromkeys(f["type"] for f in fast)],
        }


def row_types() -> list[str]:
    return [ROW_PART, ROW_ASSEMBLY, ROW_FASTENER, ROW_IN_PURCHASED]


def temin_choices() -> list[str]:
    return [TEMIN_IMALAT, TEMIN_HAZIR, TEMIN_NONE]
