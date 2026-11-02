from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.status import PROGRESS_CHOICES
from app.models import Part, Project, Tracking
from app.services import bomimport

F_1102 = "BOM_T01_0000_0000_2026-11-02.csv"
F_T35 = "T-35_Guncel_Durumu.xlsx"


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


def _preview(client, h, pid, data_file):
    with open(data_file(F_T35), "rb") as f:
        return client.post(f"/api/projects/{pid}/t35/preview", headers=h, files={"file": (F_T35, f, "application/"
                           "vnd.openxmlformats-officedocument.spreadsheetml.sheet")})


def test_t35_preview_and_apply(client, admin_headers, data_file):
    h = admin_headers
    pid = _project_1102(data_file, "BE t35")
    r = _preview(client, h, pid, data_file)
    assert r.status_code == 200, r.text
    pv = r.json()
    assert pv["rows"] > 0 and pv["counts"]["rows"] == pv["rows"]
    assert pv["updates"], "T-35 list must match BOM parts"
    assert set(pv) >= {"only_in_bom", "only_in_list", "rev_diff", "qty_diff"}

    u = next(x for x in pv["updates"] if x["changed"])
    item = {"part_no": u["part_no"], **{f: c["new"] for f, c in u["changes"].items()}}
    r = client.post(f"/api/projects/{pid}/t35/apply", json={"items": [item, {"part_no": "YOK_0000", "note": "x"}]},
                    headers=h)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["applied"] == 1 and res["fields"] == len(u["changes"])
    assert res["errors"][0]["part_no"] == "YOK_0000"

    from app.db import SessionLocal
    with SessionLocal() as db:
        t = db.scalar(select(Tracking).where(Tracking.project_id == pid, Tracking.part_no == u["part_no"]))
        for f, c in u["changes"].items():
            assert getattr(t, f) == c["new"]

    again = client.post(f"/api/projects/{pid}/t35/apply", json={"items": [item]}, headers=h).json()
    assert again["applied"] == 0
    bad = client.post(f"/api/projects/{pid}/t35/apply",
                      json={"items": [{"part_no": u["part_no"], "progress": "Belki"}]}, headers=h).json()
    assert bad["applied"] == 0 and bad["errors"]


def test_t35_preview_rejects_bad_input(client, admin_headers, data_file):
    h = admin_headers
    pid = client.post("/api/projects", json={"name": f"BE t35 boş {uuid.uuid4().hex[:8]}"}, headers=h).json()["id"]
    assert _preview(client, h, pid, data_file).status_code == 400
    pid = _project_1102(data_file, "BE t35 bad")
    r = client.post(f"/api/projects/{pid}/t35/preview", headers=h, files={"file": ("x.xlsx", b"not excel", "x")})
    assert r.status_code == 400 and "okunamadı" in r.json()["detail"]


def test_t35_config_roundtrip(client, admin_headers):
    h = admin_headers
    cfg = client.get("/api/t35/config", headers=h)
    assert cfg.status_code == 200, cfg.text
    old = cfg.json()
    assert old["rules"] and old["progress_choices"] == PROGRESS_CHOICES
    body = {"rules": [{"field": "progress", "all": ["bitti"], "value": "Tamamlandı"}],
            "default_progress": "Bekliyor", "skip_note": ["-"]}
    r = client.put("/api/t35/config", json=body, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["rules"][0]["all"] == ["bitti"] and r.json()["skip_note"] == ["-"]
    bad = client.put("/api/t35/config", json={**body, "rules": [{"field": "x", "all": ["a"], "value": "b"}]},
                     headers=h)
    assert bad.status_code == 400
    bad = client.put("/api/t35/config", json={**body, "rules": [{"field": "progress", "all": [" "],
                                                                  "value": "Tamamlandı"}]}, headers=h)
    assert bad.status_code == 400
    restore = {k: old[k] for k in ("rules", "default_progress", "skip_note")}
    r = client.put("/api/t35/config", json=restore, headers=h)
    assert r.status_code == 200
    core = ("field", "all", "value", "priority")
    assert [{k: x[k] for k in core} for x in r.json()["rules"]] == [{k: x[k] for k in core} for x in old["rules"]]
