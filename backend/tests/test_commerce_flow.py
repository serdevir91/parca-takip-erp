"""Follows money through orders, deliveries, invoices and rates: exchange rates, partial receipts and deliveries,
reversals, line by line billing, the current account and supplier performance."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app import cli
from app.services import fx
from tests.test_security_fixes import _user

TODAY = date.today()
DAY = timedelta(days=1)


def _u(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:6]}"


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


@pytest.fixture(scope="module")
def h(admin_headers):
    return admin_headers


@pytest.fixture(scope="module")
def rates(client, h):
    """EUR 40 thirty days ago, 50 today; USD 30. GBP is left for tests; XAF never gets a rate."""
    for cur, val, day in (("EUR", 40, TODAY - 30 * DAY), ("EUR", 50, TODAY), ("USD", 30, TODAY)):
        ok(client.post("/api/rates", headers=h, json={"currency": cur, "rate": val, "rate_date": day.isoformat()}), 201)


def supplier(client, h):
    return ok(client.post("/api/admin/firms", headers=h, json={"name": _u("Tedarikçi"), "kind": "supplier"}), 201)["id"]


def customer(client, h):
    return ok(client.post("/api/admin/firms", headers=h, json={"name": _u("Müşteri"), "kind": "customer"}), 201)["id"]


def project(client, h):
    return ok(client.post("/api/projects", headers=h, json={"name": _u("Proje")}), 201)["id"]


def item(client, h, code, qty=0, cost=None):
    return ok(client.post("/api/stock", headers=h, json={"code": code, "name": code, "qty": qty, "unit_cost": cost}), 201)["id"]


def stock(client, h, item_id):
    return next(i for i in ok(client.get("/api/stock", headers=h))["rows"] if i["id"] == item_id)


def po(client, h, lines, firm=None, status="sent", **kw):
    body = {"firm_id": firm or supplier(client, h), "lines": lines, **kw}
    o = ok(client.post("/api/purchase-orders", headers=h, json=body), 201)
    if status != "draft":
        ok(client.post(f"/api/purchase-orders/{o['id']}/status", headers=h, json={"status": status}))
    return ok(client.get(f"/api/purchase-orders/{o['id']}", headers=h))


def so(client, h, lines, firm=None, status="confirmed", **kw):
    o = ok(client.post("/api/sales-orders", headers=h, json={"firm_id": firm or customer(client, h), "lines": lines, **kw}), 201)
    if status != "draft":
        ok(client.post(f"/api/sales-orders/{o['id']}/status", headers=h, json={"status": status}))
    return ok(client.get(f"/api/sales-orders/{o['id']}", headers=h))


def receive(client, h, o, *qty):
    return client.post(f"/api/purchase-orders/{o['id']}/receive", headers=h, json={
        "lines": [{"line_id": l["id"], "qty": q} for l, q in zip(o["lines"], qty)]})


def reverse(client, h, o, *qty, note="Hatalı parti"):
    return client.post(f"/api/purchase-orders/{o['id']}/reverse", headers=h, json={
        "lines": [{"line_id": l["id"], "qty": q} for l, q in zip(o["lines"], qty)], "note": note})


def deliver(client, h, o, *qty, path="deliver"):
    return client.post(f"/api/sales-orders/{o['id']}/{path}", headers=h, json={
        "lines": [{"line_id": l["id"], "qty": q} for l, q in zip(o["lines"], qty)]})


def po_invoice(client, h, o, picks=None, **kw):
    body = {"no": _u("AF"), "tax_rate": 0, **kw}
    if picks is not None:
        body["lines"] = [{"line_id": l["id"], "qty": q} for l, q in zip(o["lines"], picks) if q]
    return client.post(f"/api/purchase-orders/{o['id']}/invoice", headers=h, json=body)


def so_invoice(client, h, o, picks=None, **kw):
    body = dict(kw)
    if picks is not None:
        body["lines"] = [{"line_id": l["id"], "qty": q} for l, q in zip(o["lines"], picks) if q]
    return client.post(f"/api/sales-orders/{o['id']}/invoice", headers=h, json=body)


def L(desc="Malzeme", qty=10.0, price=100.0, code=None):
    return {"code": code or "", "description": desc, "qty": qty, "unit_price": price}


# ---------- exchange rates ----------
BULLETIN = """<?xml version="1.0" encoding="UTF-8"?>
<Tarih_Date Tarih="{tr}" Date="{us}" Bulten_No="2026/1">
  <Currency CrossOrder="0" Kod="USD" CurrencyCode="USD"><Unit>1</Unit><ForexSelling>32.50</ForexSelling></Currency>
  <Currency CrossOrder="1" Kod="JPY" CurrencyCode="JPY"><Unit>100</Unit><ForexSelling>21.00</ForexSelling></Currency>
  <Currency CrossOrder="2" Kod="EUR" CurrencyCode="EUR"><Unit>1</Unit><ForexSelling>35.00</ForexSelling></Currency>
  <Currency CrossOrder="3" Kod="XDR" CurrencyCode="XDR"><Unit>1</Unit><ForexSelling></ForexSelling></Currency>
