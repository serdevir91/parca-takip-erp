"""BOM upload, compare, approve, reject and undo (spec 4.5).

Flow: upload_bom() parses the CSV, stores the file and a *pending* BomVersion
with its rows and the comparison against the current version. approve() makes
it current and carries tracking over (keeps existing, adds new parts with the
"Yeni" flag, archives removed ones, applies accepted aliases). undo_last()
restores the tracking snapshot taken at approval.
"""
from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.bomparse import (ROW_ASSEMBLY, ROW_FASTENER, ROW_IN_PURCHASED, ROW_PART, ParsedBom,
                             parse_bom)
from ..core.compare import CompareResult, compare_boms
from ..core.normalize import safe_filename
from ..core.status import PROG_DONE, PROG_WAIT
from ..models import BomRow, BomVersion, MissingRow, Part, PartAlias, Project, Tracking, User, utcnow
from . import audit
from .settings import big_drop_ratio, buy_temins, fastener_matcher, part_no_patterns, purchased_assemblies
from .state import ProjectView

TRACKING_FIELDS = ("part_no", "procurement_override", "progress", "note", "t35_note", "manufacturer",
                   "material_status", "is_new", "archived", "updated_by")


class BomImportError(ValueError):
    """User-facing error (Turkish message); the API returns it as 400."""


# ---------- helpers ----------
def _trackable_parts(bom: ParsedBom) -> list[str]:
    """Unique non-fastener part numbers below the root, in BOM order."""
    seen: dict[str, None] = {}
    for r in bom.non_fastener_rows:
        if r.depth > 0:
            seen.setdefault(r.part_no, None)
    return list(seen)


def bom_stats(bom: ParsedBom) -> dict[str, Any]:
    fr = bom.fastener_rows
    totals = bom.fastener_totals()
    return {
        "root_part_no": bom.root_part_no,
        "rows": len(bom.rows),
        "non_fastener_rows": len(bom.non_fastener_rows),
        "fastener_rows": len(fr),
        "fastener_unique": len(totals),
        "fastener_total": sum(totals.values()),
        "in_purchased_rows": sum(1 for r in bom.rows if r.in_purchased),
        "parts": len(_trackable_parts(bom)),
        "assemblies": len({r.part_no for r in bom.non_fastener_rows if r.depth > 0 and r.is_assembly}),
        "nonstandard": sum(1 for r in bom.rows if r.nonstandard),
        "parse_warnings": list(bom.warnings),
    }


def compare_json(cmp: CompareResult | None, tracking: dict[str, Tracking], ratio: float) -> dict[str, Any]:
    """Serialisable comparison plus the warnings shown before approval."""
    if cmp is None:
        return {"first": True, "warnings": [], "added": [], "removed": [], "rev_changed": [],
                "material_changed": [], "procurement_changed": [], "qty_changed": [],
                "fastener_changes": [], "fastener_total_old": 0, "fastener_total_new": 0,
                "alias_suggestions": [], "fastener_big_drop": False, "is_empty": True}
    d = asdict(cmp)
    for fc, obj in zip(d["fastener_changes"], cmp.fastener_changes):
        fc["delta"] = obj.delta
    old, new = cmp.fastener_total_old, cmp.fastener_total_new
    big_drop = old > 0 and new < old and (old - new) / old >= ratio
    warnings: list[dict[str, str]] = []
    for pno in cmp.removed:
        t = tracking.get(pno)
        if t and t.progress != PROG_WAIT:
            warnings.append({"part_no": pno, "kind": "removed_with_progress", "severity": "error",
                             "message": f"{pno}: ilerleme kaydı olan parça BOM'dan kalktı ({t.progress})."})
    for ch in cmp.rev_changed:
        t = tracking.get(ch.part_no)
        if t and t.progress == PROG_DONE:
            warnings.append({"part_no": ch.part_no, "kind": "rev_after_done", "severity": "warning",
                             "message": f"{ch.part_no}: revizyon {ch.old or '(boş)'} → {ch.new or '(boş)'}; "
                                        "eski revizyonla üretilmiş olabilir."})
    if big_drop:
        warnings.append({"part_no": "", "kind": "fastener_big_drop", "severity": "warning",
                         "message": f"Bağlantı elemanı toplam adedi {old} → {new} düştü "
                                    f"(%{round((old - new) * 100 / old)})."})
    d.update(first=False, warnings=warnings, fastener_big_drop=big_drop, is_empty=cmp.is_empty)
    return d


