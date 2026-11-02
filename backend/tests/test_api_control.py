from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import Part, Project
from app.services import bomimport

F_1102 = "BOM_T01_0000_0000_2026-11-02.csv"


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


def _list(client, h, pid, **params) -> dict:
    r = client.get(f"/api/projects/{pid}/control", params=params, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_control_resolve_cycle(client, admin_headers, data_file):
    h = admin_headers
    pid = _project_1102(data_file, "BE kontrol")
    body = _list(client, h, pid)
    assert body["items"], "11-02 BOM must produce automatic issues"
    assert body["counts"]["open"] == body["counts"]["total"] and body["kinds"]
    key = body["items"][0]["key"]

    r = client.post(f"/api/projects/{pid}/control/resolve", json={"key": key, "note": "Kontrol edildi"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "Çözüldü" and r.json()["resolved_by"] == "admin"
    after = _list(client, h, pid)
    assert after["counts"]["resolved"] == 1
    assert [i["key"] for i in _list(client, h, pid, status="Çözüldü")["items"]] == [key]

    r = client.post(f"/api/projects/{pid}/control/unresolve", json={"key": key}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "Açık" and r.json()["note"] == "Kontrol edildi"
    assert _list(client, h, pid)["counts"]["resolved"] == 0

    assert client.post(f"/api/projects/{pid}/control/resolve", json={"key": "yok|yok"},
                       headers=h).status_code == 404
    assert client.post(f"/api/projects/{pid}/control/unresolve", json={"key": "yok|yok"},
                       headers=h).status_code == 404


def test_control_manual_issue(client, admin_headers, data_file):
    h = admin_headers
    pid = _project_1102(data_file, "BE kontrol manuel")
    r = client.post(f"/api/projects/{pid}/control/issues",
                    json={"message": "Kaynak dikişi kontrol edilecek", "part_no": "T01_1100_0001"}, headers=h)
    assert r.status_code == 201, r.text
    issue = r.json()
    assert issue["manual"] and issue["key"] == f"manual|{issue['id']}"
    items = _list(client, h, pid)["items"]
    assert any(i["key"] == issue["key"] for i in items)

    r = client.post(f"/api/projects/{pid}/control/resolve", json={"key": issue["key"]}, headers=h)
    assert r.status_code == 200 and r.json()["manual"]
    assert client.post(f"/api/projects/{pid}/control/issues", json={"message": "x", "severity": "kritik"},
                       headers=h).status_code == 400

    auto = next(i for i in items if not i["manual"])
    client.post(f"/api/projects/{pid}/control/resolve", json={"key": auto["key"]}, headers=h)
    stored = _list(client, h, pid, status="Çözüldü")["items"]
    auto_id = next(i["id"] for i in stored if i["key"] == auto["key"])
    assert client.delete(f"/api/projects/{pid}/control/issues/{auto_id}", headers=h).status_code == 400

    assert client.delete(f"/api/projects/{pid}/control/issues/{issue['id']}", headers=h).status_code == 200
    assert not any(i["key"] == issue["key"] for i in _list(client, h, pid)["items"])
    assert client.delete(f"/api/projects/{pid}/control/issues/{issue['id']}", headers=h).status_code == 404
