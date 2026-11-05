"""Security closures of 1.5.9: mail rights, sealed SMTP password, project reads, grid export, chat uploads."""
import json
import os

import pytest

from sqlalchemy import delete

from app.db import SessionLocal
from app.models import Setting
from app.services import mailer, secretbox
from app.services.settings import get_setting, set_setting
from tests.test_security_fixes import _user


def _perms(client, headers, name, role, overrides):
    uid, h = _user(client, headers, name, role)
    r = client.put(f"/api/admin/users/{uid}", json={"permissions": overrides}, headers=headers)
    assert r.status_code == 200, r.text
    return h


def _room(client, headers, name):
    uid, _ = _user(client, headers, f"oda{abs(hash(name)) % 10**8}")
    r = client.post("/api/chat/groups", json={"name": f"oda {name}", "member_ids": [uid]}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_viewer_cannot_send_company_mail(client, admin_headers):
    _, h = _user(client, admin_headers, "mailviewer", "viewer")
    r = client.post("/api/mail/send", data={"to": "a@b.co", "subject": "x"}, headers=h)
    assert r.status_code == 403
    assert client.get("/api/mail/recipients", headers=h).status_code == 403
    assert client.get("/api/mail/status", headers=h).status_code == 200


def test_smtp_password_is_sealed_at_rest(client, admin_headers):
    r = client.put("/api/mail/settings", headers=admin_headers,
                   json={"host": "smtp.x.co", "from_addr": "a@x.co", "username": "u", "password": "s3cret-pass"})
    assert r.status_code == 200 and "s3cret" not in r.text
    with SessionLocal() as db:
        raw = get_setting(db, "smtp")["password"]
        assert secretbox.sealed(raw) and "s3cret" not in raw
        assert mailer.config(db).password == "s3cret-pass"
    # saving without a password keeps it, and does not seal it twice
    client.put("/api/mail/settings", headers=admin_headers, json={"host": "smtp.y.co", "from_addr": "a@x.co"})
    with SessionLocal() as db:
        assert mailer.config(db).password == "s3cret-pass"


def test_plain_password_of_older_version_gets_sealed(client):
    with SessionLocal() as db:
        v = get_setting(db, "smtp") or {}
        set_setting(db, "smtp", {**v, "password": "old-plain"})
        db.commit()
        assert mailer.config(db).password == "old-plain"
        mailer.seal_stored(db)
        assert secretbox.sealed(get_setting(db, "smtp")["password"])
        assert mailer.config(db).password == "old-plain"


def test_sealed_value_from_another_server_reads_empty():
    assert secretbox.open_("enc1:not-a-token") == ""


def test_projects_none_sees_only_names(client, admin_headers):
    pid = client.post("/api/projects", json={"name": "Gizli proje", "description": "çok gizli"},
                      headers=admin_headers).json()["id"]
    h = _perms(client, admin_headers, "noproj", "planner", {"projects": "none"})
    rows = client.get("/api/projects", headers=h).json()
    assert {"id", "name", "archived"} == set(next(r for r in rows if r["id"] == pid))
    assert "description" not in client.get(f"/api/projects/{pid}", headers=h).json()
    assert client.get(f"/api/projects/{pid}/requirements", headers=h).status_code == 403
    assert client.get(f"/api/projects/{pid}/costs", headers=h).status_code == 403


def test_user_without_any_module_gets_nothing(client, admin_headers):
    pid = client.post("/api/projects", json={"name": "Boş kullanıcı"}, headers=admin_headers).json()["id"]
    off = {m: "none" for m in ("projects", "parts", "fasteners", "drawings", "control", "planning", "workorders",
                               "stock", "purchasing", "contacts", "sales", "finance", "hr", "attendance")}
    h = _perms(client, admin_headers, "nothing", "viewer", off)
    assert client.get("/api/projects", headers=h).json() == []
    assert client.get(f"/api/projects/{pid}", headers=h).status_code == 403
    assert client.get("/api/firms", headers=h).json() == []


def test_viewer_cannot_read_project_money(client, admin_headers):
    pid = client.post("/api/projects", json={"name": "Maliyet"}, headers=admin_headers).json()["id"]
    _, h = _user(client, admin_headers, "costviewer", "viewer")
    assert client.get(f"/api/projects/{pid}/costs", headers=h).status_code == 403
    assert client.get(f"/api/projects/{pid}/requirements", headers=h).status_code == 200
    assert client.get(f"/api/projects/{pid}/costs", headers=admin_headers).status_code == 200


def test_grid_export_belongs_to_its_owner(client, admin_headers):
    _, h1 = _user(client, admin_headers, "gridone", "viewer")
    _, h2 = _user(client, admin_headers, "gridtwo", "viewer")
    fid = client.post("/api/export/grid", json={"columns": ["A"], "rows": [["x", "fazla"]]}, headers=h1).json()["id"]
    assert client.get(f"/api/export/grid/{fid}", headers=h1).status_code == 200
    assert client.get(f"/api/export/grid/{fid}", headers=h2).status_code == 404


def test_grid_export_has_a_cell_limit(client, admin_headers):
    body = b'{"columns":' + json.dumps(["c"] * 200).encode() + b',"rows":[' + b",".join([b"[1]"] * 5001) + b"]}"
    r = client.post("/api/export/grid", content=body,
                    headers={**admin_headers, "Content-Type": "application/json"})
    assert r.status_code == 413


@pytest.mark.parametrize("name", ["setup.exe", "sayfa.HTML", "resim.svg"])
def test_chat_refuses_active_files(client, admin_headers, name):
    room = _room(client, admin_headers, name)
    r = client.post(f"/api/chat/rooms/{room}/messages", data={"body": ""},
                    files={"file": (name, b"x")}, headers=admin_headers)
    assert r.status_code == 415


def test_chat_odd_file_name_does_not_crash(client, admin_headers):
    room = _room(client, admin_headers, "garip")
    r = client.post(f"/api/chat/rooms/{room}/messages", data={"body": ""},
                    files={"file": ("a./x", b"data")}, headers=admin_headers)
    assert r.status_code in (200, 201), r.text


def test_signup_is_off_on_a_new_install(client):
    with SessionLocal() as db:
        db.execute(delete(Setting).where(Setting.key == "signup"))
        db.commit()
    assert client.get("/api/auth/options").json()["signup"] is False
    r = client.post("/api/auth/register", json={"username": "kimse", "password": "Parola-12345"})
    assert r.status_code == 403


def test_spa_csp_allows_only_own_origin(client):
    from app.main import SPA_CSP
    assert "connect-src 'self';" in SPA_CSP


def test_https_files_stay_out_of_backups_and_can_be_switched(client, admin_headers, tmp_path):
    from app.services import backup, tls
    tls.disable()
    r = client.put("/api/admin/https", json={"enabled": True}, headers=admin_headers).json()
    assert r["enabled"] is True and len(r["fingerprint"]) == 64
    assert client.get("/api/tls/cert").status_code == 200
    again = client.put("/api/admin/https", json={"enabled": True}, headers=admin_headers).json()
    assert again["fingerprint"] == r["fingerprint"]           # never replaced: clients pin it
    assert os.name == "nt" or (tls.files()[1].stat().st_mode & 0o777) == 0o600   # Windows has no mode bits
    assert "tls" in backup._not_data(tls.folder().parent, "sqlite:///x.db", tmp_path)
    assert client.put("/api/admin/https", json={"enabled": False}, headers=admin_headers).json()["fingerprint"] == ""
    assert client.get("/api/tls/cert").status_code == 404


def test_https_and_restart_are_admin_only(client, admin_headers):
    _, h = _user(client, admin_headers, "tlsviewer", "viewer")
    assert client.get("/api/admin/https", headers=h).status_code == 403
    assert client.put("/api/admin/https", json={"enabled": True}, headers=h).status_code == 403
    assert client.post("/api/admin/server/restart", headers=h).status_code == 403
    assert client.post("/api/admin/server/restart", headers=admin_headers).status_code == 409
