"""Sistem Ayarları: values are validated, stored as differences and reach the code that reads them."""
import io

import pytest
from openpyxl import load_workbook

from app.config import get_settings
from app.services import loginguard


def put(client, headers, value):
    return client.put("/api/admin/settings/system", json={"value": value}, headers=headers)


@pytest.fixture(autouse=True)
def clean_system(client, admin_headers):
    loginguard.reset()
    yield
    assert put(client, admin_headers, {}).status_code == 200
    loginguard.reset()


def login(client, username="admin", password="admin"):
    return client.post("/api/auth/login", data={"username": username, "password": password})


def user_headers(client, admin_headers, name, role="viewer"):
    r = client.post("/api/admin/users", json={"username": name, "password": "Parola1234", "role": role},
                    headers=admin_headers)
    assert r.status_code in (200, 201), r.text
    t = login(client, name, "Parola1234").json()["access_token"]
    return {"Authorization": f"Bearer {t}"}


def test_defaults_and_partial_save(client, admin_headers):
    s = client.get("/api/admin/settings", headers=admin_headers).json()["system"]
    assert s["company"]["app_name"] == "LAB ERP" and s["commerce"]["currency"] == "TRY"
    r = put(client, admin_headers, {"company": {"app_name": "Atölye ERP", "name": "Örnek A.Ş."}})
    assert r.status_code == 200, r.text
    v = r.json()["system"]
    assert v["company"]["app_name"] == "Atölye ERP" and v["commerce"]["vat"] == 20
    o = client.get("/api/auth/options").json()
    assert o["app_name"] == "Atölye ERP" and o["password_min"] == 8


@pytest.mark.parametrize("value", [
    {"company": {"app_name": " "}},
    {"company": {"logo": "data:text/html;base64,AAAA"}},
    {"commerce": {"currency": "LIRA"}},
    {"commerce": {"vat": 101}},
    {"commerce": {"no_po": "S A"}},
    {"commerce": {"pay_methods": []}},
    {"production": {"work_hours": 25}},
    {"security": {"password_min": 3}},
    {"security": {"session_hours": 1.5}},
    {"files": {"backup_time": "25:00"}},
    {"modules": {"off": ["admin"]}},
    {"modules": {"off": ["yok"]}},
    "metin",
])
def test_bad_values_are_refused(client, admin_headers, value):
    assert put(client, admin_headers, value).status_code == 400


def test_commerce_defaults_reach_new_documents(client, admin_headers):
    r = put(client, admin_headers, {"commerce": {"currency": "EUR", "vat": 10, "no_so": "TK", "no_po": "PO"}})
    assert r.status_code == 200, r.text
    line = {"code": "A1", "description": "Parça", "qty": 1, "unit_price": 100}
    so = client.post("/api/sales-orders", json={"firm_name": "Müşteri", "lines": [line]}, headers=admin_headers)
    assert so.status_code in (200, 201), so.text
    d = so.json()
    assert d["no"].startswith("TK-") and d["currency"] == "EUR" and d["tax_rate"] == 10
    po = client.post("/api/purchase-orders", json={"lines": [line]}, headers=admin_headers)
    assert po.status_code in (200, 201), po.text
    assert po.json()["no"].startswith("PO-") and po.json()["currency"] == "EUR"
    me = client.get("/api/auth/me", headers=admin_headers).json()
    assert me["system"]["currency"] == "EUR" and me["system"]["vat"] == 10


def test_company_prints_on_forms(client, admin_headers):
    put(client, admin_headers, {"company": {"name": "Örnek A.Ş.", "address": "Sanayi Cad. 1"}})
    po = client.post("/api/purchase-orders", json={"lines": [{"code": "A1", "description": "x", "qty": 1}]},
                     headers=admin_headers).json()
    r = client.get(f"/api/purchase-orders/{po['id']}/xlsx", headers=admin_headers)
    assert r.status_code == 200, r.text
    ws = load_workbook(io.BytesIO(r.content)).active
    assert ws["E1"].value == "Örnek A.Ş." and ws["E2"].value == "Sanayi Cad. 1"


def test_security_settings_apply(client, admin_headers):
    h = user_headers(client, admin_headers, "guvenlik1")
    put(client, admin_headers, {"security": {"password_min": 12, "login_attempts": 3, "session_hours": 2}})
    assert get_settings().jwt_expire_hours == 2
    r = client.post("/api/auth/password", json={"old_password": "Parola1234", "new_password": "Kisa12345"},
                    headers=h)
    assert r.status_code == 400 and "12" in r.json()["detail"]
    for _ in range(3):
        assert login(client, "guvenlik1", "yanlis").status_code == 401
    assert login(client, "guvenlik1", "Parola1234").status_code == 429


def test_switched_off_module_closes_for_everyone(client, admin_headers):
    assert client.get("/api/stock", headers=admin_headers).status_code == 200
    r = put(client, admin_headers, {"modules": {"off": ["stock"]}})
    assert r.status_code == 200, r.text
    assert client.get("/api/stock", headers=admin_headers).status_code == 403
    me = client.get("/api/auth/me", headers=admin_headers).json()
    assert me["permissions"]["stock"] == "none" and me["system"]["modules_off"] == ["stock"]
    assert client.get("/api/admin/settings", headers=admin_headers).status_code == 200
    put(client, admin_headers, {})
    assert client.get("/api/stock", headers=admin_headers).status_code == 200


def test_material_status_list(client, admin_headers):
    url = "/api/admin/settings/material_status_choices"
    old = client.get("/api/admin/settings", headers=admin_headers).json()["material_status_choices"]
    assert client.put(url, json={"value": []}, headers=admin_headers).status_code == 400
    r = client.put(url, json={"value": [*old, "Depoda bekliyor"]}, headers=admin_headers)
    assert r.json()["material_status_choices"][-1] == "Depoda bekliyor"
    assert client.put(url, json={"value": old}, headers=admin_headers).status_code == 200


def test_new_install_has_no_company_data():
    from app.core.t35 import DEFAULT_MANUFACTURERS, DEFAULT_RULES

    assert DEFAULT_MANUFACTURERS == []
    assert not any("İHMA" in " ".join(r["all"]) for r in DEFAULT_RULES)