def _current_parsed(db: Session, project: Project) -> ParsedBom | None:
    if not project.current_version_id:
        return None
    return ProjectView.load(db, project).to_parsed()


def _tracking_map(db: Session, project_id: int) -> dict[str, Tracking]:
    return {t.part_no: t for t in db.scalars(select(Tracking).where(Tracking.project_id == project_id))}


def _version_parsed(db: Session, project: Project, version: BomVersion) -> ParsedBom:
    return ProjectView.load(db, project, version.id).to_parsed()


def _row_model(version_id: int, r) -> BomRow:
    fm = r.fastener
    return BomRow(
        version_id=version_id, seq=r.seq, level=r.level, depth=r.depth, parent_level=r.parent_level,
        file_name=r.file_name, part_no=r.part_no, ext=r.ext, qty=r.qty, multiplier=r.multiplier,
        total_qty=r.total_qty, material=r.material, weight=r.weight, rev=r.rev, procurement=r.procurement,
        coating=r.coating, parent_part_no=r.parent_part_no or None, main_group=r.main_group,
        in_purchased=r.in_purchased, is_purchased_assembly=r.is_purchased_assembly,
        nonstandard=r.nonstandard, row_type=r.row_type,
        fastener_key=fm.key if fm else None, fastener_type=fm.type if fm else None,
        fastener_desc=fm.desc if fm else None, fastener_std=fm.std if fm else None,
        fastener_size=fm.size if fm else None)


def retag_fasteners(db: Session) -> int:
    """Re-run the fastener rules over the live BOM versions after a rule change.

    Only the current version of each project and pending uploads are touched; older approved
    versions stay as they were approved. Returns the number of rows whose tagging changed.
    """
    db.flush()  # the session may not autoflush; the matcher must see the rule change
    matcher = fastener_matcher(db)
    pn_rx = [re.compile(p) for p in part_no_patterns(db)]
    live = select(Project.current_version_id).where(Project.current_version_id.is_not(None))
    vids = select(BomVersion.id).where((BomVersion.status == "pending") | BomVersion.id.in_(live))
    changed = 0
    for r in db.scalars(select(BomRow).where(BomRow.version_id.in_(vids))):
        fm = matcher.match(r.file_name) if r.ext == "SLDPRT" else None
        new = {"fastener_key": fm.key if fm else None, "fastener_type": fm.type if fm else None,
               "fastener_desc": fm.desc if fm else None, "fastener_std": fm.std if fm else None,
               "fastener_size": fm.size if fm else None,
               "nonstandard": (not fm and not r.in_purchased and r.depth > 0
                               and not any(rx.match(r.part_no) for rx in pn_rx)),
               "row_type": (ROW_IN_PURCHASED if r.in_purchased else ROW_FASTENER if fm
                            else ROW_ASSEMBLY if r.ext == "SLDASM" else ROW_PART)}
        if any(getattr(r, k) != v for k, v in new.items()):
            for k, v in new.items():
                setattr(r, k, v)
            changed += 1
    db.flush()
    return changed


