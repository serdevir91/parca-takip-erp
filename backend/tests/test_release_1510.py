"""Session cookie, edit conflicts, public holidays, short closing, credit notes, balance basis, manual rate."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import auth as auth_module
from app.db import SessionLocal
from app.main import app
from app.models import Invoice
from app.services import commerce
from tests.test_commerce_flow import L, customer, deliver, item, ok, po, po_invoice, receive, so, so_invoice, stock, supplier, _u
from tests.test_security_fixes import _user

TODAY = date.today()
APP = {"X-Requested-With": "LabERP"}


@pytest.fixture(scope="module")
def h(admin_headers):
    return admin_headers


def browser():
    return TestClient(app)


def sign_in(c, client, h):
    name = _u("kullanici")
    _user(client, h, name, "viewer")
    c.cookies.clear()
    r = c.post("/api/auth/login", data={"username": name, "password": "pass1234"})
    assert r.status_code == 200, r.text
    return r


# ---------- session cookie ----------
def test_login_sets_an_http_only_strict_cookie(client, h):
    with browser() as c:
        r = sign_in(c, client, h)
        head = r.headers["set-cookie"].lower()
        assert auth_module.COOKIE_HTTP in head and "httponly" in head and "samesite=strict" in head and "path=/api" in head
        assert "secure" not in head
        assert c.get("/api/auth/me").status_code == 200


def test_https_gets_its_own_secure_cookie(client, h):
    with TestClient(app, base_url="https://testserver") as c:
        r = sign_in(c, client, h)
        head = r.headers["set-cookie"].lower()
        assert auth_module.COOKIE_HTTPS in head and "secure" in head
        assert c.get("/api/auth/me").status_code == 200


def test_cookie_needs_the_app_header_on_writes(client, h):
    with browser() as c:
        sign_in(c, client, h)
        body = {"full_name": "Yeni Ad", "email": ""}
        assert c.put("/api/auth/me", json=body).status_code == 403
        assert c.put("/api/auth/me", json=body, headers=APP).status_code == 200


def test_logout_ends_the_cookie(client, h):
    with browser() as c:
        sign_in(c, client, h)
        assert c.post("/api/auth/logout", headers=APP).status_code in (200, 204)
        assert c.get("/api/auth/me").status_code == 401


def test_old_bearer_token_moves_into_the_cookie(client, h):
    name = _u("tasiyan")
    _, bearer = _user(client, h, name, "viewer")
    with browser() as c:
        assert c.post("/api/auth/session", headers=bearer).status_code in (200, 204)
        assert c.get("/api/auth/me").status_code == 200


def test_file_ticket_opens_only_its_own_path(client, h):
    with browser() as c:
        sign_in(c, client, h)
        token = c.post("/api/auth/file-ticket", json={"path": "/stock.xlsx?x=1"}, headers=APP).json()["token"]
    bearer = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/auth/me", headers=bearer).status_code == 401
    assert client.get("/api/projects", headers=bearer).status_code == 401
    assert client.get("/api/stock.xlsx", headers=bearer).status_code != 401


# ---------- edit conflicts ----------
def test_second_save_on_the_same_revision_is_stopped(client, h):
    i = ok(client.post("/api/stock", headers=h, json={"code": _u("C"), "name": "x", "qty": 0}), 201)
    rev = i["rev"]
    ok(client.put(f"/api/stock/{i['id']}", headers=h, json={"name": "ilk", "rev": rev}))
    r = client.put(f"/api/stock/{i['id']}", headers=h, json={"name": "ikinci", "rev": rev})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["conflict"] is True and detail["by"] == "admin" and detail["rev"] == rev + 1
    assert stock(client, h, i["id"])["name"] == "ilk"
    # Saving anyway is a request without a revision
    ok(client.put(f"/api/stock/{i['id']}", headers=h, json={"name": "ikinci"}))
    assert stock(client, h, i["id"])["name"] == "ikinci"


@pytest.mark.parametrize("kind", ["po", "so", "firm", "employee", "project"])
def test_forms_are_guarded(client, h, kind):
    if kind == "po":
        o = po(client, h, [L()], status="draft")
        url, body = f"/api/purchase-orders/{o['id']}", {"note": "a"}
    elif kind == "so":
        o = so(client, h, [L()], status="draft")
        url, body = f"/api/sales-orders/{o['id']}", {"note": "a"}
    elif kind == "firm":
        o = ok(client.post("/api/admin/firms", headers=h, json={"name": _u("F"), "kind": "customer"}), 201)
        url, body = f"/api/admin/firms/{o['id']}", {"note": "a"}
    elif kind == "employee":
        o = ok(client.post("/api/employees", headers=h, json={"name": _u("P")}), 201)
        url, body = f"/api/employees/{o['id']}", {"note": "a"}
    else:
        o = ok(client.post("/api/projects", headers=h, json={"name": _u("Pr")}), 201)
        url, body = f"/api/projects/{o['id']}", {"description": "a"}
    send = client.patch if kind == "project" else client.put
    rev = o["rev"]
    ok(send(url, headers=h, json={**body, "rev": rev}))
    assert send(url, headers=h, json={**body, "rev": rev}).status_code == 409


# ---------- public holidays ----------
def test_holiday_list_is_admin_edited_and_lowers_expected_days(client, h):
    year = 2031
    viewer = _user(client, h, _u("izleyen"), "viewer")[1]
    assert client.post("/api/holidays", headers=viewer, json={"day": f"{year}-03-03", "name": "x"}).status_code == 403
    made = ok(client.post("/api/holidays", headers=h, json={"day": f"{year}-03-03", "until": f"{year}-03-05", "name": "Bayram"}), 201)
    assert made["added"] == 3
    assert ok(client.post("/api/holidays/fixed", headers=h, json={"year": year}), 201)["added"] > 0
    assert ok(client.post("/api/holidays/fixed", headers=h, json={"year": year}), 201)["added"] == 0
    rows = ok(client.get(f"/api/holidays?year={year}", headers=h))
    assert any(x["day"] == f"{year}-04-23" for x in rows)
    assert next(x for x in rows if x["half_day"])["day"] == f"{year}-10-28"
    target = next(x for x in rows if x["name"] == "Bayram")
    ok(client.put(f"/api/holidays/{target['id']}", headers=h, json={"name": "Arife", "half_day": True}))
    assert client.delete(f"/api/holidays/{target['id']}", headers=h).status_code in (200, 204)


def test_working_days_skip_holidays():
    from app.core.attendance import working_days

    mon = date(2026, 11, 2)
    fri = mon + timedelta(days=4)
    assert working_days(mon, fri) == 5
    assert working_days(mon, fri, {mon: 1.0, fri: 0.5}) == 3.5


# ---------- short closing ----------
def test_sales_order_closes_short(client, h):
    c = item(client, h, _u("KK"), qty=20, cost=1)
    code = next(i["code"] for i in ok(client.get("/api/stock", headers=h))["rows"] if i["id"] == c)
    o = so(client, h, [L(qty=10, code=code)])
    assert client.post(f"/api/sales-orders/{o['id']}/close", headers=h, json={"note": "x"}).status_code == 400
    ok(deliver(client, h, o, 4))
    r = ok(client.post(f"/api/sales-orders/{o['id']}/close", headers=h, json={"note": "Müşteri vazgeçti"}))
    assert r["status"] == "closed" and r["status_label"] == "Eksik kapatıldı" and not r["late"]
    assert deliver(client, h, o, 1).status_code == 400
    assert client.put(f"/api/sales-orders/{o['id']}", headers=h, json={"note": "y"}).status_code == 400
    # Only what shipped can be billed; a return does not reopen the order
    inv = ok(so_invoice(client, h, o), 201)
    assert inv["lines"][0]["qty"] == 4
    back = ok(deliver(client, h, o, 1, path="return"))
    assert back["status"] == "closed"


# ---------- credit notes ----------
def _billed_order(client, h, qty=10, price=100.0):
    c = item(client, h, _u("DK"), qty=50, cost=1)
    code = next(i["code"] for i in ok(client.get("/api/stock", headers=h))["rows"] if i["id"] == c)
    o = so(client, h, [L(qty=qty, price=price, code=code)], tax_rate=20)
    ok(deliver(client, h, o, qty))
    inv = ok(so_invoice(client, h, o), 201)
    ok(client.post(f"/api/invoices/{inv['id']}/status", headers=h, json={"status": "issued"}))
    return o, inv


def test_return_drafts_a_credit_note_that_lowers_the_invoice(client, h):
    o, inv = _billed_order(client, h)
    r = ok(client.post(f"/api/sales-orders/{o['id']}/return", headers=h, json={
        "lines": [{"line_id": o["lines"][0]["id"], "qty": 3}], "credit_note": True}))
    assert len(r["credits"]) == 1
    note = ok(client.get(f"/api/invoices/{r['credits'][0]['id']}", headers=h))
    assert note["kind"] == "sales_credit" and note["status"] == "draft" and note["is_credit"]
    assert note["credit_of_id"] == inv["id"] and note["total"] == 360.0
    assert ok(client.get(f"/api/invoices/{inv['id']}", headers=h))["remaining"] == 1200.0   # a draft changes nothing yet
    ok(client.post(f"/api/invoices/{note['id']}/status", headers=h, json={"status": "issued"}))
    fresh = ok(client.get(f"/api/invoices/{inv['id']}", headers=h))
    assert fresh["credited"] == 360.0 and fresh["remaining"] == 840.0
    assert fresh["credits"][0]["id"] == note["id"]
    # The invoice cannot be cancelled while a credit note stands on it, and a credit note takes no payment
    assert client.post(f"/api/invoices/{inv['id']}/status", headers=h, json={"status": "cancelled"}).status_code == 400
    assert client.post("/api/payments", headers=h, json={
        "direction": "in", "firm_id": note["firm_id"], "invoice_id": note["id"], "amount": 10, "pay_date": TODAY.isoformat(),
        "method": "Nakit"}).status_code == 400


def test_draft_credit_on_a_short_closed_order_stays_editable(client, h):
    """Billed ahead of delivery, then short closed: the bill is over the delivered quantity until the note is issued."""
    c = item(client, h, _u("DK"), qty=50, cost=1)
    code = next(i["code"] for i in ok(client.get("/api/stock", headers=h))["rows"] if i["id"] == c)
    o = so(client, h, [L(qty=5, price=100.0, code=code)], tax_rate=20)
    inv = ok(so_invoice(client, h, o), 201)
    ok(client.post(f"/api/invoices/{inv['id']}/status", headers=h, json={"status": "issued"}))
    ok(deliver(client, h, o, 2))
    line = o["lines"][0]["id"]
    r = ok(client.post(f"/api/sales-orders/{o['id']}/return", headers=h, json={
        "lines": [{"line_id": line, "qty": 1}], "credit_note": True}))
    ok(client.post(f"/api/sales-orders/{o['id']}/close", headers=h, json={}))
    note = ok(client.get(f"/api/invoices/{r['credits'][0]['id']}", headers=h))
    row = {k: note["lines"][0][k] for k in ("code", "description", "unit", "unit_price")}
    url = f"/api/invoices/{note['id']}"
    edited = ok(client.put(url, headers=h, json={"rev": note["rev"], "note": "düzeltildi",
                                                 "lines": [{**row, "qty": 5}]}))
    assert edited["lines"][0]["qty"] == 5
    assert client.put(url, headers=h, json={"rev": edited["rev"], "lines": [{**row, "qty": 6}]}).status_code == 400


def test_every_invoice_kind_fits_its_column():
    """SQLite does not enforce the length, PostgreSQL refuses the row."""
    assert max(map(len, {*commerce.INV_KINDS, *commerce.CREDIT_OF})) <= Invoice.__table__.c.kind.type.length


def test_credit_cannot_pass_the_invoice(client, h):
    o, _ = _billed_order(client, h, qty=2)
    line = {"line_id": o["lines"][0]["id"], "qty": 2}
    first = ok(client.post(f"/api/sales-orders/{o['id']}/return", headers=h, json={"lines": [line], "credit_note": True}))
    assert first["credits"]
    ok(deliver(client, h, o, 2))
    again = ok(client.post(f"/api/sales-orders/{o['id']}/return", headers=h, json={"lines": [line], "credit_note": True}))
    assert again["credits"] == []


def test_credit_note_needs_finance_edit(client, h):
    o, _ = _billed_order(client, h)
    planner = _user(client, h, _u("plan"), "planner")[1]
    r = client.post(f"/api/sales-orders/{o['id']}/return", headers=planner, json={
        "lines": [{"line_id": o["lines"][0]["id"], "qty": 1}], "credit_note": True})
    assert r.status_code == 403


def test_supplier_return_drafts_a_purchase_credit(client, h):
    o = po(client, h, [L(qty=5, price=10)])
    ok(receive(client, h, o, 5))
    inv = ok(po_invoice(client, h, o), 201)
    ok(client.post(f"/api/invoices/{inv['id']}/status", headers=h, json={"status": "issued"}))
    r = ok(client.post(f"/api/purchase-orders/{o['id']}/reverse", headers=h, json={
        "lines": [{"line_id": o["lines"][0]["id"], "qty": 2}], "note": "Kusurlu", "credit_note": True}))
    note = r["credits"][0]
    assert note["kind"] == "purchase_credit" and note["credit_of_id"] == inv["id"]


# ---------- balance basis ----------
def test_basis_values_the_balance_at_document_or_today(client, h):
    day = TODAY - timedelta(days=30)
    ok(client.post("/api/rates", headers=h, json={"currency": "CHF", "rate": 30, "rate_date": day.isoformat()}), 201)
    firm = customer(client, h)
    inv = ok(client.post("/api/invoices", headers=h, json={
        "kind": "sales", "firm_id": firm, "invoice_date": day.isoformat(), "currency": "CHF", "tax_rate": 0,
        "lines": [{"code": "", "description": "Hizmet", "qty": 1, "unit_price": 100}]}), 201)
    ok(client.post(f"/api/invoices/{inv['id']}/status", headers=h, json={"status": "issued"}))
    ok(client.post("/api/rates", headers=h, json={"currency": "CHF", "rate": 40, "rate_date": TODAY.isoformat()}), 201)

    def row(basis):
        return next(b for b in ok(client.get(f"/api/balances?basis={basis}", headers=h)) if b["firm_id"] == firm)

    today, doc = row("today"), row("doc")
    assert today["basis"] == "today" and today["base_balance"] == 4000.0
    assert doc["basis"] == "doc" and doc["base_balance"] == 3000.0
    assert doc["fx_diff"] == -1000.0
    ledger = ok(client.get(f"/api/firms/{firm}/ledger?basis=doc", headers=h))
    assert ledger["base_balance"] == 3000.0 and ledger["basis"] == "doc"
    assert client.get("/api/balances?basis=yanlis", headers=h).status_code == 400


# ---------- manual rate at goods receipt ----------
def test_rate_typed_at_receipt_is_used_and_refused_when_not_needed(client, h):
    code = _u("MK")
    c = item(client, h, code)
    o = po(client, h, [L(qty=2, price=10, code=code)], currency="XOF")
    assert o["needs_rate"] is True
    assert receive(client, h, o, 1).status_code == 400
    r = client.post(f"/api/purchase-orders/{o['id']}/receive", headers=h, json={
        "lines": [{"line_id": o["lines"][0]["id"], "qty": 1}], "rate": 0.05})
    got = ok(r)
    assert got["rate"] == 0.05 and got["needs_rate"] is False
    assert stock(client, h, c)["unit_cost"] == 0.5
    again = client.post(f"/api/purchase-orders/{o['id']}/receive", headers=h, json={
        "lines": [{"line_id": o["lines"][0]["id"], "qty": 1}], "rate": 9})
    assert again.status_code == 400
    plain = po(client, h, [L(qty=1, price=10)])
    assert client.post(f"/api/purchase-orders/{plain['id']}/receive", headers=h, json={
        "lines": [{"line_id": plain["lines"][0]["id"], "qty": 1}], "rate": 9}).status_code == 400


# ---------- time stamps ----------
def test_timestamps_leave_the_api_with_their_offset(client, h):
    o = po(client, h, [L()], status="draft")
    stamp = o["created_at"]
    assert stamp.endswith("+00:00") or stamp.endswith("Z")
    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    assert abs(datetime.now(timezone.utc) - parsed) < timedelta(minutes=5)


# ---------- invoices from before the rule ----------
def test_issued_invoice_keeps_its_printed_total(client, h):
    inv = ok(client.post("/api/invoices", headers=h, json={
        "kind": "sales", "firm_id": customer(client, h), "tax_rate": 20,
        "lines": [{"code": "", "description": "a", "qty": 3, "unit_price": 0.335},
                  {"code": "", "description": "b", "qty": 3, "unit_price": 0.335}]}), 201)
    assert inv["subtotal"] == 2.02        # 1.01 + 1.01 under the rule
    with SessionLocal() as db:
        db.get(Invoice, inv["id"]).legacy_total = True
        db.commit()
    assert ok(client.get(f"/api/invoices/{inv['id']}", headers=h))["subtotal"] == 2.01


# ---------- admin warnings ----------
def test_admin_sees_plain_http_and_open_signup_warnings(client, h):
    ok(client.put("/api/admin/settings/signup", headers=h, json={"value": {"enabled": True}}))
    try:
        feed = ok(client.get("/api/notifications", headers=h))
        keys = {w["key"] for w in feed["warnings"]}
        assert {"admin:https-off", "admin:signup-on"} <= keys
        ok(client.post("/api/notifications/read", headers=h, json={"keys": ["admin:https-off"]}))
        # Reading it in the bell does not end the banner, and the setting itself stayed as it was
        assert "admin:https-off" in {w["key"] for w in ok(client.get("/api/notifications", headers=h))["warnings"]}
        secure = ok(client.get("/api/notifications", headers={**h, "X-Forwarded-Proto": "https"}))
        assert "admin:https-off" not in {w["key"] for w in secure["warnings"]}
        viewer = _user(client, h, _u("gorur"), "viewer")[1]
        assert ok(client.get("/api/notifications", headers=viewer))["warnings"] == []
    finally:
        ok(client.put("/api/admin/settings/signup", headers=h, json={"value": {"enabled": False}}))
