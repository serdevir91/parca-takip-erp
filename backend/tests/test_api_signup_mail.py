"""Self sign-up with admin approval, e-mail addresses and sending lists by e-mail."""
from __future__ import annotations

import smtplib
import uuid

import pytest

from app.services import loginguard


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _login(client, username, password):
    return client.post("/api/auth/login", data={"username": username, "password": password})


def _signup(client, **kw):
    body = {"username": _uid("yeni"), "full_name": "Yeni Kişi", "email": "yeni@example.com",
            "password": "parola123"} | kw
    return body, client.post("/api/auth/register", json=body)


@pytest.fixture(autouse=True)
def _reset_guard(client, admin_headers):
    client.put("/api/admin/settings/signup", json={"value": {"enabled": True}}, headers=admin_headers)
    loginguard.reset()
    yield
    loginguard.reset()


def test_signup_waits_for_approval_then_logs_in(client, admin_headers):
    assert client.get("/api/auth/options").json()["signup"] is True
    body, r = _signup(client)
    assert r.status_code == 201, r.text
    # Right password, but not approved yet: a clear message instead of "hatalı"
    r = _login(client, body["username"], body["password"])
    assert r.status_code == 403 and "onay" in r.json()["detail"]
    # Wrong password does not tell that the account exists
    assert _login(client, body["username"], "yanlis-sifre").status_code == 401

    assert client.get("/api/admin/signups/count", headers=admin_headers).json()["pending"] >= 1
    users = client.get("/api/admin/users", headers=admin_headers).json()
    assert users[0]["pending"] is True  # waiting requests come first
    u = next(x for x in users if x["username"] == body["username"])
    assert u["email"] == "yeni@example.com" and not u["active"]

    r = client.post(f"/api/admin/users/{u['id']}/approve", headers=admin_headers,
                    json={"role": "planner", "permissions": {"finance": "none"}})
    assert r.status_code == 200, r.text
    assert r.json()["active"] and not r.json()["pending"] and r.json()["role"] == "planner"
    r = _login(client, body["username"], body["password"])
    assert r.status_code == 200, r.text
    assert r.json()["user"]["permissions"]["finance"] == "none"
    # Approving twice is refused
    assert client.post(f"/api/admin/users/{u['id']}/approve", headers=admin_headers,
                       json={"role": "viewer"}).status_code == 400


def test_reject_removes_request(client, admin_headers):
    body, r = _signup(client)
    uid = next(x["id"] for x in client.get("/api/admin/users", headers=admin_headers).json()
               if x["username"] == body["username"])
    assert client.delete(f"/api/admin/users/{uid}/signup", headers=admin_headers).status_code == 200
    assert _login(client, body["username"], body["password"]).status_code == 401
    # The name is free again
    assert _signup(client, username=body["username"])[1].status_code == 201


@pytest.mark.parametrize("kw,code", [
    ({"username": "a b"}, 400), ({"username": "ab"}, 400), ({"password": "kisa"}, 400),
    ({"email": "e-posta-degil"}, 400), ({"username": "admin"}, 409), ({"username": "ADMIN"}, 409),
])
def test_signup_validation(client, kw, code):
    assert _signup(client, **kw)[1].status_code == code


def test_signup_rate_limit_and_switch(client, admin_headers):
    for _ in range(loginguard.SIGNUP_LIMIT):
        assert _signup(client)[1].status_code == 201
    assert _signup(client)[1].status_code == 429
    loginguard.reset()
    r = client.put("/api/admin/settings/signup", headers=admin_headers, json={"value": {"enabled": False}})
    assert r.status_code == 200 and r.json()["signup"] == {"enabled": False}
    try:
        assert client.get("/api/auth/options").json()["signup"] is False
        assert _signup(client)[1].status_code == 403
    finally:
        client.put("/api/admin/settings/signup", headers=admin_headers, json={"value": {"enabled": True}})


def test_signup_endpoints_admin_only(client):
    body, _ = _signup(client)
    assert client.get("/api/admin/signups/count").status_code == 401
    assert client.post("/api/admin/users/1/approve", json={"role": "admin"}).status_code == 401


