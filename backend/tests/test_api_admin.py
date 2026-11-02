"""Admin API, backup service and CLI tests."""
from __future__ import annotations

import os
import tarfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _login(client, username: str, password: str) -> dict[str, str]:
    r = client.post("/api/auth/login", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def viewer_headers(client, admin_headers):
    name = _uid("viewer")
    r = client.post("/api/admin/users", headers=admin_headers,
                    json={"username": name, "password": "viewer123", "full_name": "İzleyici", "role": "viewer"})
    assert r.status_code == 201, r.text
    return _login(client, name, "viewer123")


# ---------- guards ----------
@pytest.mark.parametrize("method,path", [
    ("get", "/api/admin/users"), ("get", "/api/admin/firms"), ("get", "/api/admin/settings"),
    ("get", "/api/admin/audit"), ("get", "/api/admin/backups"), ("post", "/api/admin/backups"),
    ("put", "/api/admin/settings/status_rules"), ("delete", "/api/admin/users/1"),
])
def test_non_admin_forbidden(client, viewer_headers, method, path):
    kw = {"json": {"value": {"big_drop_ratio": 0.5}}} if method == "put" else {}
    r = getattr(client, method)(path, headers=viewer_headers, **kw)
    assert r.status_code == 403, r.text


def test_anonymous_unauthorized(client):
    assert client.get("/api/admin/users").status_code == 401


# ---------- users ----------
def test_user_crud(client, admin_headers):
    roles = client.get("/api/admin/roles", headers=admin_headers).json()
    assert {r["value"] for r in roles} == {"admin", "designer", "planner", "viewer"}

    name = _uid("planci")
    r = client.post("/api/admin/users", headers=admin_headers,
                    json={"username": name, "password": "sifre123", "full_name": "Planlama", "role": "planner"})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    assert r.json()["role"] == "planner"

    dup = client.post("/api/admin/users", headers=admin_headers,
                      json={"username": name.upper(), "password": "sifre123", "role": "viewer"})
    assert dup.status_code == 409
    assert "zaten var" in dup.json()["detail"]
    assert client.post("/api/admin/users", headers=admin_headers,
                       json={"username": _uid("x"), "password": "123", "role": "viewer"}).status_code == 400
    assert client.post("/api/admin/users", headers=admin_headers,
                       json={"username": _uid("x"), "password": "sifre123", "role": "boss"}).status_code == 400

    r = client.put(f"/api/admin/users/{uid}", headers=admin_headers, json={"role": "designer", "full_name": "Tasarım"})
    assert r.status_code == 200 and r.json()["role"] == "designer"
    assert any(u["username"] == name for u in client.get("/api/admin/users", headers=admin_headers).json())

    assert client.post(f"/api/admin/users/{uid}/password", headers=admin_headers,
                       json={"password": "yeniSifre9"}).status_code == 200
    _login(client, name, "yeniSifre9")

    r = client.delete(f"/api/admin/users/{uid}", headers=admin_headers)
    assert r.status_code == 200 and r.json()["active"] is False
    bad = client.post("/api/auth/login", data={"username": name, "password": "yeniSifre9"})
    assert bad.status_code in (400, 401, 403)

    assert client.put("/api/admin/users/999999", headers=admin_headers, json={"role": "viewer"}).status_code == 404

    log = client.get("/api/admin/audit", headers=admin_headers,
                     params={"entity": "user", "entity_id": str(uid)}).json()
    fields = {a["field"] for a in log["items"]}
    assert {"username", "role", "password", "active"} <= fields


def test_second_admin_can_be_demoted(client, admin_headers):
    name = _uid("admin2")
    uid = client.post("/api/admin/users", headers=admin_headers,
                      json={"username": name, "password": "admin222", "role": "admin"}).json()["id"]
    r = client.put(f"/api/admin/users/{uid}", headers=admin_headers, json={"role": "viewer"})
    assert r.status_code == 200, r.text


def test_last_admin_guard(client, admin_headers, monkeypatch):
    from app.api import admin as admin_api
    users = client.get("/api/admin/users", headers=admin_headers).json()
    me = next(u for u in users if u["username"] == "admin")
    # Other test modules may create admins; pretend this is the only active one
    other = client.post("/api/admin/users", headers=admin_headers,
                        json={"username": _uid("solo"), "password": "admin333", "role": "admin"}).json()["id"]
    monkeypatch.setattr(admin_api, "_active_admins", lambda db: 1)
    r = client.delete(f"/api/admin/users/{other}", headers=admin_headers)
    assert r.status_code == 400
    assert "Son aktif yönetici" in r.json()["detail"]
    r = client.put(f"/api/admin/users/{other}", headers=admin_headers, json={"active": False})
    assert r.status_code == 400
    # An admin can never deactivate or demote their own account
    r = client.delete(f"/api/admin/users/{me['id']}", headers=admin_headers)
    assert r.status_code == 400
    assert "Kendi hesabınızı" in r.json()["detail"]
    r = client.put(f"/api/admin/users/{me['id']}", headers=admin_headers, json={"role": "planner"})
    assert r.status_code == 400
    monkeypatch.undo()
    assert client.delete(f"/api/admin/users/{other}", headers=admin_headers).status_code == 200
    # Changing only the name is fine
    assert client.put(f"/api/admin/users/{me['id']}", headers=admin_headers,
                      json={"full_name": me["full_name"]}).status_code == 200


def test_guard_helper_direct():
    from app.api.admin import _guard_last_admin
    from app.models import User

    class _DB:
        def scalar(self, _q):
            return 1

    u = User(username="x", role="admin", active=True, full_name="", password_hash="")
    with pytest.raises(HTTPException):
        _guard_last_admin(_DB(), u, "admin", False)
    _guard_last_admin(_DB(), u, "admin", True)
    viewer = User(username="y", role="viewer", active=True, full_name="", password_hash="")
    _guard_last_admin(_DB(), viewer, "viewer", False)


# ---------- firms ----------
def test_firm_crud(client, admin_headers):
    name = _uid("Firma Çelik")
    r = client.post("/api/admin/firms", headers=admin_headers,
                    json={"name": name, "kind": "supplier", "contact": "0212 000 00 00"})
    assert r.status_code == 201, r.text
    fid = r.json()["id"]
    assert client.post("/api/admin/firms", headers=admin_headers,
                       json={"name": name.lower(), "kind": "supplier"}).status_code == 409
    assert client.post("/api/admin/firms", headers=admin_headers,
                       json={"name": _uid("F"), "kind": "customer"}).status_code == 400

    sup = client.get("/api/admin/firms", headers=admin_headers, params={"kind": "supplier"}).json()
    assert any(f["id"] == fid for f in sup)
    manu = client.get("/api/admin/firms", headers=admin_headers, params={"kind": "manufacturer"}).json()
    assert all(f["id"] != fid for f in manu)

    r = client.put(f"/api/admin/firms/{fid}", headers=admin_headers, json={"kind": "both", "note": "ikisi"})
    assert r.status_code == 200 and r.json()["kind"] == "both"
    manu = client.get("/api/admin/firms", headers=admin_headers, params={"kind": "manufacturer"}).json()
    assert any(f["id"] == fid for f in manu)

    assert client.delete(f"/api/admin/firms/{fid}", headers=admin_headers).status_code == 200
    assert client.put(f"/api/admin/firms/{fid}", headers=admin_headers, json={"note": "x"}).status_code == 404
    log = client.get("/api/admin/audit", headers=admin_headers,
                     params={"entity": "firm", "entity_id": str(fid), "action": "delete"}).json()
    assert log["total"] >= 1


# ---------- settings ----------
def test_settings_get_put_and_purchased_mirror(client, admin_headers):
    from app.db import SessionLocal
    from app.models import Part
    from sqlalchemy import select

    before = client.get("/api/admin/settings", headers=admin_headers).json()
    assert {"part_no_patterns", "purchased_assemblies", "status_rules"} <= set(before)
    new_pno = _uid("SATIN_MONTAJ")
    try:
        r = client.put("/api/admin/settings/purchased_assemblies", headers=admin_headers,
                       json={"value": [*before["purchased_assemblies"], new_pno, " ", new_pno]})
        assert r.status_code == 200, r.text
        assert new_pno in r.json()["purchased_assemblies"]
        assert r.json()["purchased_assemblies"].count(new_pno) == 1
        with SessionLocal() as db:
            assert db.scalar(select(Part.is_purchased_assembly).where(Part.part_no == new_pno)) is True

        assert client.put("/api/admin/settings/part_no_patterns", headers=admin_headers,
                          json={"value": ["^T01_(", "x"]}).status_code == 400
        assert client.put("/api/admin/settings/part_no_patterns", headers=admin_headers,
                          json={"value": []}).status_code == 400
        r = client.put("/api/admin/settings/part_no_patterns", headers=admin_headers,
                       json={"value": [*before["part_no_patterns"], r"^ZZ\d+$"]})
        assert r.status_code == 200 and r"^ZZ\d+$" in r.json()["part_no_patterns"]

        assert client.put("/api/admin/settings/status_rules", headers=admin_headers,
                          json={"value": {"big_drop_ratio": 1.5}}).status_code == 400
        r = client.put("/api/admin/settings/status_rules", headers=admin_headers,
                       json={"value": {"big_drop_ratio": 0.25}})
        assert r.status_code == 200 and r.json()["status_rules"]["big_drop_ratio"] == 0.25

        assert client.put("/api/admin/settings/bilinmeyen", headers=admin_headers,
                          json={"value": 1}).status_code == 404
        log = client.get("/api/admin/audit", headers=admin_headers,
                         params={"entity": "setting", "q": new_pno}).json()
        assert log["total"] >= 1
    finally:
        for key in ("purchased_assemblies", "part_no_patterns", "status_rules"):
            client.put(f"/api/admin/settings/{key}", headers=admin_headers, json={"value": before[key]})
    with SessionLocal() as db:
        assert not db.scalar(select(Part.is_purchased_assembly).where(Part.part_no == new_pno))
    after = client.get("/api/admin/settings", headers=admin_headers).json()
    assert after == before


# ---------- audit ----------
def test_audit_filters_and_paging(client, admin_headers):
    tag = _uid("AuditFirma")
    for i in range(3):
        client.post("/api/admin/firms", headers=admin_headers, json={"name": f"{tag}_{i}", "kind": "manufacturer"})
    base = {"q": tag, "action": "create", "user": "admin"}
    allr = client.get("/api/admin/audit", headers=admin_headers, params=base).json()
    assert allr["total"] == 3
    p1 = client.get("/api/admin/audit", headers=admin_headers, params={**base, "page_size": 2}).json()
    p2 = client.get("/api/admin/audit", headers=admin_headers, params={**base, "page_size": 2, "page": 2}).json()
    assert len(p1["items"]) == 2 and len(p2["items"]) == 1
    assert {a["id"] for a in p1["items"]}.isdisjoint({a["id"] for a in p2["items"]})

    today = datetime.now(timezone.utc).date()
    tomorrow = (today + timedelta(days=2)).isoformat()
    yesterday = (today - timedelta(days=2)).isoformat()
    assert client.get("/api/admin/audit", headers=admin_headers,
                      params={**base, "date_from": yesterday, "date_to": tomorrow}).json()["total"] == 3
    assert client.get("/api/admin/audit", headers=admin_headers,
                      params={**base, "date_from": tomorrow}).json()["total"] == 0
    assert client.get("/api/admin/audit", headers=admin_headers,
                      params={**base, "date_to": yesterday}).json()["total"] == 0
    assert client.get("/api/admin/audit", headers=admin_headers,
                      params={**base, "user": "kimse_yok"}).json()["total"] == 0
    assert client.get("/api/admin/audit", headers=admin_headers,
                      params={"project_id": 987654}).json()["total"] == 0
    assert client.get("/api/admin/audit", headers=admin_headers,
                      params={"date_from": "dün"}).status_code == 400
    assert client.get("/api/admin/audit", headers=admin_headers, params={"page": 0}).status_code == 422

    facets = client.get("/api/admin/audit/facets", headers=admin_headers).json()
    assert "admin" in facets["users"] and "create" in facets["actions"] and "firm" in facets["entities"]


# ---------- backups (API) ----------
def test_backup_endpoints(client, admin_headers):
    r = client.post("/api/admin/backups", headers=admin_headers)
    assert r.status_code in (201, 409), r.text
    if r.status_code == 409:  # same second as another backup; list must still show one
        name = client.get("/api/admin/backups", headers=admin_headers).json()["last"]["name"]
    else:
        name = r.json()["name"]
    st = client.get("/api/admin/backups", headers=admin_headers).json()
    assert st["count"] >= 1 and any(b["name"] == name for b in st["items"])

    d = client.get(f"/api/admin/backups/{name}", headers=admin_headers)
    assert d.status_code == 200
    assert d.headers["content-type"] == "application/x-tar"
    assert len(d.content) == next(b["size"] for b in st["items"] if b["name"] == name)

    assert client.get("/api/admin/backups/..%2Fsecret.tar", headers=admin_headers).status_code == 404
    assert client.get("/api/admin/backups/erp_19990101_000000.tar", headers=admin_headers).status_code == 404
    log = client.get("/api/admin/audit", headers=admin_headers,
                     params={"entity": "backup", "entity_id": name}).json()
    assert {"download"} <= {a["action"] for a in log["items"]}


# ---------- backup service ----------
def _make_sqlite(path: Path) -> str:
    import sqlite3
    with sqlite3.connect(path) as c:
        c.execute("create table t (v text)")
        c.execute("insert into t values ('ilk')")
    return f"sqlite:///{path}"


def test_backup_service_sqlite_and_prune(tmp_path):
    from app.services import backup as bk

    url = _make_sqlite(tmp_path / "src.db")
    data = tmp_path / "data"
    (data / "drawings").mkdir(parents=True)
    (data / "drawings" / "parça.pdf").write_bytes(b"%PDF-1.4 test")
    out = tmp_path / "bk"

    t0 = datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)
    names = []
    for i in range(5):
        info = bk.create_backup(url, data, out, keep_days=0, now=t0 + timedelta(days=i))
        names.append(info.name)
    assert [b.name for b in bk.list_backups(out)] == list(reversed(names))

    with tarfile.open(out / names[0]) as tar:
        members = set(tar.getnames())
    assert {"manifest.json", "db.sqlite3", "data/drawings/parça.pdf"} <= members
    m = bk.read_manifest(out / names[0])
    assert m["db_kind"] == "sqlite" and m["data_files"] == 1

    # keep 2 days at day 4: days 0 and 1 go, 2..4 stay
    deleted = bk.prune(2, out, now=t0 + timedelta(days=4))
    assert sorted(deleted) == sorted(names[:2])
    assert {b.name for b in bk.list_backups(out)} == set(names[2:])

    # create_backup prunes on its own with keep_days
    info = bk.create_backup(url, data, out, keep_days=1, now=t0 + timedelta(days=10))
    assert [b.name for b in bk.list_backups(out)] == [info.name]

    # newest backup survives even when everything is old
    assert bk.prune(1, out, now=t0 + timedelta(days=100)) == []
    assert len(bk.list_backups(out)) == 1

    with pytest.raises(bk.BackupError):
        bk.backup_path("../src.db", out)
    with pytest.raises(bk.BackupError):
        bk.backup_path("erp_20000101_000000.tar", out)
    assert bk.backup_path(info.name, out) == out / info.name


