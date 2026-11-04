"""Restoring a backup from the admin screen while the server runs."""
import io
import time

from app.services import maintenance
from tests.test_security_fixes import _user


def _backup(client, headers):
    time.sleep(1.1)
    r = client.post("/api/admin/backups", headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["name"]


def test_restore_brings_old_data_back_and_keeps_a_safety_backup(client, admin_headers):
    keep = client.post("/api/projects", json={"name": "Yedekte var"}, headers=admin_headers).json()["id"]
    name = _backup(client, admin_headers)
    gone = client.post("/api/projects", json={"name": "Sonradan eklendi"}, headers=admin_headers).json()["id"]

    assert client.post(f"/api/admin/backups/{name}/restore", json={"confirm": "yanlış"},
                       headers=admin_headers).status_code == 400
    time.sleep(1.1)
    r = client.post(f"/api/admin/backups/{name}/restore", json={"confirm": name}, headers=admin_headers)
    assert r.status_code == 200, r.text

    ids = [p["id"] for p in client.get("/api/projects", headers=admin_headers).json()]
    assert keep in ids and gone not in ids
    names = [b["name"] for b in client.get("/api/admin/backups", headers=admin_headers).json()["items"]]
    assert r.json()["safety_backup"] in names

    # and the safety backup undoes it
    time.sleep(1.1)
    safety = r.json()["safety_backup"]
    assert client.post(f"/api/admin/backups/{safety}/restore", json={"confirm": safety},
                       headers=admin_headers).status_code == 200
    assert gone in [p["id"] for p in client.get("/api/projects", headers=admin_headers).json()]


def test_restore_is_admin_only(client, admin_headers):
    name = _backup(client, admin_headers)
    _, h = _user(client, admin_headers, "restoreviewer", "planner")
    assert client.post(f"/api/admin/backups/{name}/restore", json={"confirm": name}, headers=h).status_code == 403


def test_requests_wait_outside_while_restoring(client, admin_headers):
    with maintenance.exclusive(wait=0.1):
        r = client.get("/api/projects", headers=admin_headers)
        assert r.status_code == 503 and "geri yükleniyor" in r.json()["detail"]
        assert client.get("/api/health").status_code == 200
    assert client.get("/api/projects", headers=admin_headers).status_code == 200


def test_upload_accepts_only_real_backups(client, admin_headers):
    r = client.post("/api/admin/backups/upload", files={"file": ("x.tar", io.BytesIO(b"bu bir yedek degil"))},
                    headers=admin_headers)
    assert r.status_code == 400
    name = _backup(client, admin_headers)
    data = client.get(f"/api/admin/backups/{name}", headers=admin_headers).content
    time.sleep(1.1)
    r = client.post("/api/admin/backups/upload", files={"file": ("baska.tar", io.BytesIO(data))},
                    headers=admin_headers)
    assert r.status_code == 201, r.text
    assert r.json()["name"] != name
