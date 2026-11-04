"""Barcode resolve, reorder suggestions, work order materials and route."""
from __future__ import annotations

import uuid

import pytest

from test_api_commerce import _login


def _code(p="M"):
    return f"{p}-{uuid.uuid4().hex[:8].upper()}"


def _item(client, h, qty=0, cost=None, **kw):
    code = kw.pop("code", None) or _code()
    r = client.post("/api/stock", headers=h, json={"code": code, "name": "Malzeme", "qty": qty, "unit_cost": cost, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _firm(client, h, name=None):
    r = client.post("/api/admin/firms", headers=h, json={"name": name or f"Firma {uuid.uuid4().hex[:6]}", "kind": "supplier"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _project(client, h):
    return client.post("/api/projects", json={"name": f"Stok {uuid.uuid4().hex[:8]}"}, headers=h).json()["id"]


def _wo(client, h, qty=10, project_id=None, unit_cost=None, part_no=None):
    r = client.post("/api/work-orders", headers=h, json={"part_no": part_no or _code("P"), "qty": qty,
                                                         "project_id": project_id, "unit_cost": unit_cost})
    assert r.status_code == 201, r.text
    return r.json()


def _materials(client, h, wo_id, *rows):
    r = client.put(f"/api/work-orders/{wo_id}/materials", headers=h, json={"rows": list(rows)})
    assert r.status_code == 200, r.text
    return r.json()


def _po(client, h, code, qty=10, price=None, firm_id=None, project_id=None, status="sent", currency=""):
    r = client.post("/api/purchase-orders", headers=h, json={
        "firm_id": firm_id, "project_id": project_id, "currency": currency,
        "lines": [{"code": code, "description": "x", "qty": qty, "unit_price": price}]})
    assert r.status_code == 201, r.text
    po = r.json()
    if status != "draft":
        assert client.post(f"/api/purchase-orders/{po['id']}/status", headers=h, json={"status": status}).status_code == 200
    return po


def _qty(client, h, item_id):
    return next(r["qty"] for r in client.get("/api/stock", headers=h).json()["rows"] if r["id"] == item_id)


def _stock_cost(client, h, code):
    return next(r["unit_cost"] for r in client.get("/api/stock", headers=h).json()["rows"] if r["code"] == code)


def _costs(client, h, pid):
    r = client.get(f"/api/projects/{pid}/costs", headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    return d, {s["name"]: s for s in d["by_source"]}


def _resolve(client, h, payload):
    return client.post("/api/scan/resolve", headers=h, json={"payload": payload})


# ---------- scan ----------
def test_scan_resolves_every_payload_kind(client, admin_headers):
    h = admin_headers
    i = _item(client, h, qty=4)
    for payload in (f"STK:{i['code']}", i["code"], f"stk:{i['code']}", f"  {i['code']}\r\n"):
        r = _resolve(client, h, payload)
        assert r.status_code == 200, payload
        assert (r.json()["type"], r.json()["id"]) == ("stock", i["id"])
        assert r.json()["actions"] == ["in", "out", "count"]
    w = _wo(client, h)
    d = _resolve(client, h, f"WO:{w['no']}").json()
    assert (d["type"], d["id"], d["actions"]) == ("wo", w["id"], ["start", "complete"])
    po = _po(client, h, i["code"], qty=5, price=99.5)
    d = _resolve(client, h, f"PO:{po['no']}").json()
    assert (d["type"], d["id"], d["actions"]) == ("po", po["id"], ["receive"])
    assert d["detail"]["lines"][0]["remaining"] == 5
    assert "99.5" not in str(d)


def test_scan_unknown_and_empty(client, admin_headers):
    assert _resolve(client, admin_headers, "STK:YOK-BOYLE-KOD").status_code == 404
    assert _resolve(client, admin_headers, "WO:YOK").status_code == 404
    assert _resolve(client, admin_headers, "   ").status_code == 400


def test_scan_reads_a_us_scanner_on_a_turkish_keyboard(client, admin_headers):
    i = _item(client, admin_headers, code=f"AB-{uuid.uuid4().hex[:6].upper()}")
    mangled = "STKŞ" + i["code"].replace("-", "*")
    assert _resolve(client, admin_headers, mangled).json()["id"] == i["id"]


def test_scan_actions_follow_permissions(client, admin_headers):
    h = admin_headers
    i = _item(client, h, qty=4)
    w = _wo(client, h)
    _materials(client, h, w["id"], {"code": i["code"], "planned_qty": 1})
    po = _po(client, h, i["code"])

    viewer, _ = _login(client, h, "viewer", permissions={"stock": "view", "workorders": "view", "purchasing": "view"})
    assert _resolve(client, viewer, i["code"]).json()["actions"] == []
    assert _resolve(client, viewer, f"WO:{w['no']}").json()["actions"] == []
    assert _resolve(client, viewer, f"PO:{po['no']}").json()["actions"] == []

    planner, _ = _login(client, h, "planner")
    assert _resolve(client, planner, f"WO:{w['no']}").json()["actions"] == ["start", "complete", "issue"]

    # A right in one module opens the scanner but no other module's records, existing or not
    buyer, _ = _login(client, h, "viewer", permissions={"purchasing": "view", "stock": "none", "workorders": "none"})
    assert _resolve(client, buyer, f"PO:{po['no']}").status_code == 200
    assert _resolve(client, buyer, f"WO:{w['no']}").status_code == 403
    assert _resolve(client, buyer, "WO:YOK").status_code == 403
    assert _resolve(client, buyer, i["code"]).status_code == 403

    nobody, _ = _login(client, h, "viewer", permissions={"stock": "none", "purchasing": "none", "workorders": "none"})
    assert _resolve(client, nobody, i["code"]).status_code == 403


def test_scan_offers_only_what_the_status_allows(client, admin_headers):
    h = admin_headers
    i = _item(client, h)
    draft = _po(client, h, i["code"], status="draft")
    assert _resolve(client, h, f"PO:{draft['no']}").json()["actions"] == []
    w = _wo(client, h, qty=1)
    assert client.post(f"/api/work-orders/{w['id']}/complete", headers=h, json={"qty": 1}).status_code == 200
    d = _resolve(client, h, f"WO:{w['no']}").json()
    assert d["actions"] == [] and d["detail"]["status"] == "done"


def test_scan_does_not_wake_every_open_screen(client, admin_headers):
    """It is a read: a bump here would refetch the card, which would bump again."""
    i = _item(client, admin_headers)
    rev = client.get("/api/sync").json()["rev"]
    assert _resolve(client, admin_headers, i["code"]).status_code == 200
    assert client.get("/api/sync").json()["rev"] == rev


# ---------- reorder ----------
def _suggest(client, h):
    r = client.get("/api/stock/reorder", headers=h)
    assert r.status_code == 200, r.text
    return {x["code"]: x for x in r.json()["rows"]}


def test_reorder_quantity_and_open_orders(client, admin_headers):
    h = admin_headers
    a = _item(client, h, qty=2, min_qty=10)
    b = _item(client, h, qty=2, min_qty=10, reorder_qty=25)
    c = _item(client, h, qty=10, min_qty=10)                  # at the minimum is not below it
    d = _item(client, h, qty=0)                               # no minimum set
    rows = _suggest(client, h)
    assert rows[a["code"]]["suggested_qty"] == 8
    assert rows[b["code"]]["suggested_qty"] == 25
    assert c["code"] not in rows and d["code"] not in rows

    # Draft and sent count; a partly received line counts for what remains
    e = _item(client, h, qty=2, min_qty=10)
    _po(client, h, e["code"], qty=3, status="draft")
    po = _po(client, h, e["code"], qty=4)
    r = client.post(f"/api/purchase-orders/{po['id']}/receive", headers=h,
                    json={"lines": [{"line_id": po["lines"][0]["id"] if "lines" in po else 0, "qty": 1}]})
    assert r.status_code == 200, r.text
    row = _suggest(client, h)[e["code"]]
    assert (row["qty"], row["on_order"], row["available"], row["suggested_qty"]) == (3, 6, 9, 1)

    # Cancelled and fully covered orders
    f = _item(client, h, qty=2, min_qty=10)
    _po(client, h, f["code"], qty=20, status="cancelled")
    assert _suggest(client, h)[f["code"]]["on_order"] == 0
    _po(client, h, f["code"], qty=8, status="draft")
    assert f["code"] not in _suggest(client, h)


def test_reorder_ignores_project_orders(client, admin_headers):
    """Their goods are issued to the project on receipt and never reach free stock."""
    h = admin_headers
    a = _item(client, h, qty=2, min_qty=10)
    _po(client, h, a["code"], qty=50, project_id=_project(client, h))
    assert _suggest(client, h)[a["code"]]["on_order"] == 0


def test_reorder_firm_and_price_sources(client, admin_headers):
    h = admin_headers
    old, last, preferred = _firm(client, h), _firm(client, h), _firm(client, h)
    a = _item(client, h, qty=0, min_qty=5)
    _po(client, h, a["code"], qty=1, price=10, firm_id=old, status="cancelled")
    assert _suggest(client, h)[a["code"]]["firm_id"] is None      # a cancelled order is no history
    _po(client, h, a["code"], qty=1, price=20, firm_id=old)
    _po(client, h, a["code"], qty=1, price=None, firm_id=last)    # newest firm, but the price comes from the order before
    row = _suggest(client, h)[a["code"]]
    assert (row["firm_id"], row["firm_source"], row["last_price"]) == (last, "last_order", 20)

    assert client.put(f"/api/stock/{a['id']}", headers=h, json={"preferred_firm_id": preferred}).status_code == 200
    row = _suggest(client, h)[a["code"]]
    assert (row["firm_id"], row["firm_source"], row["firm_missing"]) == (preferred, "preferred", False)


def test_reorder_survives_a_deleted_preferred_firm(client, admin_headers):
    h = admin_headers
    gone = _firm(client, h)
    a = _item(client, h, qty=0, min_qty=5, preferred_firm_id=gone)
    assert client.delete(f"/api/admin/firms/{gone}", headers=h).status_code == 200
    row = _suggest(client, h)[a["code"]]
    assert (row["firm_id"], row["firm_missing"]) == (None, True)
    # The card still saves, and the dead firm can be cleared
    assert client.put(f"/api/stock/{a['id']}", headers=h, json={"note": "x"}).status_code == 200
    assert client.put(f"/api/stock/{a['id']}", headers=h, json={"preferred_firm_id": None}).json()["preferred_firm_id"] is None
    assert client.put(f"/api/stock/{a['id']}", headers=h, json={"preferred_firm_id": gone}).status_code == 400
    assert client.post("/api/stock", headers=h, json={"code": _code(), "preferred_firm_id": gone}).status_code == 400


def test_reorder_creates_one_draft_per_firm(client, admin_headers):
    h = admin_headers
    f1, f2 = _firm(client, h), _firm(client, h)
    a, b, c = (_item(client, h, min_qty=5, unit="Kg") for _ in range(3))
    _po(client, h, a["code"], qty=1, price=12.5, firm_id=f1, status="draft")
    r = client.post("/api/stock/reorder/orders", headers=h, json={"items": [
        {"item_id": a["id"], "qty": 7, "firm_id": f1}, {"item_id": b["id"], "qty": 3, "firm_id": f2},
        {"item_id": c["id"], "qty": 2, "firm_id": f1}]})
    assert r.status_code == 201, r.text
    orders = r.json()["orders"]
    assert sorted(o["line_count"] for o in orders) == [1, 2]
    assert len({o["no"] for o in orders}) == 2
    one = next(o for o in orders if o["line_count"] == 2)
    po = client.get(f"/api/purchase-orders/{one['id']}", headers=h).json()
    assert (po["status"], po["firm_id"], po["project_id"]) == ("draft", f1, None)
    assert [(l["code"], l["qty"], l["unit"], l["unit_price"]) for l in po["lines"]] == [
        (a["code"], 7, "Kg", 12.5), (c["code"], 2, "Kg", None)]
    assert a["code"] not in _suggest(client, h)      # the draft now covers it


def test_reorder_error_on_one_item_creates_nothing(client, admin_headers):
    h = admin_headers
    f = _firm(client, h)
    a, b = _item(client, h, min_qty=5), _item(client, h, min_qty=5)
    before = len(client.get("/api/purchase-orders", headers=h).json()["rows"])
    r = client.post("/api/stock/reorder/orders", headers=h, json={"items": [
        {"item_id": a["id"], "qty": 1, "firm_id": f}, {"item_id": b["id"], "qty": 1, "firm_id": None}]})
    assert r.status_code == 400
    assert r.json()["detail"]["errors"] == [{"item_id": b["id"], "code": b["code"], "error": "Firma seçilmemiş"}]
    assert len(client.get("/api/purchase-orders", headers=h).json()["rows"]) == before

    def bad(rows):
        return client.post("/api/stock/reorder/orders", headers=h, json={"items": rows})
    assert bad([{"item_id": 99999999, "qty": 1, "firm_id": f}]).status_code == 400
    assert bad([{"item_id": a["id"], "qty": 1, "firm_id": 99999999}]).status_code == 400
    assert bad([{"item_id": a["id"], "qty": 1, "firm_id": f}, {"item_id": a["id"], "qty": 1, "firm_id": f}]).status_code == 400
    assert bad([{"item_id": a["id"], "qty": 0, "firm_id": f}]).status_code == 422
    assert bad([]).status_code == 422


def test_reorder_price_in_another_currency_is_not_copied(client, admin_headers):
    h = admin_headers
    f = _firm(client, h)
    a = _item(client, h, min_qty=5)
    _po(client, h, a["code"], qty=1, price=3, firm_id=f, currency="XYZ", status="draft")
    b = client.post("/api/stock/reorder/orders", headers=h, json={"items": [{"item_id": a["id"], "qty": 1, "firm_id": f}]})
    po = client.get(f"/api/purchase-orders/{b.json()['orders'][0]['id']}", headers=h).json()
    assert po["lines"][0]["unit_price"] is None


def test_reorder_permissions(client, admin_headers):
    h = admin_headers
    f = _firm(client, h)
    a = _item(client, h, min_qty=5)
    body = {"items": [{"item_id": a["id"], "qty": 1, "firm_id": f}]}
    stock_only, _ = _login(client, h, "viewer", permissions={"stock": "edit", "purchasing": "none"})
    buy_only, _ = _login(client, h, "viewer", permissions={"stock": "none", "purchasing": "edit"})
    both_view, _ = _login(client, h, "viewer", permissions={"stock": "view", "purchasing": "view"})
    assert client.get("/api/stock/reorder", headers=stock_only).status_code == 403
    assert client.get("/api/stock/reorder", headers=buy_only).status_code == 403
    assert client.get("/api/stock/reorder", headers=both_view).status_code == 200
    assert client.post("/api/stock/reorder/orders", headers=both_view, json=body).status_code == 403
    assert client.post("/api/stock/reorder/orders", headers=stock_only, json=body).status_code == 403
    assert client.post("/api/stock/reorder/orders", headers=buy_only, json=body).status_code == 201


# ---------- materials ----------
def test_issue_and_return_move_stock(client, admin_headers):
    h = admin_headers
    i = _item(client, h, qty=10, cost=5)
    w = _wo(client, h)
    m = _materials(client, h, w["id"], {"code": i["code"], "planned_qty": 6})[0]
    assert (m["description"], m["unit"], m["stock_qty"], m["remaining"]) == ("Malzeme", "Adet", 10, 6)
    url = f"/api/work-orders/{w['id']}/materials/{m['id']}"
    r = client.post(f"{url}/issue", headers=h, json={"qty": 4})
    assert r.status_code == 200 and r.json()[0]["issued_qty"] == 4
    assert _qty(client, h, i["id"]) == 6
    assert client.post(f"{url}/return", headers=h, json={"qty": 5}).status_code == 400
    assert client.post(f"{url}/return", headers=h, json={"qty": 1}).json()[0]["issued_qty"] == 3
    assert _qty(client, h, i["id"]) == 7
    assert client.post(f"{url}/issue", headers=h, json={"qty": 0}).status_code == 422
    assert client.post(f"{url}/issue", headers=h, json={"qty": -1}).status_code == 422
    assert client.post(f"{url}/issue", headers=h, json={"qty": 100}).status_code == 400
    assert _qty(client, h, i["id"]) == 7


def test_material_list_rules(client, admin_headers):
    h = admin_headers
    i, j = _item(client, h, qty=10), _item(client, h, qty=10)
    w = _wo(client, h)

    def put(*rows):
        return client.put(f"/api/work-orders/{w['id']}/materials", headers=h, json={"rows": list(rows)})

    assert put({"code": w["part_no"], "planned_qty": 1}).status_code == 400
    assert put({"code": i["code"], "planned_qty": 1}, {"code": i["code"], "planned_qty": 1}).status_code == 400
    assert put({"code": i["code"], "planned_qty": 0}).status_code == 422
    m = put({"code": i["code"], "planned_qty": 5}).json()[0]
    assert client.post(f"/api/work-orders/{w['id']}/materials/{m['id']}/issue", headers=h, json={"qty": 3}).status_code == 200
    assert put({"id": m["id"], "code": i["code"], "planned_qty": 2}).status_code == 400
    assert put({"id": m["id"], "code": j["code"], "planned_qty": 5}).status_code == 400
    assert put().status_code == 400
    assert put({"id": 99999999, "code": j["code"], "planned_qty": 5}).status_code == 400
    assert put({"id": m["id"], "code": i["code"], "planned_qty": 8}, {"code": j["code"], "planned_qty": 1}).status_code == 200

    # A material row of another order cannot be reached through this one
    other = _wo(client, h)
    assert client.post(f"/api/work-orders/{other['id']}/materials/{m['id']}/issue", headers=h, json={"qty": 1}).status_code == 404


def test_material_without_stock_card(client, admin_headers):
    h = admin_headers
    w = _wo(client, h, qty=1)
    code = _code()
    m = _materials(client, h, w["id"], {"code": code, "planned_qty": 2})[0]
    assert m["has_card"] is False
    assert client.post(f"/api/work-orders/{w['id']}/materials/{m['id']}/issue", headers=h, json={"qty": 1}).status_code == 400
    r = client.post(f"/api/work-orders/{w['id']}/complete", headers=h, json={"qty": 1})
    assert r.status_code == 200
    assert [x["code"] for x in r.json()["warnings"]] == [code]


def test_material_cost_counts_once_on_a_project(client, admin_headers):
    h = admin_headers
    pid = _project(client, h)
    i = _item(client, h, qty=20, cost=10)
    w = _wo(client, h, qty=5, project_id=pid, unit_cost=20)
    m = _materials(client, h, w["id"], {"code": i["code"], "planned_qty": 5})[0]
    url = f"/api/work-orders/{w['id']}/materials/{m['id']}"
    assert client.post(f"{url}/issue", headers=h, json={"qty": 2}).status_code == 200
    d, src = _costs(client, h, pid)
    assert src["Stoktan"]["actual"] == 20 and d["actual"] == 20
    assert client.post(f"/api/work-orders/{w['id']}/complete", headers=h, json={"qty": 5}).status_code == 200
    d, src = _costs(client, h, pid)
    # 5 x 10 of material once, 5 x 20 of conversion once, and nothing for the finished part's own moves
    assert src["Stoktan"]["actual"] == 50
    assert src["İç üretim"]["actual"] == 100
    assert d["actual"] == 150 and d["committed"] == 150
    moves = client.get(f"/api/stock/{i['id']}/moves", headers=h).json()
    assert all(x["project_id"] == pid and w["no"] in x["note"] for x in moves if x["kind"] == "issue")


def test_returned_material_leaves_no_cost(client, admin_headers):
    h = admin_headers
    pid = _project(client, h)
    i = _item(client, h, qty=10, cost=10)
    w = _wo(client, h, qty=5, project_id=pid)
    m = _materials(client, h, w["id"], {"code": i["code"], "planned_qty": 5})[0]
    url = f"/api/work-orders/{w['id']}/materials/{m['id']}"
    assert client.post(f"{url}/issue", headers=h, json={"qty": 4}).status_code == 200
    # The stock's average moves on after the issue; the return still goes back at the cost it left at
    assert client.post(f"/api/stock/{i['id']}/moves", headers=h, json={"kind": "in", "qty": 6, "unit_cost": 30}).status_code == 200
    assert client.post(f"{url}/return", headers=h, json={"qty": 1}).status_code == 200
    assert _costs(client, h, pid)[0]["actual"] == 30
    assert client.post(f"{url}/return", headers=h, json={"qty": 3}).status_code == 200
    assert _costs(client, h, pid)[0]["actual"] == 0


def test_material_cost_without_a_project_reaches_the_project_that_takes_the_part(client, admin_headers):
    h = admin_headers
    i = _item(client, h, qty=20, cost=10)
    w = _wo(client, h, qty=5, unit_cost=20)
    m = _materials(client, h, w["id"], {"code": i["code"], "planned_qty": 10})[0]
    assert client.post(f"/api/work-orders/{w['id']}/materials/{m['id']}/issue", headers=h, json={"qty": 4}).status_code == 200
    assert client.post(f"/api/work-orders/{w['id']}/complete", headers=h, json={"qty": 2}).status_code == 200
    # First batch: 40 of material was out, spread over 2 parts; second: the other 60 over 3
    assert _stock_cost(client, h, w["part_no"]) == 40
    assert client.post(f"/api/work-orders/{w['id']}/complete", headers=h, json={"qty": 3}).status_code == 200
    assert _stock_cost(client, h, w["part_no"]) == 40

    part = next(r for r in client.get("/api/stock", headers=h).json()["rows"] if r["code"] == w["part_no"])
    assert part["value"] == 200                       # 5 x 20 conversion + 100 material
    pid = _project(client, h)
    assert client.post(f"/api/stock/{part['id']}/moves", headers=h,
                       json={"kind": "issue", "qty": 5, "project_id": pid}).status_code == 200
    d, src = _costs(client, h, pid)
    assert d["actual"] == 200 and list(src) == ["Stoktan"]


def test_completion_issues_in_proportion(client, admin_headers):
    h = admin_headers
    i = _item(client, h, qty=100, cost=1)
    w = _wo(client, h, qty=10)
    m = _materials(client, h, w["id"], {"code": i["code"], "planned_qty": 40})[0]

    def issued():
        return client.get(f"/api/work-orders/{w['id']}/materials", headers=h).json()[0]["issued_qty"]

    r = client.post(f"/api/work-orders/{w['id']}/complete", headers=h, json={"qty": 2.5})
    assert r.json()["warnings"] == [] and issued() == 10
    # What was issued by hand counts toward the share
    assert client.post(f"/api/work-orders/{w['id']}/materials/{m['id']}/issue", headers=h, json={"qty": 15}).status_code == 200
    client.post(f"/api/work-orders/{w['id']}/complete", headers=h, json={"qty": 2.5})
    assert issued() == 25
    r = client.post(f"/api/work-orders/{w['id']}/complete", headers=h, json={"qty": 5})
    assert r.json()["status"] == "done" and r.json()["warnings"] == []
    assert issued() == 40 and _qty(client, h, i["id"]) == 60


def test_overproduction_does_not_issue_past_the_plan(client, admin_headers):
    h = admin_headers
    i = _item(client, h, qty=100)
    w = _wo(client, h, qty=2)
    _materials(client, h, w["id"], {"code": i["code"], "planned_qty": 10})
    assert client.post(f"/api/work-orders/{w['id']}/complete", headers=h, json={"qty": 3}).status_code == 200
    assert _qty(client, h, i["id"]) == 90


def test_shortage_completes_and_warns(client, admin_headers):
    h = admin_headers
    pid = _project(client, h)
    short, empty, enough = _item(client, h, qty=3, cost=10), _item(client, h), _item(client, h, qty=9)
    w = _wo(client, h, qty=1, project_id=pid)
    _materials(client, h, w["id"], {"code": short["code"], "planned_qty": 5}, {"code": empty["code"], "planned_qty": 1},
               {"code": enough["code"], "planned_qty": 4})
    r = client.post(f"/api/work-orders/{w['id']}/complete", headers=h, json={"qty": 1})
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["status"], d["done_qty"]) == ("done", 1)
    warn = {x["code"]: x for x in d["warnings"]}
    assert set(warn) == {short["code"], empty["code"]}
    assert (warn[short["code"]]["issued"], warn[short["code"]]["short"]) == (3, 2)
    assert (warn[empty["code"]]["issued"], warn[empty["code"]]["short"]) == (0, 1)
    assert warn[short["code"]]["message"]
    assert _qty(client, h, short["id"]) == 0 and _qty(client, h, enough["id"]) == 5
    assert _costs(client, h, pid)[1]["Stoktan"]["actual"] == 30


def test_final_orders_refuse_material_and_route_changes(client, admin_headers):
    h = admin_headers
    i = _item(client, h, qty=50)

    def order():
        w = _wo(client, h, qty=2)
        m = _materials(client, h, w["id"], {"code": i["code"], "planned_qty": 1})[0]
        o = client.put(f"/api/work-orders/{w['id']}/ops", headers=h, json={"rows": [{"name": "Kesim"}]}).json()[0]
        return w, m, o

    done, m1, o1 = order()
    assert client.post(f"/api/work-orders/{done['id']}/complete", headers=h, json={"qty": 2}).status_code == 200
    cancelled, m2, o2 = order()
    assert client.post(f"/api/work-orders/{cancelled['id']}/status", headers=h, json={"status": "cancelled"}).status_code == 200
    closed, m3, o3 = order()
    assert client.post(f"/api/work-orders/{closed['id']}/complete", headers=h, json={"qty": 1}).status_code == 200
    assert client.post(f"/api/work-orders/{closed['id']}/status", headers=h, json={"status": "closed"}).status_code == 200
    for w, m, o in ((done, m1, o1), (cancelled, m2, o2), (closed, m3, o3)):
        base = f"/api/work-orders/{w['id']}"
        rows = {"rows": [{"id": m["id"], "code": i["code"], "planned_qty": 3}]}
        assert client.put(f"{base}/materials", headers=h, json=rows).status_code == 400
        assert client.post(f"{base}/materials/{m['id']}/issue", headers=h, json={"qty": 1}).status_code == 400
        assert client.post(f"{base}/materials/{m['id']}/return", headers=h, json={"qty": 1}).status_code == 400
        assert client.put(f"{base}/ops", headers=h, json={"rows": []}).status_code == 400
        assert client.post(f"{base}/ops/{o['id']}/status", headers=h, json={"status": "done"}).status_code == 400
        assert client.put(base, headers=h, json={"note": "x"}).status_code == 400
        assert client.post(f"{base}/complete", headers=h, json={"qty": 1}).status_code == 400
        assert client.post(f"{base}/status", headers=h, json={"status": "in_progress"}).status_code == 400
        assert client.delete(base, headers=h).status_code == 400
        assert client.get(f"{base}/materials", headers=h).status_code == 200


def test_material_permissions(client, admin_headers):
    h = admin_headers
    i = _item(client, h, qty=10, cost=7)
    w = _wo(client, h)
    m = _materials(client, h, w["id"], {"code": i["code"], "planned_qty": 5})[0]
    o = client.put(f"/api/work-orders/{w['id']}/ops", headers=h, json={"rows": [{"name": "Kesim"}]}).json()[0]
    base = f"/api/work-orders/{w['id']}"
    issue = {"qty": 1}

    # Stock edit alone does not reach a work order
    store, _ = _login(client, h, "viewer", permissions={"stock": "edit", "workorders": "view"})
    assert client.get(f"{base}/materials", headers=store).status_code == 200
    assert client.post(f"{base}/materials/{m['id']}/issue", headers=store, json=issue).status_code == 403
    assert client.post(f"{base}/materials/{m['id']}/return", headers=store, json=issue).status_code == 403
    assert client.put(f"{base}/materials", headers=store, json={"rows": []}).status_code == 403
    assert client.put(f"{base}/ops", headers=store, json={"rows": []}).status_code == 403
    assert client.post(f"{base}/ops/{o['id']}/status", headers=store, json={"status": "done"}).status_code == 403

    none, _ = _login(client, h, "viewer", permissions={"workorders": "none"})
    assert client.get(f"{base}/materials", headers=none).status_code == 403
    assert client.get(f"{base}/ops", headers=none).status_code == 403

    # A planner has it, and so has someone with workorders edit and no stock rights, who sees no stock figure
    planner, _ = _login(client, h, "planner")
    assert client.post(f"{base}/materials/{m['id']}/issue", headers=planner, json=issue).status_code == 200
    foreman, _ = _login(client, h, "viewer", permissions={"workorders": "edit", "stock": "none"})
    r = client.post(f"{base}/materials/{m['id']}/issue", headers=foreman, json=issue)
    assert r.status_code == 200 and r.json()[0]["stock_qty"] is None
    assert _qty(client, h, i["id"]) == 8
    assert not {"unit_cost", "issued_value", "booked_value"} & set(r.json()[0])


# ---------- route ----------
def test_route_progress_and_start(client, admin_headers):
    h = admin_headers
    w = _wo(client, h)
    base = f"/api/work-orders/{w['id']}"
    ops = client.put(f"{base}/ops", headers=h, json={"rows": [
        {"name": "Kesim", "planned_hours": 2}, {"name": "Delme"}, {"name": "Boya"}]}).json()
    assert [o["status"] for o in ops] == ["pending"] * 3 and [o["seq"] for o in ops] == [1, 2, 3]
    row = next(r for r in client.get("/api/work-orders", headers=h).json()["rows"] if r["id"] == w["id"])
    assert (row["status"], row["ops_done"], row["ops_total"]) == ("planned", 0, 3)

    assert client.post(f"{base}/ops/{ops[0]['id']}/status", headers=h, json={"status": "bogus"}).status_code == 400
    r = client.post(f"{base}/ops/{ops[0]['id']}/status", headers=h, json={"status": "in_progress"})
    assert r.status_code == 200
    assert r.json()["status"] == "in_progress" and r.json()["start_date"]
    r = client.post(f"{base}/ops/{ops[0]['id']}/status", headers=h, json={"status": "done"}).json()
    assert (r["ops_done"], r["ops_total"]) == (1, 3)
    assert r["op"]["done_by"] == "admin" and r["op"]["done_at"]
    # Reopening clears who finished it
    r = client.post(f"{base}/ops/{ops[0]['id']}/status", headers=h, json={"status": "pending"}).json()
    assert r["op"]["done_by"] == "" and r["op"]["done_at"] is None and r["status"] == "in_progress"


def test_finishing_a_step_on_a_planned_order_starts_it(client, admin_headers):
    h = admin_headers
    w = _wo(client, h)
    o = client.put(f"/api/work-orders/{w['id']}/ops", headers=h, json={"rows": [{"name": "Kesim"}]}).json()[0]
    assert client.post(f"/api/work-orders/{w['id']}/ops/{o['id']}/status", headers=h, json={"status": "done"}).json()["status"] == "in_progress"


def test_route_edit_rules(client, admin_headers):
    h = admin_headers
    w = _wo(client, h)
    base = f"/api/work-orders/{w['id']}"
    a, b = client.put(f"{base}/ops", headers=h, json={"rows": [{"name": "A"}, {"name": "B"}]}).json()
    assert client.post(f"{base}/ops/{a['id']}/status", headers=h, json={"status": "done"}).status_code == 200
    assert client.put(f"{base}/ops", headers=h, json={"rows": [{"id": b["id"], "name": "B"}]}).status_code == 400
    # Reordering and renaming keep the status; a pending step can go
    r = client.put(f"{base}/ops", headers=h, json={"rows": [{"name": "Yeni"}, {"id": a["id"], "name": "A2"}]})
    assert r.status_code == 200
    assert [(o["name"], o["status"]) for o in r.json()] == [("Yeni", "pending"), ("A2", "done")]
    assert client.put(f"{base}/ops", headers=h, json={"rows": [{"id": 99999999, "name": "x"}]}).status_code == 400
    assert client.put(f"{base}/ops", headers=h, json={"rows": [{"name": "   "}]}).status_code == 400
    other = _wo(client, h)
    assert client.post(f"/api/work-orders/{other['id']}/ops/{a['id']}/status", headers=h, json={"status": "done"}).status_code == 404


# ---------- closed / cancel ----------
def test_close_short_keeps_what_was_made(client, admin_headers):
    h = admin_headers
    pid = _project(client, h)
    w = _wo(client, h, qty=10, project_id=pid, unit_cost=5)
    base = f"/api/work-orders/{w['id']}"
    assert client.post(f"{base}/complete", headers=h, json={"qty": 4}).status_code == 200
    r = client.post(f"{base}/status", headers=h, json={"status": "closed"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["status"], d["status_label"], d["done_qty"], d["qty"]) == ("closed", "Kısa kapatıldı", 4, 10)
    assert (d["remaining"], d["total_cost"], d["overdue"]) == (0, 20, False)
    costs = _costs(client, h, pid)[0]
    assert (costs["actual"], costs["committed"]) == (20, 20)
    assert "closed" in client.get("/api/work-orders", headers=h).json()["statuses"]
    assert w["id"] not in [r["id"] for r in client.get("/api/work-orders?status=open", headers=h).json()["rows"]]
    assert w["id"] in [r["id"] for r in client.get("/api/work-orders?status=closed", headers=h).json()["rows"]]


def test_cancel_refused_once_work_or_material_went_in(client, admin_headers):
    h = admin_headers
    w = _wo(client, h, qty=10)
    base = f"/api/work-orders/{w['id']}"
    assert client.post(f"{base}/complete", headers=h, json={"qty": 1}).status_code == 200
    r = client.post(f"{base}/status", headers=h, json={"status": "cancelled"})
    assert r.status_code == 400 and "kısa kapat" in r.json()["detail"]

    i = _item(client, h, qty=5)
    w = _wo(client, h, qty=10)
    base = f"/api/work-orders/{w['id']}"
    m = _materials(client, h, w["id"], {"code": i["code"], "planned_qty": 1})[0]
    assert client.post(f"{base}/materials/{m['id']}/issue", headers=h, json={"qty": 1}).status_code == 200
    assert client.post(f"{base}/status", headers=h, json={"status": "cancelled"}).status_code == 400
    assert client.delete(base, headers=h).status_code == 400
    assert client.post(f"{base}/materials/{m['id']}/return", headers=h, json={"qty": 1}).status_code == 200
    assert client.post(f"{base}/status", headers=h, json={"status": "cancelled"}).status_code == 200
    assert _qty(client, h, i["id"]) == 5


def test_planned_order_with_a_list_can_be_deleted(client, admin_headers):
    h = admin_headers
    i = _item(client, h)
    w = _wo(client, h)
    _materials(client, h, w["id"], {"code": i["code"], "planned_qty": 1})
    client.put(f"/api/work-orders/{w['id']}/ops", headers=h, json={"rows": [{"name": "A"}]})
    assert client.delete(f"/api/work-orders/{w['id']}", headers=h).status_code == 200


@pytest.mark.parametrize("bad", ["done", "bogus"])
def test_status_route_still_refuses_done_by_hand(client, admin_headers, bad):
    w = _wo(client, admin_headers)
    assert client.post(f"/api/work-orders/{w['id']}/status", headers=admin_headers, json={"status": bad}).status_code == 400