def test_backup_restore_sqlite(tmp_path):
    import sqlite3

    from app.services import backup as bk

    db = tmp_path / "live.db"
    url = _make_sqlite(db)
    data = tmp_path / "data"
    data.mkdir()
    (data / "a.txt").write_text("eski", encoding="utf-8")
    info = bk.create_backup(url, data, tmp_path / "bk", keep_days=14)

    with sqlite3.connect(db) as c:
        c.execute("delete from t")
    (data / "a.txt").write_text("değişti", encoding="utf-8")
    (data / "yeni.txt").write_text("silinmeli", encoding="utf-8")

    bk.restore_backup(info.path, url, data)
    with sqlite3.connect(db) as c:
        assert c.execute("select v from t").fetchall() == [("ilk",)]
    assert (data / "a.txt").read_text(encoding="utf-8") == "eski"
    assert not (data / "yeni.txt").exists()


def test_backup_busy_and_partial_cleanup(tmp_path):
    from app.services import backup as bk

    url = _make_sqlite(tmp_path / "s.db")
    out = tmp_path / "bk"
    now = datetime(2026, 3, 1, tzinfo=timezone.utc)
    bk.create_backup(url, tmp_path / "nodata", out, keep_days=3, now=now)
    with pytest.raises(bk.BackupBusy):  # same second
        bk.create_backup(url, tmp_path / "nodata", out, keep_days=3, now=now)
    assert bk._lock.acquire(blocking=False)
    try:
        with pytest.raises(bk.BackupBusy):
            bk.create_backup(url, tmp_path / "nodata", out, keep_days=3, now=now + timedelta(seconds=1))
    finally:
        bk._lock.release()

    old = out / "erp_20250101_000000.tar.partial"
    old.write_bytes(b"x")
    ts = (now - timedelta(days=30)).timestamp()
    os.utime(old, (ts, ts))
    bk.prune(3, out, now=now)
    assert not old.exists()
    with pytest.raises(bk.BackupError):
        bk.create_backup("sqlite:///:memory:", tmp_path, out)


# ---------- CLI ----------
def test_cli_create_admin_and_backup(client, tmp_path, monkeypatch, capsys):
    from app import cli
    from app.config import get_settings

    name = _uid("cliadmin")
    assert cli.main(["create-admin", "--username", name, "--password", "cliSifre1"]) == 0
    _login(client, name, "cliSifre1")
    assert cli.main(["create-admin", "--username", name, "--password", "cliSifre2", "--full-name", "CLI"]) == 0
    assert "sıfırlandı" in capsys.readouterr().out
    _login(client, name, "cliSifre2")
    with pytest.raises(SystemExit):
        cli.create_admin(_uid("k"), "123")

    assert cli._next_run("02:00", datetime(2026, 1, 1, 1, 0)) == datetime(2026, 1, 1, 2, 0)
    assert cli._next_run("02:00", datetime(2026, 1, 1, 3, 0)) == datetime(2026, 1, 2, 2, 0)

    out = tmp_path / "cli_bk"
    monkeypatch.setattr(get_settings(), "backup_dir", out)
    monkeypatch.setattr(get_settings(), "backup_keep_days", 14)
    rc = cli.main(["backup"])
    assert rc in (0, 1)
    if rc == 0:
        assert len(list(out.glob("erp_*.tar"))) == 1
