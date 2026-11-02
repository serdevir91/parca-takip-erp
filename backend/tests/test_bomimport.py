from sqlalchemy import select

from app.core.status import PROG_RUN
from app.models import Part, PartAlias, Project, Tracking
from app.services import bomimport


def _read(name: str) -> bytes:
    from pathlib import Path
    return (Path(__file__).parent / "data" / name).read_bytes()


def _db():
    from app.db import SessionLocal
    return SessionLocal()


def _ensure_purchased(db):
    p = db.scalar(select(Part).where(Part.part_no == "TSDacikboy"))
    if p is None:
        db.add(Part(part_no="TSDacikboy", is_purchased_assembly=True))
    else:
        p.is_purchased_assembly = True
    db.flush()


def test_upload_approve_undo(client):
    db = _db()
    try:
        _ensure_purchased(db)
        project = Project(name="T01 import test")
        db.add(project)
        db.flush()

        v1 = bomimport.upload_bom(db, project, "BOM_T01_0000_0000_2026-10-31.csv",
                                  _read("BOM_T01_0000_0000_2026-10-31.csv"), None)
        assert v1.status == "pending" and v1.compare_json["first"]
        bomimport.approve(db, v1, None)
        assert project.current_version_id == v1.id
        assert project.root_part_no == "T01_0000_0000"
        tracked = {t.part_no: t for t in db.scalars(select(Tracking).where(Tracking.project_id == project.id))}
        assert tracked and not any(t.is_new for t in tracked.values())

        removed_candidate = next(p for p in tracked if p.startswith("T01_3000"))
        tracked[removed_candidate].progress = PROG_RUN
        db.flush()

        v2 = bomimport.upload_bom(db, project, "BOM_T01_0000_0000_2026-11-02.csv",
                                  _read("BOM_T01_0000_0000_2026-11-02.csv"), None)
        s, c = v2.stats_json, v2.compare_json
        assert s["rows"] == 450 and s["fastener_rows"] == 62
        assert s["fastener_unique"] == 43 and s["fastener_total"] == 1006
        assert s["in_purchased_rows"] == 60
        assert (c["fastener_total_old"], c["fastener_total_new"]) == (1642, 1006)
        assert c["fastener_big_drop"]
        assert any(p.startswith("T01_3000") for p in c["removed"])
        assert any(p.startswith("T01_6000_0000") for p in c["added"])
        kinds = {w["kind"] for w in c["warnings"]}
        assert {"removed_with_progress", "fastener_big_drop"} <= kinds

        bomimport.approve(db, v2, None)
        tracked = {t.part_no: t for t in db.scalars(select(Tracking).where(Tracking.project_id == project.id))}
        assert tracked[removed_candidate].archived
        assert tracked[removed_candidate].progress == PROG_RUN
        new_parts = [p for p in c["added"] if p in tracked]
        assert new_parts and all(tracked[p].is_new for p in new_parts)

        bomimport.undo_last(db, project, None)
        assert v2.status == "undone" and project.current_version_id == v1.id
        tracked = {t.part_no: t for t in db.scalars(select(Tracking).where(Tracking.project_id == project.id))}
        assert not tracked[removed_candidate].archived
        assert not any(p in tracked for p in new_parts)

        try:
            bomimport.approve(db, v2, None)
            raise AssertionError("approving an undone version must fail")
        except bomimport.BomImportError:
            pass
    finally:
        db.rollback()
        db.close()


def test_alias_carries_status(client):
    db = _db()
    try:
        project = Project(name="Alias test")
        db.add(project)
        db.flush()
        base = _read("BOM_T01_0004_0000_v1.csv")
        v1 = bomimport.upload_bom(db, project, "v1.csv", base, None)
        bomimport.approve(db, v1, None)
        renamed = base.decode("utf-8-sig").replace("T01_0004_0005.SLDPRT", "T01_0004_0005-P.SLDPRT")
        v = bomimport.upload_bom(db, project, "v1p.csv", renamed.encode("utf-8"), None)
        sugg = v.compare_json["alias_suggestions"]
        assert sugg, "expected a suffix-only alias suggestion"
        pair = sugg[0]
        t_old = db.scalar(select(Tracking).where(Tracking.project_id == project.id,
                                                 Tracking.part_no == pair["removed"]))
        t_old.note = "taşınmalı"
        db.flush()
        bomimport.approve(db, v, None, [{"removed": pair["removed"], "added": pair["added"]}])
        t_new = db.scalar(select(Tracking).where(Tracking.project_id == project.id,
                                                 Tracking.part_no == pair["added"]))
        assert t_new.note == "taşınmalı" and not t_new.archived and not t_new.is_new
        bomimport.undo_last(db, project, None)
        t_back = db.scalar(select(Tracking).where(Tracking.project_id == project.id,
                                                  Tracking.part_no == pair["removed"]))
        assert t_back.note == "taşınmalı"
        assert db.scalar(select(PartAlias).where(PartAlias.alias == pair["removed"])) is None
    finally:
        db.rollback()
        db.close()