# ---------- upload ----------
def upload_bom(db: Session, project: Project, filename: str, data: bytes, user: User | None,
               note: str = "") -> BomVersion:
    try:
        parsed = parse_bom(data, purchased_assemblies=purchased_assemblies(db), matcher=fastener_matcher(db),
                           part_no_patterns=part_no_patterns(db), buy_temins=buy_temins(db))
    except Exception as e:  # noqa: BLE001 - any parse failure is a bad file for the user
        raise BomImportError(f"BOM dosyası okunamadı: {e}") from e
    if not parsed.rows:
        raise BomImportError("BOM dosyasında satır bulunamadı.")

    seq = (db.scalar(select(func.max(BomVersion.seq)).where(BomVersion.project_id == project.id)) or 0) + 1
    folder = get_settings().bom_dir / str(project.id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{seq:03d}_{safe_filename(filename) or 'bom.csv'}"
    path.write_bytes(data)

    cmp = None
    old = _current_parsed(db, project)
    if old is not None:
        cmp = compare_boms(old, parsed)
    stats = bom_stats(parsed)
    cj = compare_json(cmp, _tracking_map(db, project.id), big_drop_ratio(db))
    if project.root_part_no and parsed.root_part_no and parsed.root_part_no != project.root_part_no:
        cj["warnings"].insert(0, {"part_no": parsed.root_part_no, "kind": "root_mismatch", "severity": "error",
                                  "message": f"Dosyanın ana montajı {parsed.root_part_no}, proje ise "
                                             f"{project.root_part_no}. Doğru proje mi?"})

    v = BomVersion(project_id=project.id, seq=seq, filename=filename, file_path=str(path),
                   uploaded_by=user.username if user else "", note=note, status="pending",
                   previous_version_id=project.current_version_id, compare_json=cj, stats_json=stats)
    db.add(v)
    db.flush()
    db.add_all(_row_model(v.id, r) for r in parsed.rows)
    audit.record(db, user, "bom_version", v.id, "upload", None, filename, project.id, action="create")
    db.flush()
    return v


def refresh_compare(db: Session, project: Project, version: BomVersion) -> None:
    """Recompute the comparison when the current version changed after upload."""
    old = _current_parsed(db, project)
    cmp = compare_boms(old, _version_parsed(db, project, version)) if old is not None else None
    version.compare_json = compare_json(cmp, _tracking_map(db, project.id), big_drop_ratio(db))
    version.previous_version_id = project.current_version_id


# ---------- approve ----------
def approve(db: Session, version: BomVersion, user: User | None,
            alias_accept: list[dict[str, str]] | None = None) -> BomVersion:
    """alias_accept: [{"removed": old_no, "added": new_no}] pairs the user confirmed as the same part."""
    if version.status != "pending":
        raise BomImportError("Sadece bekleyen BOM sürümü onaylanabilir.")
    project = db.get(Project, version.project_id)
    if version.previous_version_id != project.current_version_id:
        refresh_compare(db, project, version)
    cj = version.compare_json or {}
    removed, added = set(cj.get("removed") or []), set(cj.get("added") or [])
    pairs = []
    for p in alias_accept or []:
        old_no, new_no = p.get("removed", ""), p.get("added", "")
        if old_no not in removed or new_no not in added:
            raise BomImportError(f"Eşleştirme geçersiz: {old_no} → {new_no}")
        pairs.append((old_no, new_no))

    tracking = _tracking_map(db, project.id)
    missing = list(db.scalars(select(MissingRow).where(MissingRow.project_id == project.id)))
    undo: dict[str, Any] = {
        "previous_version_id": project.current_version_id,
        "root_part_no": project.root_part_no,
        "tracking": [{f: getattr(t, f) for f in TRACKING_FIELDS} for t in tracking.values()],
        "missing_part_no": {str(m.id): m.part_no for m in missing},
        "aliases_created": [], "aliases_replaced": [], "parts_created": [],
    }
    first = project.current_version_id is None
    uname = user.username if user else ""

    # Accepted aliases: move tracking and missing rows to the new number
    for old_no, new_no in pairs:
        existing = db.scalar(select(PartAlias).where(PartAlias.alias == old_no))
        if existing:
            undo["aliases_replaced"].append({"id": existing.id, "part_no": existing.part_no})
            existing.part_no = new_no
        else:
            a = PartAlias(alias=old_no, part_no=new_no, created_by=uname)
            db.add(a)
            db.flush()
            undo["aliases_created"].append(a.id)
        t_old, t_new = tracking.pop(old_no, None), tracking.get(new_no)
        if t_old is not None:
            if t_new is not None:
                db.delete(t_new)
                db.flush()
            t_old.part_no = new_no
            tracking[new_no] = t_old
        for m in missing:
            if m.part_no == old_no:
                m.part_no = new_no
        removed.discard(old_no)
        added.discard(new_no)
        audit.record(db, user, "part", new_no, "alias", old_no, new_no, project.id)

    # Old "Yeni" flags last until the next version
    for t in tracking.values():
        if t.is_new:
            t.is_new = False
    parts_now = _trackable_parts(_version_parsed(db, project, version))
    known_parts = set(db.scalars(select(Part.part_no).where(Part.part_no.in_(parts_now)))) if parts_now else set()
    for pno in parts_now:
        if pno not in known_parts:
            db.add(Part(part_no=pno))
            undo["parts_created"].append(pno)
        t = tracking.get(pno)
        if t is None:
            tracking[pno] = Tracking(project_id=project.id, part_no=pno, progress=PROG_WAIT,
                                     is_new=not first and pno in added, updated_by=uname)
            db.add(tracking[pno])
        elif t.archived:
            t.archived = False
            t.is_new = not first
    current = set(parts_now)
    for pno, t in tracking.items():
        if pno not in current and not t.archived:
            t.archived = True
            audit.record(db, user, "tracking", pno, "archived", False, True, project.id)

    version.undo_json = undo
    version.status = "approved"
    version.approved_by = uname
    version.approved_at = utcnow()
    project.current_version_id = version.id
    if not project.root_part_no:
        project.root_part_no = (version.stats_json or {}).get("root_part_no") or ""
    audit.record(db, user, "bom_version", version.id, "status", "pending", "approved", project.id)
    db.flush()
    return version


def reject(db: Session, version: BomVersion, user: User | None) -> BomVersion:
    if version.status != "pending":
        raise BomImportError("Sadece bekleyen BOM sürümü reddedilebilir.")
    version.status = "rejected"
    audit.record(db, user, "bom_version", version.id, "status", "pending", "rejected", version.project_id)
    db.flush()
    return version


def delete_version(db: Session, version: BomVersion, user: User | None) -> str:
    """Remove a rejected or undone version with its rows. Returns the stored file to delete after the commit."""
    if version.status not in ("rejected", "undone"):
        raise BomImportError("Sadece reddedilen veya geri alınan BOM sürümü silinebilir.")
    audit.record(db, user, "bom_version", version.id, "deleted", f"#{version.seq} {version.filename}", None,
                 version.project_id, action="delete")
    path = version.file_path
    db.delete(version)
    db.flush()
    return path


def remove_stored_file(path: str) -> None:
    """Delete an uploaded BOM file; paths outside the BOM folder are left alone."""
    if not path:
        return
    f = Path(path).resolve()
    if f.is_relative_to(get_settings().bom_dir.resolve()):
        f.unlink(missing_ok=True)


# ---------- undo ----------
def undo_last(db: Session, project: Project, user: User | None) -> BomVersion:
    """Revert the current (last approved) version and restore tracking as it was before it.
    Edits made after that approval are lost; the API should confirm with the user."""
    version = db.get(BomVersion, project.current_version_id) if project.current_version_id else None
    if version is None or version.status != "approved" or not version.undo_json:
        raise BomImportError("Geri alınacak onaylı BOM yüklemesi yok.")
    u = version.undo_json
    for t in db.scalars(select(Tracking).where(Tracking.project_id == project.id)):
        db.delete(t)
    db.flush()
    for d in u.get("tracking", []):
        db.add(Tracking(project_id=project.id, **d))
    for mid, pno in (u.get("missing_part_no") or {}).items():
        m = db.get(MissingRow, int(mid))
        if m is not None:
            m.part_no = pno
    for aid in u.get("aliases_created", []):
        a = db.get(PartAlias, aid)
        if a is not None:
            db.delete(a)
    for rep in u.get("aliases_replaced", []):
        a = db.get(PartAlias, rep["id"])
        if a is not None:
            a.part_no = rep["part_no"]
    # Parts created by this approval stay unless no other version uses them
    for pno in u.get("parts_created", []):
        used = db.scalar(select(func.count()).select_from(BomRow).join(BomVersion)
                         .where(BomRow.part_no == pno, BomVersion.status == "approved",
                                BomVersion.id != version.id))
        if not used:
            p = db.scalar(select(Part).where(Part.part_no == pno))
            if p is not None and not p.is_purchased_assembly:
                db.delete(p)
    project.current_version_id = u.get("previous_version_id")
    project.root_part_no = u.get("root_part_no") or project.root_part_no
    version.status = "undone"
    audit.record(db, user, "bom_version", version.id, "status", "approved", "undone", project.id)
    db.flush()
    return version
