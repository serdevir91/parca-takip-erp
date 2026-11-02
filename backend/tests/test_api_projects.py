from __future__ import annotations

import uuid


def _name(prefix: str) -> str:
    return f"{prefix} {uuid.uuid4().hex[:8]}"


def test_project_crud(client, admin_headers):
    name = _name("Proje CRUD")
    r = client.post("/api/projects", json={"name": name, "description": "deneme"}, headers=admin_headers)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["name"] == name and p["current_version"] is None and p["tracked_parts"] == 0
    pid = p["id"]

    dup = client.post("/api/projects", json={"name": name.upper()}, headers=admin_headers)
    assert dup.status_code == 400 and "zaten var" in dup.json()["detail"]

    assert client.get(f"/api/projects/{pid}", headers=admin_headers).json()["description"] == "deneme"
    r = client.patch(f"/api/projects/{pid}", json={"description": "güncel", "root_part_no": " T99 "},
                     headers=admin_headers)
    assert r.status_code == 200 and r.json()["description"] == "güncel" and r.json()["root_part_no"] == "T99"

    other = client.post("/api/projects", json={"name": _name("Proje diğer")}, headers=admin_headers).json()
    clash = client.patch(f"/api/projects/{other['id']}", json={"name": name}, headers=admin_headers)
    assert clash.status_code == 400

    ids = [x["id"] for x in client.get("/api/projects", headers=admin_headers).json()]
    assert pid in ids

    assert client.delete(f"/api/projects/{pid}", headers=admin_headers).json()["archived"] is True
    assert pid not in [x["id"] for x in client.get("/api/projects", headers=admin_headers).json()]
    listed = client.get("/api/projects", params={"include_archived": True}, headers=admin_headers).json()
    assert pid in [x["id"] for x in listed]
    assert client.post(f"/api/projects/{pid}/restore", headers=admin_headers).json()["archived"] is False


def test_project_errors(client, admin_headers):
    assert client.get("/api/projects/999999", headers=admin_headers).status_code == 404
    assert client.post("/api/projects", json={"name": "   "}, headers=admin_headers).status_code == 400
    assert client.post("/api/projects", json={"name": ""}, headers=admin_headers).status_code == 422
    assert client.get("/api/projects").status_code == 401
