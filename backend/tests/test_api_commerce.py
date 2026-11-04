"""Ticari modules: sales orders, invoices, payments, current account, HR time entries and the overview."""
from __future__ import annotations

import io
import uuid
from datetime import date, timedelta

import pytest
from openpyxl import load_workbook


def _u(p: str) -> str:
    return f"{p} {uuid.uuid4().hex[:6]}"


@pytest.fixture(scope="module")
def customer(client, admin_headers):
    r = client.post("/api/admin/firms", headers=admin_headers, json={"name": _u("Müşteri"), "kind": "customer"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def pid(client, admin_headers):
    return client.post("/api/projects", json={"name": _u("Satış projesi")}, headers=admin_headers).json()["id"]


def test_customer_picker(client, admin_headers, customer):
    ids = [f["id"] for f in client.get("/api/firms", params={"kind": "customer"}, headers=admin_headers).json()]
    assert customer in ids


def test_sales_order_to_invoice_to_payment(client, admin_headers, customer, pid):
    h = admin_headers
    r = client.post("/api/sales-orders", headers=h, json={
        "firm_id": customer, "project_id": pid, "tax_rate": 20, "discount_pct": 10,
        "valid_until": (date.today() + timedelta(days=15)).isoformat(),
        "lines": [{"code": "M-01", "description": "Makine", "qty": 1, "unit_price": 1000},
                  {"description": "Montaj", "unit": "Saat", "qty": 10, "unit_price": 50}]})
    assert r.status_code == 201, r.text
    so = r.json()
    assert so["no"].startswith(f"SS-{date.today().year}-") and so["status"] == "draft"
    assert (so["subtotal"], so["discount"], so["tax"], so["total"]) == (1500, 150, 270, 1620)
    # quote form
    x = client.get(f"/api/sales-orders/{so['id']}/xlsx", headers=h)
    assert x.status_code == 200
    ws = load_workbook(io.BytesIO(x.content)).active
    assert ws["A1"].value == "FİYAT TEKLİFİ"
    # invoice only after confirmation; bad transitions refused
    assert client.post(f"/api/sales-orders/{so['id']}/invoice", headers=h).status_code == 400
    assert client.post(f"/api/sales-orders/{so['id']}/status", headers=h, json={"status": "delivered"}).status_code == 400
    for s in ("quoted", "confirmed"):
        assert client.post(f"/api/sales-orders/{so['id']}/status", headers=h, json={"status": s}).status_code == 200
    assert client.put(f"/api/sales-orders/{so['id']}", headers=h, json={"discount_pct": 0}).status_code == 400
    r = client.post(f"/api/sales-orders/{so['id']}/invoice", headers=h)
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["no"].startswith("FT-") and inv["kind"] == "sales" and inv["total"] == 1620
    assert client.get(f"/api/sales-orders/{so['id']}", headers=h).json()["invoiced"] == 1620
    # draft invoices do not count in the balance; issued ones do
    def bal():
        return next((b for b in client.get("/api/balances", headers=h).json() if b["firm_id"] == customer), None)
    assert bal() is None
    assert client.post("/api/payments", headers=h, json={
        "direction": "in", "invoice_id": inv["id"], "amount": 10}).status_code == 400   # not issued yet
    assert client.put(f"/api/invoices/{inv['id']}", headers=h,
                      json={"due_date": (date.today() - timedelta(days=1)).isoformat()}).status_code == 200
    assert client.post(f"/api/invoices/{inv['id']}/status", headers=h, json={"status": "issued"}).status_code == 200
    assert client.put(f"/api/invoices/{inv['id']}", headers=h, json={"note": "x"}).status_code == 400
    b = bal()
    assert b["receivable"] == 1620 and b["overdue_receivable"] == 1620
    assert client.get(f"/api/invoices/{inv['id']}", headers=h).json()["pay_state"] == "overdue"
    # payments: wrong direction and overpayment refused
    assert client.post("/api/payments", headers=h, json={
        "direction": "out", "invoice_id": inv["id"], "amount": 10}).status_code == 400
    assert client.post("/api/payments", headers=h, json={
        "direction": "in", "invoice_id": inv["id"], "amount": 5000}).status_code == 400
    p1 = client.post("/api/payments", headers=h, json={"direction": "in", "invoice_id": inv["id"], "amount": 620})
    assert p1.status_code == 201, p1.text
    assert p1.json()["firm_id"] == customer
    got = client.get(f"/api/invoices/{inv['id']}", headers=h).json()
    assert (got["paid"], got["remaining"], got["pay_state"]) == (620, 1000, "overdue")
    assert client.post(f"/api/invoices/{inv['id']}/status", headers=h, json={"status": "cancelled"}).status_code == 400
    client.post("/api/payments", headers=h, json={"direction": "in", "invoice_id": inv["id"], "amount": 1000})
    assert client.get(f"/api/invoices/{inv['id']}", headers=h).json()["pay_state"] == "paid"
    b = bal()
    assert b["balance"] == 0 and b["overdue_receivable"] == 0 and b["collected"] == 1620
    # ledger: invoice +1620, two payments, running balance ends at 0
    led = client.get(f"/api/firms/{customer}/ledger", headers=h).json()
    assert [r["doc"] for r in led["rows"]] == ["invoice", "payment", "payment"]
    assert led["rows"][0]["debit"] == 1620 and led["rows"][-1]["balance"] == 0
    assert led["balance"] == {"TRY": 0}
    # copy as a new draft
    cp = client.post(f"/api/sales-orders/{so['id']}/copy", headers=h).json()
    assert cp["status"] == "draft" and cp["no"] != so["no"] and cp["total"] == 1620
    assert client.delete(f"/api/sales-orders/{cp['id']}", headers=h).status_code == 200
    assert client.delete(f"/api/sales-orders/{so['id']}", headers=h).status_code == 400


def test_purchase_invoice_from_po(client, admin_headers):
    h = admin_headers
    sup = client.post("/api/admin/firms", headers=h, json={"name": _u("Tedarikçi"), "kind": "supplier"}).json()["id"]
    po = client.post("/api/purchase-orders", headers=h, json={
        "firm_id": sup, "lines": [{"code": "X-1", "qty": 4, "unit_price": 25}]}).json()
    assert client.post(f"/api/purchase-orders/{po['id']}/invoice", headers=h,
                       json={"no": "A-1"}).status_code == 400                      # draft PO
    client.post(f"/api/purchase-orders/{po['id']}/status", headers=h, json={"status": "sent"})
    assert client.post(f"/api/purchase-orders/{po['id']}/invoice", headers=h, json={"no": " "}).status_code == 400
    r = client.post(f"/api/purchase-orders/{po['id']}/invoice", headers=h, json={"no": "TDK-778", "tax_rate": 20})
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["no"] == "TDK-778" and inv["kind"] == "purchase" and inv["total"] == 120
    client.post(f"/api/invoices/{inv['id']}/status", headers=h, json={"status": "issued"})
    b = next(b for b in client.get("/api/balances", headers=h).json() if b["firm_id"] == sup)
    assert b["payable"] == 120 and b["balance"] == -120
    # a payment on account (no invoice) lowers the payable
    assert client.post("/api/payments", headers=h, json={"direction": "out", "firm_id": sup,
                                                         "amount": 20, "method": "Nakit"}).status_code == 201
    b = next(b for b in client.get("/api/balances", headers=h).json() if b["firm_id"] == sup)
    assert b["payable"] == 100
    assert client.post("/api/payments", headers=h, json={"direction": "in", "amount": 5}).status_code == 400


def test_time_entries_add_labor_cost(client, admin_headers, pid):
    h = admin_headers
    e = client.post("/api/employees", headers=h, json={"name": "Ali Usta", "title": "Kaynakçı",
                                                       "hourly_cost": 250}).json()
    assert client.post("/api/time-entries", headers=h, json={"employee_id": e["id"], "hours": 25}).status_code == 422
    r = client.post("/api/time-entries", headers=h, json={"employee_id": e["id"], "hours": 8, "project_id": pid})
    assert r.status_code == 201, r.text
    assert r.json()["cost"] == 2000
    # rate change later does not rewrite the entry
    client.put(f"/api/employees/{e['id']}", headers=h, json={"hourly_cost": 400})
    t = client.get("/api/time-entries", headers=h, params={"project_id": pid}).json()
    assert t["total_hours"] == 8 and t["total_cost"] == 2000
    costs = client.get(f"/api/projects/{pid}/costs", headers=h).json()
    assert {"name": "İşçilik", "committed": 2000, "actual": 2000} in costs["by_source"]
    emp = next(x for x in client.get("/api/employees", headers=h).json() if x["id"] == e["id"])
    assert emp["hours_30d"] == 8 and emp["hourly_cost"] == 400
    assert client.delete(f"/api/employees/{e['id']}", headers=h).status_code == 400


def test_overview_respects_permissions(client, admin_headers):
    r = client.get("/api/overview", headers=admin_headers)
    assert r.status_code == 200, r.text
    o = r.json()
    assert {"projects", "purchasing", "stock", "sales", "finance", "hr"} <= o.keys()
    assert len(o["activity"]) == 30
    name = _u("ov").replace(" ", "_")
    client.post("/api/admin/users", headers=admin_headers, json={
        "username": name, "password": "ov123456", "role": "viewer", "permissions": {"sales": "view"}})
    tok = client.post("/api/auth/login", data={"username": name, "password": "ov123456"}).json()["access_token"]
    vh = {"Authorization": f"Bearer {tok}"}
    o = client.get("/api/overview", headers=vh).json()
    assert "finance" not in o and "sales" in o
    assert client.get("/api/balances", headers=vh).status_code == 403
    assert client.get("/api/sales-orders", headers=vh).status_code == 200
    assert client.post("/api/sales-orders", headers=vh, json={"firm_name": "x"}).status_code == 403


def _login(client, admin_headers, role: str, **extra) -> tuple[dict, int]:
    name = _u(role).replace(" ", "_")
    u = client.post("/api/admin/users", headers=admin_headers, json={
        "username": name, "password": "pw123456", "role": role, **extra})
    assert u.status_code in (200, 201), u.text
    tok = client.post("/api/auth/login", data={"username": name, "password": "pw123456"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}, u.json()["id"]


def test_role_defaults_hide_wages_money_and_deals(client, admin_headers):
    for role in ("viewer", "designer", "planner"):
        h, _ = _login(client, admin_headers, role)
        assert client.get("/api/employees", headers=h).status_code == 403, role
        assert client.get("/api/time-entries", headers=h).status_code == 403, role
        assert client.get("/api/balances", headers=h).status_code == 403, role
        o = client.get("/api/overview", headers=h).json()
        assert "hr" not in o and "finance" not in o, role
    vh, _ = _login(client, admin_headers, "viewer")
    assert client.get("/api/sales-orders", headers=vh).status_code == 403
    ph, _ = _login(client, admin_headers, "planner")
    assert client.get("/api/sales-orders", headers=ph).status_code == 200


def test_employee_sees_only_own_card(client, admin_headers, pid):
    h = admin_headers
    me_h, me_id = _login(client, admin_headers, "viewer", email=f"{uuid.uuid4().hex[:6]}@lab.test")
    mine = client.post("/api/employees", headers=h, json={"name": _u("Ayşe"), "hourly_cost": 300,
                                                          "user_id": me_id}).json()
    other = client.post("/api/employees", headers=h, json={"name": _u("Veli"), "hourly_cost": 900}).json()
    assert mine["user_id"] == me_id
    # one login, one card
    dup = client.post("/api/employees", headers=h, json={"name": "x", "user_id": me_id})
    assert dup.status_code == 409
    client.post("/api/time-entries", headers=h, json={"employee_id": mine["id"], "hours": 5, "project_id": pid})
    client.post("/api/time-entries", headers=h, json={"employee_id": other["id"], "hours": 7, "project_id": pid})
    r = client.get("/api/hr/me", headers=me_h).json()
    assert r["employee"]["id"] == mine["id"] and r["employee"]["hourly_cost"] == 300
    assert {x["employee_id"] for x in r["rows"]} == {mine["id"]} and r["total_hours"] == 5
    # no card: empty answer, not an error
    nh, _ = _login(client, admin_headers, "viewer")
    assert client.get("/api/hr/me", headers=nh).json()["employee"] is None
    # project cost without hr rights: labour shows no names
    pl, _ = _login(client, admin_headers, "planner")
    firms = {x["name"] for x in client.get(f"/api/projects/{pid}/costs", headers=pl).json()["by_firm"]}
    assert other["name"] not in firms and mine["name"] not in firms and "İşçilik" in firms
    firms = {x["name"] for x in client.get(f"/api/projects/{pid}/costs", headers=h).json()["by_firm"]}
    assert other["name"] in firms
    assert client.get("/api/hr/users", headers=me_h).status_code == 403
    assert any(u["id"] == me_id for u in client.get("/api/hr/users", headers=h).json())
