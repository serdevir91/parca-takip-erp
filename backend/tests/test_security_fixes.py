"""Regression tests for the findings of the security audit."""
import os
import sqlite3
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor


from app.config import WEAK_SECRETS, get_settings
from app.services import backup, loginguard


def _user(client, headers, name, role="viewer", email=None):
    r = client.post("/api/admin/users", json={"username": name, "password": "pass1234", "full_name": name, "role": role},
                    headers=headers)
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    token = client.post("/api/auth/login", data={"username": name, "password": "pass1234"}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    if email:
        assert client.put("/api/auth/me", json={"full_name": name, "email": email}, headers=h).status_code == 200
    return uid, h


def test_placeholder_secret_is_weak():
    assert "degistir-bunu-uzun-rastgele-bir-anahtar" in WEAK_SECRETS


def test_same_email_does_not_open_a_colleagues_card(client, admin_headers):
    r = client.post("/api/employees", json={"name": "Ayşe", "email": "ayse@firma.test", "hourly_cost": 500},
                    headers=admin_headers)
    assert r.status_code == 201, r.text
    _, h = _user(client, admin_headers, "gozcu", email="ayse@firma.test")
    assert client.get("/api/hr/me", headers=h).json().get("employee") is None


def test_activity_feed_follows_permissions(client, admin_headers):
    client.post("/api/employees", json={"name": "Maaşlı", "hourly_cost": 777}, headers=admin_headers)
    uid, h = _user(client, admin_headers, "izleyen")
    client.put(f"/api/admin/users/{uid}", json={"permissions": {"hr": "none", "parts": "none", "projects": "none"}},
               headers=admin_headers)
    recent = client.get("/api/overview", headers=h).json()["recent"]
    assert not [r for r in recent if r["entity"] in ("Personel", "Kullanıcı")]
    assert any(r["entity"] == "Personel" for r in client.get("/api/overview", headers=admin_headers).json()["recent"])


def test_login_failures_do_not_lock_out_other_addresses(client, admin_headers):
    loginguard.reset()
    limit = get_settings().login_attempts
    for _ in range(limit):
        loginguard.failed("admin", "10.0.0.9")
    assert loginguard.blocked_for("admin", "10.0.0.9") > 0
    assert loginguard.blocked_for("admin", "10.0.0.5") == 0
    for i in range(limit * loginguard.USER_LIMIT_FACTOR):
        loginguard.failed("admin", f"10.1.{i}.1")
    assert loginguard.blocked_for("admin", "10.0.0.5") > 0   # spread over many addresses it still stops
    loginguard.reset()


def test_big_body_needs_a_login(client, admin_headers):
    big = b'{"columns":["a"],"rows":[' + b"[1111111]," * 150_000 + b"[1]]}"
    plain = {"Content-Type": "application/json"}
    assert client.post("/api/export/grid", content=big, headers=plain).status_code == 401

    def chunks():
        for i in range(0, len(big), 65536):
            yield big[i:i + 65536]

    assert client.post("/api/export/grid", content=chunks(), headers=plain).status_code == 401
    assert client.post("/api/export/grid", content=big, headers={**plain, **admin_headers}).status_code == 200


def test_deactivated_user_stays_signed_out_after_reactivation(client, admin_headers):
    uid, h = _user(client, admin_headers, "gecici")
    assert client.delete(f"/api/admin/users/{uid}", headers=admin_headers).status_code == 200
    assert client.put(f"/api/admin/users/{uid}", json={"active": True}, headers=admin_headers).status_code == 200
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_default_password_warning(client, admin_headers):
    assert client.get("/api/auth/me", headers=admin_headers).json()["default_password"] is True
    _, h = _user(client, admin_headers, "sifreli", role="admin")
    assert client.get("/api/auth/me", headers=h).json()["default_password"] is False


def test_backup_has_no_signing_key_and_is_private(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / ".jwt_secret").write_text("gizli")
    (data / "resim.pdf").write_text("x")
    db = tmp_path / "b.db"
    db.write_bytes(b"")
    info = backup.create_backup(f"sqlite:///{db}", data, tmp_path / "bk", keep_days=30)
    assert os.name == "nt" or info.path.stat().st_mode & 0o077 == 0   # Windows has no mode bits
    with tarfile.open(info.path) as t:
        names = t.getnames()
    assert "data/resim.pdf" in names and "data/.jwt_secret" not in names


def test_parallel_stock_moves_all_count(client, admin_headers):
    i = client.post("/api/stock", json={"code": "PARALEL-1", "name": "Vida", "qty": 0}, headers=admin_headers).json()

    def one(_):
        return client.post(f"/api/stock/{i['id']}/moves", json={"kind": "in", "qty": 1}, headers=admin_headers).status_code

    with ThreadPoolExecutor(8) as pool:
        codes = list(pool.map(one, range(24)))
    assert set(codes) <= {200, 201}
    moves = client.get(f"/api/stock/{i['id']}/moves", headers=admin_headers).json()
    assert sorted(m["balance"] for m in moves) == [float(n) for n in range(1, 25)]


def test_backup_leaves_live_database_and_old_backups_alone(tmp_path):
    data = tmp_path / "data"
    bk = data / "backups"
    (data / "drawings").mkdir(parents=True)
    (data / "drawings" / "a.pdf").write_text("x")
    db = data / "erp.db"
    con = sqlite3.connect(db)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("create table t(a)")
    con.execute("insert into t values (1)")
    con.commit()
    url = f"sqlite:///{db}"
    first = backup.create_backup(url, data, bk, keep_days=30)
    time.sleep(1.1)   # one backup per second: the name is the time
    second = backup.create_backup(url, data, bk, keep_days=30)
    with tarfile.open(second.path) as t:
        names = t.getnames()
    assert "data/drawings/a.pdf" in names
    assert not [n for n in names if n.startswith(("data/erp.db", "data/backups"))]
    assert (data / "erp.db-wal").exists()      # the live connection kept its locks

    con.execute("insert into t values (2)")
    con.commit()
    con.close()
    backup.restore_backup(first.path, url, data, bk)
    con = sqlite3.connect(db)
    assert con.execute("select count(*) from t").fetchone()[0] == 1
    con.close()
    assert first.path.exists() and (data / "drawings" / "a.pdf").exists()


def test_parallel_sales_orders_get_their_own_numbers(client, admin_headers):
    firm = client.post("/api/admin/firms", json={"name": "Paralel AŞ", "kind": "customer"}, headers=admin_headers).json()

    def one(_):
        return client.post("/api/sales-orders", json={"firm_id": firm["id"], "lines": []}, headers=admin_headers).status_code

    with ThreadPoolExecutor(8) as pool:
        assert set(pool.map(one, range(16))) == {201}


def test_firm_with_documents_cannot_be_deleted(client, admin_headers):
    firm = client.post("/api/admin/firms", json={"name": "Borçlu AŞ", "kind": "customer"}, headers=admin_headers).json()
    assert client.post("/api/sales-orders", json={"firm_id": firm["id"], "lines": []}, headers=admin_headers).status_code == 201
    assert client.delete(f"/api/admin/firms/{firm['id']}", headers=admin_headers).status_code == 400


def test_sales_order_is_invoiced_once(client, admin_headers):
    firm = client.post("/api/admin/firms", json={"name": "Tek Fatura AŞ", "kind": "customer"}, headers=admin_headers).json()
    so = client.post("/api/sales-orders", headers=admin_headers, json={
        "firm_id": firm["id"], "lines": [{"description": "İş", "qty": 1, "unit_price": 100}]}).json()
    assert client.post(f"/api/sales-orders/{so['id']}/status", json={"status": "confirmed"}, headers=admin_headers).status_code == 200
    assert client.post(f"/api/sales-orders/{so['id']}/invoice", headers=admin_headers).status_code == 201
    r = client.post(f"/api/sales-orders/{so['id']}/invoice", headers=admin_headers)
    assert r.status_code == 400 and "zaten var" in r.json()["detail"]