</Tarih_Date>"""


def bulletin(day: date) -> bytes:
    return BULLETIN.format(tr=day.strftime("%d.%m.%Y"), us=day.strftime("%m/%d/%Y")).encode()


def test_rate_on_takes_latest_on_or_before_the_day(client, h, rates):
    on = lambda c, d: client.get("/api/rates/on", headers=h, params={"currency": c, "day": d.isoformat()}).json()["rate"]  # noqa: E731
    assert on("EUR", TODAY) == 50
    assert on("EUR", TODAY - DAY) == 40
    assert on("EUR", TODAY - 31 * DAY) is None
    assert on("TRY", TODAY - 999 * DAY) == 1
    assert on("XAF", TODAY) is None


def test_manual_rate_rules(client, h):
    assert client.post("/api/rates", headers=h, json={"currency": "TRY", "rate": 2}).status_code == 400
    assert client.post("/api/rates", headers=h, json={"currency": "EURO", "rate": 2}).status_code == 400
    assert client.post("/api/rates", headers=h, json={"currency": "EUR", "rate": 0}).status_code == 422
    assert client.post("/api/rates", headers=h, json={
        "currency": "EUR", "rate": 2, "rate_date": (TODAY + DAY).isoformat()}).status_code == 400


def test_fetch_respects_unit_and_keeps_manual_rate(client, h, monkeypatch):
    day = TODAY - 200 * DAY
    ok(client.post("/api/rates", headers=h, json={"currency": "USD", "rate": 33, "rate_date": day.isoformat()}), 201)
    monkeypatch.setattr(fx, "download", lambda: bulletin(day))
    out = ok(client.post("/api/rates/fetch", headers=h))
    assert out["rate_date"] == day.isoformat()
    on = lambda c: client.get("/api/rates/on", headers=h, params={"currency": c, "day": day.isoformat()}).json()["rate"]  # noqa: E731
    assert on("JPY") == pytest.approx(0.21)     # 21 TRY per 100 yen
    assert on("USD") == 33                      # typed by hand, stays
    assert on("EUR") == 35
    assert on("XDR") is None


def test_cross_rates_through_try_when_base_is_not_try(client, h, monkeypatch):
    day = TODAY - 300 * DAY
    old = ok(client.get("/api/admin/settings", headers=h))["system"]
    assert client.put("/api/admin/settings/system", headers=h, json={"value": {
        **old, "commerce": {**old["commerce"], "currency": "EUR"}}}).status_code == 200
    try:
        monkeypatch.setattr(fx, "download", lambda: bulletin(day))
        ok(client.post("/api/rates/fetch", headers=h))
        on = lambda c: client.get("/api/rates/on", headers=h, params={"currency": c, "day": day.isoformat()}).json()["rate"]  # noqa: E731
        assert on("USD") == pytest.approx(32.5 / 35, abs=1e-5)
        assert on("TRY") == pytest.approx(1 / 35, abs=1e-5)
        assert on("EUR") == 1
    finally:
        assert client.put("/api/admin/settings/system", headers=h, json={"value": old}).status_code == 200


@pytest.mark.parametrize("reply", [b"not xml", b"<Tarih_Date Date='01/01/2026'></Tarih_Date>",
                                   b'<!DOCTYPE x [<!ENTITY a "b">]><Tarih_Date>&a;</Tarih_Date>'])
def test_bad_bulletin_is_a_clear_failure(client, h, monkeypatch, reply):
    monkeypatch.setattr(fx, "download", lambda: reply)
    r = client.post("/api/rates/fetch", headers=h)
    assert r.status_code == 502 and "Merkez Bankası" in r.json()["detail"]


def test_offline_fetch_says_so_in_turkish_and_manual_rates_still_work(client, h, monkeypatch):
    def boom(*a, **k):
        raise OSError("no route")
    monkeypatch.setattr(fx.urllib.request.OpenerDirector, "open", boom)
    r = client.post("/api/rates/fetch", headers=h)
    assert r.status_code == 502 and "elle" in r.json()["detail"]
    ok(client.post("/api/rates", headers=h, json={"currency": "CAD", "rate": 22}), 201)


def test_download_stops_at_the_size_cap(monkeypatch):
    class Big:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read1(self, n):
            return b"x" * n

    monkeypatch.setattr(fx.urllib.request.OpenerDirector, "open", lambda *a, **k: Big())
    with pytest.raises(fx.RateFetchError):
        fx.download()


def test_daily_tick_never_raises_and_runs_once_a_day(monkeypatch):
    calls = []

    def boom(db, user=None):
        calls.append(1)
        raise RuntimeError("db gone")

    monkeypatch.setattr(cli.fx, "fetch", boom)
    day = cli.daily_rates(None)
    assert day == TODAY and calls == [1]
    assert cli.daily_rates(day) == TODAY and calls == [1]


def test_rate_permissions(client, h):
    _, viewer = _user(client, h, _u("kurviewer"))
    assert client.get("/api/rates", headers=viewer).status_code == 200
    assert client.post("/api/rates", headers=viewer, json={"currency": "EUR", "rate": 1}).status_code == 403
    assert client.post("/api/rates/fetch", headers=viewer).status_code == 403
    assert client.get("/api/rates").status_code == 401


# ---------- documents fix their rate ----------
def test_documents_fix_rate_from_table_or_form(client, h, rates):
    o = po(client, h, [L()], currency="EUR", status="draft")
    assert o["rate"] == 50 and o["base_total"] == 50000
    o = po(client, h, [L()], currency="EUR", rate=45, status="draft")
    assert o["rate"] == 45
    o = po(client, h, [L()], currency="EUR", order_date=(TODAY - 5 * DAY).isoformat(), status="draft")
    assert o["rate"] == 40
    # a later table change does not move a fixed document
    s = so(client, h, [L()], currency="USD", status="draft")
    assert s["rate"] == 30
    r = client.post("/api/purchase-orders", headers=h, json={"firm_id": supplier(client, h), "currency": "EURO", "lines": [L()]})
    assert r.status_code == 400


def test_rate_edit_is_refused_after_goods_or_confirmation(client, h, rates):
    o = po(client, h, [L()], currency="EUR")
    ok(receive(client, h, o, 1))
    assert client.put(f"/api/purchase-orders/{o['id']}", headers=h, json={"rate": 41}).status_code == 400
    s = so(client, h, [L()], currency="EUR")
    assert client.put(f"/api/sales-orders/{s['id']}", headers=h, json={"rate": 41}).status_code == 400
    d = so(client, h, [L()], currency="EUR", status="draft")
    assert ok(client.put(f"/api/sales-orders/{d['id']}", headers=h, json={"rate": 41}))["rate"] == 41
    assert ok(client.put(f"/api/sales-orders/{d['id']}", headers=h, json={"rate": None}))["rate"] == 50


def test_project_costs_in_base_with_eur_and_try(client, h, rates):
    p = project(client, h)
    eur = po(client, h, [L(qty=10, price=2)], currency="EUR", rate=40, project_id=p)          # 800 TRY
    tl = po(client, h, [L(qty=10, price=100)], project_id=p)                                   # 1000 TRY
    ok(receive(client, h, eur, 5))                                                              # 400 TRY actual
    ok(receive(client, h, tl, 10))
    c = ok(client.get(f"/api/projects/{p}/costs", headers=h))
    assert c["currency"] == "TRY" and c["committed"] == 1800 and c["actual"] == 1400 and c["unconverted"] == []


def test_project_costs_keeps_unconvertible_money_apart(client, h, rates):
    p = project(client, h)
    o = po(client, h, [L(qty=10, price=2)], currency="XAF", project_id=p)
    assert o["rate"] is None and o["base_total"] is None
    po(client, h, [L(qty=1, price=100)], project_id=p)
    c = ok(client.get(f"/api/projects/{p}/costs", headers=h))
    assert c["committed"] == 100
    assert c["unconverted"] == [{"currency": "XAF", "committed": 20, "actual": 0, "documents": [o["no"]]}]


def test_closed_order_commits_received_value_and_partial_keeps_order_value(client, h, rates):
    p = project(client, h)
    o = po(client, h, [L(qty=10, price=2)], currency="EUR", rate=40, project_id=p)
    ok(receive(client, h, o, 4))
    c = ok(client.get(f"/api/projects/{p}/costs", headers=h))
    assert (c["committed"], c["actual"]) == (800, 320)
    closed = ok(client.post(f"/api/purchase-orders/{o['id']}/close", headers=h, json={"note": "Kalanı gelmeyecek"}))
    assert closed["status"] == "closed"
    c = ok(client.get(f"/api/projects/{p}/costs", headers=h))
    assert (c["committed"], c["actual"]) == (320, 320)


def test_foreign_receipt_books_stock_cost_in_base(client, h, rates):
    code = _u("EUR-MAL")
    i = item(client, h, code, qty=10, cost=100)
    o = po(client, h, [L(qty=10, price=3, code=code)], currency="EUR", rate=50)     # 150 TRY each
    ok(receive(client, h, o, 10))
    s = stock(client, h, i)
    assert s["qty"] == 20 and s["unit_cost"] == 125


def test_receipt_on_foreign_order_with_unknown_rate_is_refused(client, h):
    code = _u("XAF-MAL")
    o = po(client, h, [L(qty=1, price=3, code=code)], currency="XAF")
    r = receive(client, h, o, 1)
    assert r.status_code == 400 and "kur" in r.json()["detail"].lower()


# ---------- receipts ----------
def test_over_receipt_uses_the_setting(client, h):
    o = po(client, h, [L(qty=10)])
    assert receive(client, h, o, 10.5).status_code == 400
    old = ok(client.get("/api/admin/settings", headers=h))["system"]
    assert client.put("/api/admin/settings/system", headers=h, json={"value": {
        **old, "commerce": {**old["commerce"], "over_receipt_pct": 10}}}).status_code == 200
    try:
        assert receive(client, h, o, 11.5).status_code == 400
        got = ok(receive(client, h, o, 11))
        assert got["status"] == "received" and got["lines"][0]["received_qty"] == 11
    finally:
        assert client.put("/api/admin/settings/system", headers=h, json={"value": old}).status_code == 200


def test_reversal_takes_stock_out_at_original_cost_and_reopens(client, h, rates):
    code = _u("GERI")
    i = item(client, h, code, qty=10, cost=100)
    o = po(client, h, [L(qty=10, price=200, code=code)])
    ok(receive(client, h, o, 10))
    assert stock(client, h, i)["unit_cost"] == 150
    back = ok(reverse(client, h, o, 4))
    assert back["status"] == "partial" and back["lines"][0]["received_qty"] == 6
    s = stock(client, h, i)
    assert s["qty"] == 16 and s["unit_cost"] == 137.5       # (10*100 + 6*200) / 16
    assert [r["qty"] for r in back["receipts"]] == [10, -4]
    assert back["receipts"][1]["note"] == "Hatalı parti"
    back = ok(reverse(client, h, o, 6))
    assert back["status"] == "sent" and stock(client, h, i)["unit_cost"] == 100
    assert reverse(client, h, o, 1).status_code == 400


def test_reversal_refused_when_stock_is_gone(client, h):
    code = _u("YOK")
    o = po(client, h, [L(qty=5, code=code)])
    ok(receive(client, h, o, 5))
    i = next(x for x in ok(client.get("/api/stock", headers=h))["rows"] if x["code"] == code)["id"]
    ok(client.post(f"/api/stock/{i}/moves", headers=h, json={"kind": "out", "qty": 4}))
    r = reverse(client, h, o, 2)
    assert r.status_code == 400 and "stokta yeterli" in r.json()["detail"]
    assert ok(client.get(f"/api/purchase-orders/{o['id']}", headers=h))["lines"][0]["received_qty"] == 5   # rolled back
    ok(reverse(client, h, o, 1))


def test_reversal_on_project_order_nets_project_and_stock(client, h):
    p = project(client, h)
    code = _u("PRJ")
    o = po(client, h, [L(qty=5, price=10, code=code)], project_id=p)
    ok(receive(client, h, o, 5))
    ok(reverse(client, h, o, 2))
    c = ok(client.get(f"/api/projects/{p}/costs", headers=h))
    assert (c["committed"], c["actual"]) == (50, 30)
    assert ok(client.get(f"/api/purchase-orders/{o['id']}", headers=h))["status"] == "partial"
    assert reverse(client, h, o, 4).status_code == 400


def test_reversal_of_a_closed_order_stays_closed(client, h):
    o = po(client, h, [L(qty=10, code=_u("KPL"))])
    ok(receive(client, h, o, 6))
    ok(client.post(f"/api/purchase-orders/{o['id']}/close", headers=h, json={}))
    assert ok(reverse(client, h, o, 2))["status"] == "closed"


def test_close_and_cancel_rules(client, h):
    o = po(client, h, [L(qty=10)])
    assert client.post(f"/api/purchase-orders/{o['id']}/close", headers=h, json={}).status_code == 400   # nothing came
    ok(receive(client, h, o, 4))
    r = client.post(f"/api/purchase-orders/{o['id']}/status", headers=h, json={"status": "cancelled"})
    assert r.status_code == 400 and "kapat" in r.json()["detail"].lower()
    ok(client.post(f"/api/purchase-orders/{o['id']}/close", headers=h, json={}))
    assert receive(client, h, o, 1).status_code == 400
    assert client.put(f"/api/purchase-orders/{o['id']}", headers=h, json={"note": "x"}).status_code == 400


# ---------- partial invoices ----------
def test_po_partial_invoices_add_up_and_cancelled_frees(client, h):
    o = po(client, h, [L("A", 10, 100), L("B", 4, 50)])
    assert ok(client.get(f"/api/purchase-orders/{o['id']}", headers=h))["lines"][0]["to_bill"] == 10   # advance
    ok(receive(client, h, o, 6, 4))
    d = ok(client.get(f"/api/purchase-orders/{o['id']}", headers=h))
    assert [(l["to_bill"], l["billable"]) for l in d["lines"]] == [(6, 10), (4, 4)]
    first = ok(po_invoice(client, h, o), 201)       # default: what came
    assert first["subtotal"] == 800 and [l["source_line_id"] for l in first["lines"]] == [l["id"] for l in o["lines"]]
    assert po_invoice(client, h, o).status_code == 400   # nothing received and unbilled
    ok(receive(client, h, o, 4))
    second = ok(po_invoice(client, h, o, [3, 0]), 201)
    third = ok(po_invoice(client, h, o, [1, 0]), 201)
    assert first["subtotal"] + second["subtotal"] + third["subtotal"] == 1200 == sum(l["qty"] * l["unit_price"] for l in o["lines"])
    r = po_invoice(client, h, o, [1, 0])
    assert r.status_code == 400 and "faturalan" in r.json()["detail"]
    ok(client.post(f"/api/invoices/{third['id']}/status", headers=h, json={"status": "cancelled"}))
    assert ok(client.get(f"/api/purchase-orders/{o['id']}", headers=h))["lines"][0]["billed_qty"] == 9
    ok(po_invoice(client, h, o, [1, 0]), 201)


def test_closed_po_bills_only_what_came(client, h):
    o = po(client, h, [L("A", 10, 100)])
    ok(receive(client, h, o, 4))
    ok(client.post(f"/api/purchase-orders/{o['id']}/close", headers=h, json={}))
    assert po_invoice(client, h, o, [5]).status_code == 400
    assert ok(po_invoice(client, h, o, [4]), 201)["subtotal"] == 400


def test_old_invoices_without_source_line_still_count(client, h):
    o = po(client, h, [L("A", 3, 100), L("A", 3, 100), L("B", 2, 10)])
    ok(receive(client, h, o, 3, 3, 2))
    inv = ok(po_invoice(client, h, o, [3, 1, 0]), 201)
    from app.db import SessionLocal
    from app.models import InvoiceLine
    with SessionLocal() as db:      # what an invoice from before this version looks like
        for l in db.query(InvoiceLine).filter(InvoiceLine.invoice_id == inv["id"]):
            l.source_line_id = None
        db.commit()
    d = ok(client.get(f"/api/purchase-orders/{o['id']}", headers=h))
    assert [l["billed_qty"] for l in d["lines"]] == [3, 1, 0]
    assert po_invoice(client, h, o, [1, 3, 0]).status_code == 400
    ok(po_invoice(client, h, o, [0, 2, 2]), 201)


def test_invoice_line_of_another_order_is_refused(client, h):
    a, b = po(client, h, [L()]), po(client, h, [L()])
    r = client.post(f"/api/purchase-orders/{a['id']}/invoice", headers=h, json={
        "no": _u("AF"), "lines": [{"line_id": b["lines"][0]["id"], "qty": 1}]})
    assert r.status_code == 400


def test_draft_edit_cannot_pass_the_order(client, h):
    s = so(client, h, [L("A", 10, 100)])
    ok(deliver(client, h, s, 4))
    inv = ok(so_invoice(client, h, s), 201)
    row = {k: inv["lines"][0][k] for k in ("code", "description", "unit", "unit_price", "source_line_id")}
    r = client.put(f"/api/invoices/{inv['id']}", headers=h, json={"lines": [{**row, "qty": 11}]})
    assert r.status_code == 400
    ok(client.put(f"/api/invoices/{inv['id']}", headers=h, json={"lines": [{**row, "qty": 10}]}))
    assert ok(client.get(f"/api/sales-orders/{s['id']}", headers=h))["lines"][0]["billable"] == 0


def test_sales_partial_invoices_keep_discount_and_add_up(client, h):
    s = so(client, h, [L("A", 3, 100), L("B", 1, 50)], discount_pct=10, tax_rate=0)
    ok(deliver(client, h, s, 1, 1))
    a = ok(so_invoice(client, h, s), 201)
    assert a["subtotal"] == 135
    ok(deliver(client, h, s, 2, 0))
    b = ok(so_invoice(client, h, s), 201)
    assert a["subtotal"] + b["subtotal"] == s["total"] == 315
    assert so_invoice(client, h, s).status_code == 400


def test_unpriced_line_blocks_only_when_chosen(client, h):
    s = so(client, h, [L("A", 1, 100), {"description": "Fiyatsız", "qty": 1}])
    ok(so_invoice(client, h, s, [1, 0]), 201)
    assert so_invoice(client, h, s, [0, 1]).status_code == 400


# ---------- deliveries ----------
def test_deliver_takes_stock_and_return_brings_it_back(client, h):
    code = _u("SEVK")
    i = item(client, h, code, qty=10, cost=80)
    s = so(client, h, [L("A", 6, 100, code=code), L("Hizmet", 2, 50)])
    d = ok(deliver(client, h, s, 2, 0))
    assert d["status"] == "partial" and d["lines"][0]["remaining"] == 4
    assert stock(client, h, i)["qty"] == 8
    assert deliver(client, h, s, 5, 0).status_code == 400
    d = ok(deliver(client, h, s, 4, 2))
    assert d["status"] == "delivered" and stock(client, h, i)["qty"] == 4
    d = ok(deliver(client, h, s, 1, 0, path="return"))
    assert d["status"] == "partial" and stock(client, h, i)["qty"] == 5
    assert stock(client, h, i)["unit_cost"] == 80
    assert [x["qty"] for x in d["deliveries"][:3]] == [2, 4, 2]
    assert deliver(client, h, s, -9, 0).status_code == 400          # more than went out
    ok(deliver(client, h, s, -5, -2))
    assert ok(client.get(f"/api/sales-orders/{s['id']}", headers=h))["status"] == "confirmed"
    assert stock(client, h, i)["qty"] == 10


def test_delivery_needs_stock_and_a_confirmed_order(client, h):
    code = _u("AZ")
    item(client, h, code, qty=1, cost=1)
    s = so(client, h, [L("A", 5, 10, code=code)])
    r = deliver(client, h, s, 2)
    assert r.status_code == 400 and "stokta yeterli" in r.json()["detail"]
    draft = so(client, h, [L("A", 5, 10)], status="draft")
    assert deliver(client, h, draft, 1).status_code == 400
    assert deliver(client, h, draft, -1).status_code == 400


def test_code_without_stock_card_ships_without_stock(client, h):
    s = so(client, h, [L("A", 5, 10, code=_u("KARTSIZ"))])
    assert ok(deliver(client, h, s, 5))["status"] == "delivered"


def test_status_delivered_ships_the_rest_through_stock(client, h):
    code = _u("TUM")
    i = item(client, h, code, qty=10, cost=5)
    s = so(client, h, [L("A", 6, 10, code=code)])
    ok(deliver(client, h, s, 2))
    ok(client.post(f"/api/sales-orders/{s['id']}/status", headers=h, json={"status": "delivered"}))
    d = ok(client.get(f"/api/sales-orders/{s['id']}", headers=h))
    assert d["status"] == "delivered" and d["lines"][0]["delivered_qty"] == 6 and stock(client, h, i)["qty"] == 4


def test_project_goods_leave_stock_once(client, h):
    """Bought for the project, the goods already left stock; shipping them takes nothing more."""
    p = project(client, h)
    code = _u("PRJSEVK")
    i = item(client, h, code, qty=3, cost=10)
    o = po(client, h, [L(qty=2, price=10, code=code)], project_id=p)
    ok(receive(client, h, o, 2))
    assert stock(client, h, i)["qty"] == 3
    s = so(client, h, [L("A", 3, 100, code=code)], project_id=p)
    ok(deliver(client, h, s, 2))
    assert stock(client, h, i)["qty"] == 3
    ok(deliver(client, h, s, 1))            # the third comes from free stock and costs the project
    assert stock(client, h, i)["qty"] == 2
    c = ok(client.get(f"/api/projects/{p}/costs", headers=h))
    assert c["actual"] == 30
    ok(deliver(client, h, s, 1, path="return"))
    assert stock(client, h, i)["qty"] == 3 and ok(client.get(f"/api/projects/{p}/costs", headers=h))["actual"] == 20


def test_partial_order_cannot_be_cancelled_or_repriced(client, h):
    s = so(client, h, [L("A", 6, 10)])
    ok(deliver(client, h, s, 2))
    assert client.post(f"/api/sales-orders/{s['id']}/status", headers=h, json={"status": "cancelled"}).status_code == 400
    assert client.put(f"/api/sales-orders/{s['id']}", headers=h, json={"lines": [L("A", 1, 1)]}).status_code == 400


# ---------- current account ----------
def balance(client, h, firm):
    rows = ok(client.get("/api/balances", headers=h))
    rows = rows["rows"] if isinstance(rows, dict) else rows
    return [r for r in rows if r["firm_id"] == firm]


def test_cari_shows_each_currency_and_a_base_total(client, h, rates):
    firm = customer(client, h)
    eur = so(client, h, [L("A", 1, 100)], firm=firm, currency="EUR", rate=45, tax_rate=0)
    tl = so(client, h, [L("A", 1, 1000)], firm=firm, tax_rate=0)
    a = ok(so_invoice(client, h, eur), 201)
    assert a["rate"] == 50      # the table's rate of the invoice day; the form can override
    b = ok(so_invoice(client, h, tl), 201)
    for inv in (a, b):
        ok(client.post(f"/api/invoices/{inv['id']}/status", headers=h, json={"status": "issued"}))
    rows = {r["currency"]: r for r in balance(client, h, firm)}
    assert rows["EUR"]["receivable"] == 100 and rows["EUR"]["base_receivable"] == 5000
    assert rows["TRY"]["receivable"] == 1000 and rows["TRY"]["base_receivable"] == 1000
    led = ok(client.get(f"/api/firms/{firm}/ledger", headers=h))
    assert led["balance"] == {"EUR": 100, "TRY": 1000} and led["base_balance"] == 6000 and led["unconverted"] == []
    assert sorted(r["base_amount"] for r in led["rows"]) == [1000, 5000]


def test_payment_on_foreign_invoice_settles_in_its_currency(client, h, rates):
    firm = customer(client, h)
    s = so(client, h, [L("A", 1, 100)], firm=firm, currency="EUR", tax_rate=0)
    inv = ok(so_invoice(client, h, s, rate=40), 201)
    assert inv["rate"] == 40
    ok(client.post(f"/api/invoices/{inv['id']}/status", headers=h, json={"status": "issued"}))
    body = {"direction": "in", "invoice_id": inv["id"], "amount": 100}
    assert client.post("/api/payments", headers=h, json={**body, "currency": "TRY"}).status_code == 400
    p = ok(client.post("/api/payments", headers=h, json=body), 201)
    assert p["currency"] == "EUR" and p["rate"] == 50 and p["base_amount"] == 5000
    got = ok(client.get(f"/api/invoices/{inv['id']}", headers=h))
    assert got["remaining"] == 0 and got["base_remaining"] == 0
    rows = balance(client, h, firm)
    assert all(r["base_balance"] in (0, None) for r in rows)    # a settled account is zero whatever the rate did


def test_unknown_rate_stays_out_of_the_base_total(client, h):
    firm = customer(client, h)
    s = so(client, h, [L("A", 1, 100)], firm=firm, currency="XAF", tax_rate=0)
    inv = ok(so_invoice(client, h, s), 201)
    assert inv["rate"] is None and inv["base_total"] is None
    ok(client.post(f"/api/invoices/{inv['id']}/status", headers=h, json={"status": "issued"}))   # never blocks
    assert balance(client, h, firm)[0]["base_balance"] is None
    led = ok(client.get(f"/api/firms/{firm}/ledger", headers=h))
    assert led["unconverted"] == ["XAF"] and led["base_balance"] == 0


# ---------- suppliers ----------
def backdate(po_id, day):
    from app.db import SessionLocal
    from app.models import PurchaseReceipt
    from datetime import datetime, time
    with SessionLocal() as db:
        for r in db.query(PurchaseReceipt).filter(PurchaseReceipt.po_id == po_id):
            r.received_at = datetime.combine(day, time(12))
        db.commit()


def perf(client, h, firm):
    return next(r for r in ok(client.get("/api/suppliers/performance", headers=h))["rows"] if r["firm_id"] == firm)


def test_supplier_performance(client, h, rates):
    f = supplier(client, h)
    due = (TODAY - 10 * DAY).isoformat()
    on_time = po(client, h, [L(qty=10, price=2)], firm=f, currency="EUR", rate=40, due_date=due)
    ok(receive(client, h, on_time, 10))
    backdate(on_time["id"], TODAY - 11 * DAY)
    late = po(client, h, [L(qty=10, price=10)], firm=f, due_date=due)
    ok(receive(client, h, late, 10))
    backdate(late["id"], TODAY - 6 * DAY)
    ok(reverse(client, h, late, 2))         # returned at today's date; 8 stay
    no_due = po(client, h, [L(qty=1, price=10)], firm=f)
    ok(receive(client, h, no_due, 1))
    po(client, h, [L(qty=1, price=10)], firm=f)                        # nothing received, left out
    po(client, h, [L(qty=1, price=10)], firm=f, status="draft")        # not counted at all
    r = perf(client, h, f)
    assert (r["orders"], r["measured"], r["left_out"], r["on_time"]) == (4, 2, 2, 1)
    assert r["avg_delay_days"] == 5             # the reversal reopened `late`, open past due: 10 days so far
    assert r["spend"] == 800 + 80 + 10 and r["return_pct"] == 9.5


def test_supplier_late_and_early_average(client, h):
    f = supplier(client, h)
    due = (TODAY - 10 * DAY).isoformat()
    a = po(client, h, [L(qty=10, price=2)], firm=f, due_date=due)
    ok(receive(client, h, a, 10))
    backdate(a["id"], TODAY - 12 * DAY)
    b = po(client, h, [L(qty=10, price=3)], firm=f, due_date=due)
    ok(receive(client, h, b, 10))
    backdate(b["id"], TODAY - 6 * DAY)
    c = po(client, h, [L(qty=10, price=5)], firm=f, due_date=due)        # part came, past due, still open: late so far
    ok(receive(client, h, c, 5))
    r = perf(client, h, f)
    assert (r["orders"], r["measured"], r["on_time"], r["on_time_pct"]) == (3, 3, 1, 33.3)
    assert r["avg_delay_days"] == pytest.approx((0 + 4 + 10) / 3, abs=0.05)
    assert r["spend"] == 75


def test_completing_receipt_is_the_last_one_after_a_reversal(client, h):
    f = supplier(client, h)
    o = po(client, h, [L(qty=4, price=10, code=_u("TAM"))], firm=f, due_date=(TODAY - DAY).isoformat())
    ok(receive(client, h, o, 4))
    backdate(o["id"], TODAY - 3 * DAY)
    ok(reverse(client, h, o, 1))
    ok(receive(client, h, o, 1))
    r = perf(client, h, f)
    assert (r["on_time"], r["avg_delay_days"]) == (0, 1)
    assert r["return_pct"] == 20       # 1 back of 5 received


def test_supplier_spend_keeps_unknown_rate_apart(client, h):
    f = supplier(client, h)
    o = po(client, h, [L(qty=2, price=10)], firm=f, currency="USD", rate=30)
    ok(receive(client, h, o, 2))
    x = po(client, h, [L(qty=1, price=7)], firm=f, currency="ZMW")
    from app.db import SessionLocal
    from app.models import PurchaseOrderLine
    with SessionLocal() as db:
        db.get(PurchaseOrderLine, x["lines"][0]["id"]).received_qty = 1
        db.commit()
    r = perf(client, h, f)
    assert r["spend"] == 600 and r["unconverted"] == [{"currency": "ZMW", "amount": 7}]


def test_price_history_per_firm_in_base(client, h, rates):
    code = _u("FIYAT")
    f1, f2 = supplier(client, h), supplier(client, h)
    old = (TODAY - 20 * DAY).isoformat()
    po(client, h, [L(qty=1, price=2, code=code)], firm=f1, currency="EUR", rate=40, order_date=old)   # 80
    po(client, h, [L(qty=1, price=100, code=code)], firm=f1, order_date=TODAY.isoformat())
    po(client, h, [L(qty=1, price=90, code=code)], firm=f2, order_date=TODAY.isoformat())
    po(client, h, [L(qty=1, price=1, code=code)], firm=f2, status="draft")
    out = ok(client.get("/api/suppliers/price-history", headers=h, params={"code": code}))
    assert out["base"] == "TRY" and [x["firm_id"] for x in out["firms"]] == [f2, f1]
    a = out["firms"][1]
    assert (a["last_price"], a["lowest_price"], a["orders"]) == (100, 80, 2)
    assert [p["base_price"] for p in a["points"]] == [80, 100]
    near = ok(client.get("/api/suppliers/price-history", headers=h, params={"code": code[:-2]}))
    assert near["firms"] == [] and near["suggestions"] == [code]
    assert client.get("/api/suppliers/price-history", headers=h, params={"code": " "}).status_code == 400


# ---------- permissions ----------
def test_permissions(client, h):
    uid, x = _user(client, h, _u("gizli"))
    ok(client.put(f"/api/admin/users/{uid}", headers=h, json={"permissions": {"purchasing": "none", "sales": "view", "finance": "none"}}))
    assert client.get("/api/suppliers/performance", headers=x).status_code == 403
    assert client.get("/api/suppliers/price-history", headers=x, params={"code": "A"}).status_code == 403
    o = po(client, h, [L()])
    s = so(client, h, [L()])
    for path in ("receive", "reverse", "close"):
        assert client.post(f"/api/purchase-orders/{o['id']}/{path}", headers=x, json={"lines": []}).status_code == 403
    for path in ("deliver", "return"):
        assert client.post(f"/api/sales-orders/{s['id']}/{path}", headers=x, json={"lines": []}).status_code == 403
    assert client.post(f"/api/sales-orders/{s['id']}/invoice", headers=x, json={}).status_code == 403
    assert client.post(f"/api/purchase-orders/{o['id']}/invoice", headers=x, json={"no": "X"}).status_code == 403