def test_profile_and_admin_email(client, admin_headers):
    name = _uid("mail")
    r = client.post("/api/admin/users", headers=admin_headers,
                    json={"username": name, "password": "parola123", "email": "ilk@example.com"})
    assert r.status_code == 201 and r.json()["email"] == "ilk@example.com"
    h = {"Authorization": f"Bearer {_login(client, name, 'parola123').json()['access_token']}"}
    r = client.put("/api/auth/me", headers=h, json={"full_name": "Mail Kişi", "email": "ben@example.com"})
    assert r.status_code == 200 and r.json()["email"] == "ben@example.com"
    assert client.put("/api/auth/me", headers=h, json={"full_name": "x", "email": "bozuk"}).status_code == 400
    uid = r.json()["id"]
    r = client.put(f"/api/admin/users/{uid}", headers=admin_headers, json={"email": ""})
    assert r.status_code == 200 and r.json()["email"] == ""


class FakeSMTP:
    sent: list = []

    def __init__(self, host, port, timeout=None, **kw):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, **kw):
        pass

    def login(self, user, pw):
        if pw != "dogru":
            raise smtplib.SMTPAuthenticationError(535, b"bad")

    def send_message(self, msg, to_addrs=None):
        FakeSMTP.sent.append((msg, to_addrs))


@pytest.fixture
def smtp(client, admin_headers, monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    FakeSMTP.sent = []
    r = client.put("/api/mail/settings", headers=admin_headers, json={
        "host": "smtp.example.com", "port": 587, "security": "starttls", "username": "erp@example.com",
        "password": "dogru", "from_addr": "erp@example.com", "from_name": "ERP"})
    assert r.status_code == 200, r.text
    yield
    client.put("/api/mail/settings", headers=admin_headers, json={"host": "", "clear_password": True})


def test_smtp_settings_hide_password(client, admin_headers, smtp):
    s = client.get("/api/mail/settings", headers=admin_headers).json()
    assert "password" not in s and s["has_password"] and s["ready"]
    # Saving without a password keeps the stored one
    client.put("/api/mail/settings", headers=admin_headers, json={**s, "password": ""})
    assert client.get("/api/mail/settings", headers=admin_headers).json()["has_password"]
    assert client.put("/api/mail/settings", headers=admin_headers,
                      json={"host": "x", "security": "tls"}).status_code == 400


def test_send_list_by_mail(client, admin_headers, smtp):
    assert client.get("/api/mail/status", headers=admin_headers).json() == {"ready": True}
    r = client.post("/api/mail/send", headers=admin_headers,
                    data={"to": "a@example.com; b@example.com", "subject": "Parça listesi", "body": "Ekte."},
                    files=[("files", ("liste.xlsx", b"PK\x03\x04data", "application/vnd.ms-excel"))])
    assert r.status_code == 200, r.text
    msg, to = FakeSMTP.sent[-1]
    assert to == ["a@example.com", "b@example.com"]
    assert msg["Subject"] == "Parça listesi"
    att = [p for p in msg.iter_attachments()]
    assert att[0].get_filename() == "liste.xlsx" and att[0].get_content() == b"PK\x03\x04data"
    assert client.post("/api/mail/send", headers=admin_headers,
                       data={"to": "bozuk", "subject": "x"}).status_code == 400
    assert client.post("/api/mail/test", headers=admin_headers, json={"to": "c@example.com"}).status_code == 200


def test_send_reports_auth_error(client, admin_headers, smtp):
    client.put("/api/mail/settings", headers=admin_headers, json={
        "host": "smtp.example.com", "username": "u", "password": "yanlis", "from_addr": "erp@example.com"})
    r = client.post("/api/mail/send", headers=admin_headers, data={"to": "a@example.com", "subject": "x"})
    assert r.status_code == 502 and "uygulama şifresi" in r.json()["detail"]


def test_send_without_smtp(client, admin_headers):
    assert client.get("/api/mail/status", headers=admin_headers).json() == {"ready": False}
    r = client.post("/api/mail/send", headers=admin_headers, data={"to": "a@example.com", "subject": "x"})
    assert r.status_code == 400


def test_recipients(client, admin_headers):
    r = client.get("/api/mail/recipients", headers=admin_headers)
    assert r.status_code == 200 and all("@" in x["email"] for x in r.json())
