from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import Part, Project
from app.services import bomimport

F_1102 = "BOM_T01_0000_0000_2026-11-02.csv"
RULE_KEYS = ("name", "pattern", "type", "desc", "std", "size", "d", "l", "maps", "priority", "active")


def _project_1102(data_file, prefix: str) -> int:
    """Project with the 11-02 BOM approved directly through bomimport."""
    from app.db import SessionLocal
    with SessionLocal() as db:
        p = db.scalar(select(Part).where(Part.part_no == "TSDacikboy"))
        if p is None:
            db.add(Part(part_no="TSDacikboy", is_purchased_assembly=True))
        else:
            p.is_purchased_assembly = True
        db.flush()
        project = Project(name=f"{prefix} {uuid.uuid4().hex[:8]}")
        db.add(project)
        db.flush()
        v = bomimport.upload_bom(db, project, F_1102, data_file(F_1102).read_bytes(), None)
        bomimport.approve(db, v, None)
        db.commit()
        return project.id


def test_fastener_summary_rows_settings(client, admin_headers, data_file):
    h = admin_headers
    pid = _project_1102(data_file, "BE fastener")
    r = client.get(f"/api/projects/{pid}/fasteners", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["totals"]["unique"] == 43 and len(body["items"]) == 43
    assert body["totals"]["total_qty"] == 1006
    assert body["totals"]["order_qty"] >= 1006
    assert "Sipariş Verilmedi" in body["statuses"]

    rows = client.get(f"/api/projects/{pid}/fasteners/rows", headers=h).json()
    assert rows and all(x["fastener"] for x in rows)

    key = body["items"][0]["key"]
    r = client.put(f"/api/projects/{pid}/fasteners/settings", headers=h,
                   json={"keys": [key], "spare_pct": 0, "unit_price": 2.5, "order_status": "Sipariş Verildi",
                         "supplier": "Civata A.Ş."})
    assert r.status_code == 200, r.text
    it = r.json()["items"][0]
    assert it["order_status"] == "Sipariş Verildi" and it["supplier"] == "Civata A.Ş."
    assert it["order_qty"] == it["total_qty"] and it["total_price"] == round(it["total_qty"] * 2.5, 2)
    stored = client.get(f"/api/projects/{pid}/fasteners/settings", headers=h).json()
    assert [s["key"] for s in stored] == [key]

    bad = client.put(f"/api/projects/{pid}/fasteners/settings", headers=h,
                     json={"keys": [key], "order_status": "Yok"})
    assert bad.status_code == 400
    bad = client.put(f"/api/projects/{pid}/fasteners/settings", headers=h,
                     json={"keys": ["yok|yok|yok"], "note": "x"})
    assert bad.status_code == 400 and "bulunamadı" in bad.json()["detail"]
    from app.db import SessionLocal
    from app.models import AuditLog
    with SessionLocal() as db:
        logs = db.scalars(select(AuditLog).where(AuditLog.project_id == pid, AuditLog.entity == "fastener")).all()
    assert {x.field for x in logs} >= {"order_status", "unit_price", "supplier"}


def test_fastener_rules_crud_and_test(client, admin_headers):
    h = admin_headers
    before = client.get("/api/fastener-rules", headers=h).json()
    rule = {"name": f"Test pim {uuid.uuid4().hex[:6]}", "pattern": r"^PIM\s*(\d+)x(\d+)$", "type": "Pim",
            "desc": "Pim {1}x{2}", "std": "ISO 2338", "size": "{1}x{2}", "d": "{1}", "l": "{2}", "priority": 5}
    r = client.post("/api/fastener-rules", json=rule, headers=h)
    assert r.status_code == 201, r.text
    rid = r.json()["id"]

    bad = client.post("/api/fastener-rules", json={**rule, "pattern": "(unclosed"}, headers=h)
    assert bad.status_code == 400 and "regex" in bad.json()["detail"].lower()
    bad = client.post("/api/fastener-rules", json={**rule, "size": "{3}"}, headers=h)
    assert bad.status_code == 400 and "grubu" in bad.json()["detail"]
    bad = client.post("/api/fastener-rules", json={**rule, "std": "{1|olmayan}"}, headers=h)
    assert bad.status_code == 400 and "eşleme" in bad.json()["detail"]

    t = client.post("/api/fastener-rules/test", json={"text": "PIM 6x20\nbaşka bir şey", "rule": rule}, headers=h)
    assert t.status_code == 200, t.text
    res = t.json()
    assert res["matched"] == 1 and res["results"][0]["match"]["size"] == "6x20"
    t = client.post("/api/fastener-rules/test", json={"text": "PIM 8x30"}, headers=h).json()
    assert t["results"][0]["match"]["type"] == "Pim"

    r = client.put(f"/api/fastener-rules/{rid}", json={**rule, "active": False}, headers=h)
    assert r.status_code == 200 and r.json()["active"] is False

    ids = [x["id"] for x in client.get("/api/fastener-rules", headers=h).json()]
    ids = [rid] + [i for i in ids if i != rid]
    r = client.post("/api/fastener-rules/reorder", json={"ids": ids}, headers=h)
    assert r.status_code == 200 and r.json()[0]["id"] == rid and r.json()[0]["priority"] == 10
    # restore original priorities
    for x in before:
        client.put(f"/api/fastener-rules/{x['id']}", json={k: x[k] for k in RULE_KEYS},
                   headers=h)

    assert client.delete(f"/api/fastener-rules/{rid}", headers=h).status_code == 200
    assert client.delete(f"/api/fastener-rules/{rid}", headers=h).status_code == 404
    assert client.post("/api/fastener-rules/test", json={"text": "  "}, headers=h).status_code == 400


def test_rule_change_retags_current_bom(client, admin_headers, data_file):
    """Adding or deleting a rule re-tags the approved BOM, so the summary follows the rules."""
    import re

    from app.db import SessionLocal
    from app.models import BomRow
    h = admin_headers
    pid = _project_1102(data_file, "BE retag")
    with SessionLocal() as db:
        vid = db.get(Project, pid).current_version_id
        part = db.scalar(select(BomRow).where(BomRow.version_id == vid, BomRow.row_type == "Parça",
                                              BomRow.ext == "SLDPRT").order_by(BomRow.seq))
        name, part_no = part.file_name, part.part_no
    rule = {"name": f"Retag {uuid.uuid4().hex[:6]}", "pattern": f"^{re.escape(part_no)}$", "type": "Pim",
            "desc": "Özel pim", "std": "", "size": "", "d": "", "l": "", "priority": 1}
    rid = client.post("/api/fastener-rules", json=rule, headers=h).json()["id"]
    try:
        body = client.get(f"/api/projects/{pid}/fasteners", headers=h).json()
        assert body["totals"]["unique"] == 44
        with SessionLocal() as db:
            row = db.scalar(select(BomRow).where(BomRow.version_id == vid, BomRow.file_name == name))
            assert row.row_type == "Bağlantı Elemanı" and row.fastener_type == "Pim"
    finally:
        assert client.delete(f"/api/fastener-rules/{rid}", headers=h).status_code == 200
    body = client.get(f"/api/projects/{pid}/fasteners", headers=h).json()
    assert body["totals"]["unique"] == 43 and body["totals"]["total_qty"] == 1006
