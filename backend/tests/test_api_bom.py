from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import func, select

from app.core.status import PROG_RUN
from app.models import Part

F1031 = "BOM_T01_0000_0000_2026-10-31.csv"
F1102 = "BOM_T01_0000_0000_2026-11-02.csv"


def _ensure_purchased() -> None:
    from app.db import SessionLocal
    with SessionLocal() as db:
        p = db.scalar(select(Part).where(Part.part_no == "TSDacikboy"))
        if p is None:
            db.add(Part(part_no="TSDacikboy", is_purchased_assembly=True))
        else:
            p.is_purchased_assembly = True
        db.commit()


def _project(client, headers, prefix: str) -> int:
    r = client.post("/api/projects", json={"name": f"{prefix} {uuid.uuid4().hex[:8]}"}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _upload(client, headers, pid: int, path, name: str | None = None, note: str = ""):
    with open(path, "rb") as f:
        return client.post(f"/api/projects/{pid}/bom/upload", headers=headers, data={"note": note},
                           files={"file": (name or path.name, f, "text/csv")})


def test_bom_flow(client, admin_headers, data_file):
    _ensure_purchased()
    h = admin_headers
    pid = _project(client, h, "BOM akış")

    r = _upload(client, h, pid, data_file(F1031), note="ilk")
    assert r.status_code == 201, r.text
    v1 = r.json()
    assert v1["status"] == "pending" and v1["compare"]["first"] and v1["note"] == "ilk"
    r = client.post(f"/api/projects/{pid}/bom/versions/{v1['id']}/approve", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved" and r.json()["is_current"]
    proj = client.get(f"/api/projects/{pid}", headers=h).json()
    assert proj["current_version_id"] == v1["id"] and proj["root_part_no"] == "T01_0000_0000"
    assert proj["tracked_parts"] > 0

    # Give a part that will be removed some progress, through the API
    parts = client.get(f"/api/projects/{pid}/parts", headers=h).json()["rows"]
    cand = next(p["part_no"] for p in parts if p["part_no"].startswith("T01_3000"))
    r = client.patch(f"/api/projects/{pid}/parts/{cand}", json={"progress": PROG_RUN}, headers=h)
    assert r.status_code == 200 and r.json()["part"]["progress"] == PROG_RUN

    r = _upload(client, h, pid, data_file(F1102))
    assert r.status_code == 201, r.text
    v2 = r.json()
    s, c = v2["stats"], v2["compare"]
    assert s["rows"] == 450 and s["fastener_rows"] == 62
    assert s["fastener_unique"] == 43 and s["fastener_total"] == 1006 and s["in_purchased_rows"] == 60
    assert (c["fastener_total_old"], c["fastener_total_new"]) == (1642, 1006)
    assert c["fastener_big_drop"]
    assert cand in c["removed"]
    assert any(p.startswith("T01_3000") for p in c["removed"])
    added = [p for p in c["added"] if p.startswith("T01_6000_0000")]
    assert added
    kinds = {w["kind"] for w in v2["warnings"]}
    assert {"removed_with_progress", "fastener_big_drop"} <= kinds
    assert v2["summary"]["removed"] == len(c["removed"])

    listed = client.get(f"/api/projects/{pid}/bom/versions", headers=h).json()
    assert [v["id"] for v in listed] == [v2["id"], v1["id"]]
    detail = client.get(f"/api/projects/{pid}/bom/versions/{v2['id']}", headers=h).json()
    assert detail["compare"]["fastener_total_new"] == 1006
    rows = client.get(f"/api/projects/{pid}/bom/versions/{v2['id']}/rows", headers=h).json()
    assert rows["count"] == 450 and len(rows["rows"]) == 450
    f = client.get(f"/api/projects/{pid}/bom/versions/{v2['id']}/file", headers=h)
    assert f.status_code == 200 and len(f.content) > 1000

    r = client.post(f"/api/projects/{pid}/bom/versions/{v2['id']}/approve", json={"alias_accept": []},
                    headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["can_undo"]
    arch = client.get(f"/api/projects/{pid}/parts", params={"archived": True}, headers=h).json()
    assert cand in [p["part_no"] for p in arch["rows"]]
    new = client.get(f"/api/projects/{pid}/parts", params={"is_new": True}, headers=h).json()
    assert set(added) & {p["part_no"] for p in new["rows"]}

    # Approving again fails cleanly
    again = client.post(f"/api/projects/{pid}/bom/versions/{v2['id']}/approve", headers=h)
    assert again.status_code == 400

    r = client.post(f"/api/projects/{pid}/bom/undo", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["undone"]["status"] == "undone" and r.json()["current"]["id"] == v1["id"]
    parts = {p["part_no"]: p for p in client.get(f"/api/projects/{pid}/parts", headers=h).json()["rows"]}
    assert parts[cand]["progress"] == PROG_RUN
    assert not set(added) & set(parts)


def test_bom_reject_and_errors(client, admin_headers, data_file):
    h = admin_headers
    pid = _project(client, h, "BOM ret")
    bad = client.post(f"/api/projects/{pid}/bom/upload", headers=h,
                      files={"file": ("bom.xlsx", b"x", "application/octet-stream")})
    assert bad.status_code == 400
    empty = client.post(f"/api/projects/{pid}/bom/upload", headers=h, files={"file": ("bom.csv", b"", "text/csv")})
    assert empty.status_code == 400
    assert client.post(f"/api/projects/{pid}/bom/undo", headers=h).status_code == 400

    v = _upload(client, h, pid, data_file("BOM_T01_0004_0000_v1.csv")).json()
    r = client.post(f"/api/projects/{pid}/bom/versions/{v['id']}/reject", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert client.post(f"/api/projects/{pid}/bom/versions/{v['id']}/approve", headers=h).status_code == 400
    assert client.get(f"/api/projects/{pid}/bom/versions/999999", headers=h).status_code == 404


def test_aliases(client, admin_headers, data_file):
    h = admin_headers
    pid = _project(client, h, "Takma ad")
    for name in ("v1", "v2"):
        v = _upload(client, h, pid, data_file(f"BOM_T01_0004_0000_{name}.csv")).json()
        assert client.post(f"/api/projects/{pid}/bom/versions/{v['id']}/approve", headers=h).status_code == 200
    old_no, new_no = "Part1-1", "T01_0004_0033"
    assert client.patch(f"/api/projects/{pid}/parts/{old_no}", json={"note": "eski not"},
                        headers=h).status_code == 200
    v = _upload(client, h, pid, data_file("BOM_T01_0004_0000_v3.csv")).json()
    assert client.post(f"/api/projects/{pid}/bom/versions/{v['id']}/approve", headers=h).status_code == 200

    assert client.post(f"/api/projects/{pid}/aliases", json={"alias": new_no, "part_no": new_no},
                       headers=h).status_code == 400
    # A number still in the current BOM cannot become an alias (its row would lose its tracking)
    live = client.post(f"/api/projects/{pid}/aliases", json={"alias": "T01_0004_0001", "part_no": new_no},
                       headers=h)
    assert live.status_code == 400
    r = client.post(f"/api/projects/{pid}/aliases", json={"alias": old_no, "part_no": new_no}, headers=h)
    assert r.status_code == 201, r.text
    a = r.json()
    try:
        assert a["state_moved"]
        dup = client.post(f"/api/projects/{pid}/aliases", json={"alias": old_no, "part_no": "X"}, headers=h)
        assert dup.status_code == 400
        listed = client.get(f"/api/projects/{pid}/aliases", headers=h).json()
        assert a["id"] in [x["id"] for x in listed]
        # Old number resolves to the new one: tracking moved there and the new part is live
        d = client.get(f"/api/projects/{pid}/parts/{old_no}", headers=h).json()
        assert d["part"]["part_no"] == new_no and d["part"]["note"] == "eski not" and old_no in d["aliases"]
        assert d["part"]["archived"] is False
    finally:
        assert client.delete(f"/api/projects/{pid}/aliases/{a['id']}", headers=h).status_code == 200
    assert client.delete(f"/api/projects/{pid}/aliases/{a['id']}", headers=h).status_code == 404


def test_version_scoping(client, admin_headers, data_file):
    h = admin_headers
    p1, p2 = _project(client, h, "Kapsam A"), _project(client, h, "Kapsam B")
    v = _upload(client, h, p1, data_file("BOM_T01_0004_0000_v1.csv")).json()
    for url in (f"/api/projects/{p2}/parts?version_id={v['id']}",
                f"/api/projects/{p2}/parts/T01_0004_0001?version_id={v['id']}",
                f"/api/projects/{p2}/dashboard?version_id={v['id']}",
                f"/api/projects/{p2}/bom/versions/{v['id']}"):
        assert client.get(url, headers=h).status_code == 404, url
    assert client.post(f"/api/projects/{p2}/bom/versions/{v['id']}/approve", headers=h).status_code == 404
    # Archived project: no new uploads, pending versions cannot be approved
    assert client.delete(f"/api/projects/{p1}", headers=h).status_code == 200
    assert client.post(f"/api/projects/{p1}/bom/versions/{v['id']}/approve", headers=h).status_code == 400
    assert _upload(client, h, p1, data_file("BOM_T01_0004_0000_v2.csv")).status_code == 400


def test_delete_rejected_version(client, admin_headers, data_file):
    h = admin_headers
    pid = _project(client, h, "BOM sil")
    v1 = _upload(client, h, pid, data_file("BOM_T01_0004_0000_v1.csv")).json()
    url = f"/api/projects/{pid}/bom/versions/{v1['id']}"
    assert client.delete(url, headers=h).status_code == 400  # pending
    client.post(f"{url}/approve", headers=h)
    assert client.delete(url, headers=h).status_code == 400  # approved, current

    v2 = _upload(client, h, pid, data_file("BOM_T01_0004_0000_v2.csv")).json()
    url2 = f"/api/projects/{pid}/bom/versions/{v2['id']}"
    client.post(f"{url2}/reject", headers=h)
    from app.db import SessionLocal
    from app.models import BomRow, BomVersion
    with SessionLocal() as db:
        stored = Path(db.get(BomVersion, v2["id"]).file_path)
    assert stored.is_file()
    assert client.delete(url2, headers=h).status_code == 200
    assert client.get(url2, headers=h).status_code == 404
    assert not stored.exists()
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(BomRow).where(BomRow.version_id == v2["id"])) == 0
    assert client.get(url, headers=h).json()["is_current"] is True


def test_purge_project(client, admin_headers, data_file):
    h = admin_headers
    pid = _project(client, h, "Silinecek")
    v = _upload(client, h, pid, data_file("BOM_T01_0004_0000_v1.csv")).json()
    client.post(f"/api/projects/{pid}/bom/versions/{v['id']}/approve", headers=h)
    from app.config import get_settings
    from app.db import SessionLocal
    from app.models import BomVersion, PurchaseOrder, Tracking, WorkOrder
    with SessionLocal() as db:
        db.add(WorkOrder(no=f"WO-{pid}", project_id=pid, part_no="X"))
        db.add(PurchaseOrder(no=f"PO-{pid}", project_id=pid))
        db.commit()

    imp = client.get(f"/api/projects/{pid}/delete-impact", headers=h).json()
    assert imp["deleted"]["bom_versions"] == 1 and imp["deleted"]["work_orders"] == 1
    assert imp["deleted"]["tracked_parts"] > 0 and imp["unlinked"]["purchase_orders"] == 1

    r = client.post(f"/api/projects/{pid}/purge", headers=h, json={})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/projects/{pid}", headers=h).status_code == 404
    assert not (get_settings().bom_dir / str(pid)).exists()
    with SessionLocal() as db:
        for model in (BomVersion, Tracking, WorkOrder):
            assert db.scalar(select(func.count()).select_from(model).where(model.project_id == pid)) == 0
        po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.no == f"PO-{pid}"))
        assert po is not None and po.project_id is None

