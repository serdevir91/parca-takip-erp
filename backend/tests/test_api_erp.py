"""ERP modules: purchase orders, goods receipt, stock, work orders, requirement planning and cost."""
from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest
from openpyxl import load_workbook

from app.core.status import PROG_DONE, PROG_RUN

DATA = Path(__file__).parent / "data"
F_V1 = "BOM_T01_0004_0000_v1.csv"


@pytest.fixture(scope="module")
def pid(client, admin_headers):
    h = admin_headers
    pid = client.post("/api/projects", json={"name": f"ERP {uuid.uuid4().hex[:8]}"}, headers=h).json()["id"]
    with open(DATA / F_V1, "rb") as f:
        v = client.post(f"/api/projects/{pid}/bom/upload", headers=h, files={"file": (F_V1, f, "text/csv")}).json()
    assert client.post(f"/api/projects/{pid}/bom/versions/{v['id']}/approve", headers=h).status_code == 200
    return pid


@pytest.fixture(scope="module")
def firm_id(client, admin_headers):
    r = client.post("/api/admin/firms", headers=admin_headers, json={
        "name": f"Tedarikçi {uuid.uuid4().hex[:6]}", "kind": "supplier", "phone": "0212 000 00 00",
        "email": "satis@example.com", "tax_office": "Kadıköy", "tax_no": "1234567890", "lead_days": 7})
    assert r.status_code == 201, r.text
    assert r.json()["lead_days"] == 7
    return r.json()["id"]


def _need(client, h, pid) -> dict[str, dict]:
    r = client.get(f"/api/projects/{pid}/requirements", headers=h)
    assert r.status_code == 200, r.text
    return {x["code"]: x for x in r.json()["rows"]}


def _part(client, h, pid, part_no) -> dict:
    rows = client.get(f"/api/projects/{pid}/parts", params={"view": "flat"}, headers=h).json()["rows"]
    return next(r for r in rows if r["part_no"] == part_no)


def test_firm_picker_lists_supplier_card(client, admin_headers, firm_id):
    firms = client.get("/api/firms", params={"kind": "supplier"}, headers=admin_headers).json()
    f = next(x for x in firms if x["id"] == firm_id)
    assert f["phone"] and f["email"] == "satis@example.com"


def test_requirements_cover_parts_and_fasteners(client, admin_headers, pid):
    need = _need(client, admin_headers, pid)
    kinds = {r["kind"] for r in need.values()}
    assert kinds == {"part", "fastener"}
    # in-house assemblies are not procured, so they are not in the list
    parts = client.get(f"/api/projects/{pid}/parts", params={"view": "flat"}, headers=admin_headers).json()["rows"]
    asm = [p["part_no"] for p in parts if p["is_assembly"] and not p["is_purchased_assembly"]]
    assert asm and not set(asm) & set(need)
    for r in need.values():
        assert r["shortage"] == r["required"] and r["action"] in ("purchase", "work_order")
    assert any(r["action"] == "work_order" for r in need.values())


def test_purchase_order_flow_updates_tracking_and_stock(client, admin_headers, pid, firm_id):
    h = admin_headers
    need = _need(client, h, pid)
    code = next(c for c, r in need.items() if r["kind"] == "part" and r["action"] == "purchase")
    fkey = next(c for c, r in need.items() if r["kind"] == "fastener")
    r = client.post(f"/api/projects/{pid}/requirements/purchase-order", headers=h,
                    json={"codes": [code, fkey], "firm_id": firm_id, "due_date": "2026-12-01"})
    assert r.status_code == 201, r.text
    po = r.json()
    assert po["no"].startswith("SA-") and po["status"] == "draft" and po["project_id"] == pid
    assert {l["code"] for l in po["lines"]} == {code, fkey}

    # draft lines count as on order: the shortage disappears, nothing double-ordered
    assert _need(client, h, pid)[code]["shortage"] == 0
    assert client.post(f"/api/projects/{pid}/requirements/purchase-order", headers=h,
                       json={"codes": [code]}).status_code == 400

    lines = [{**{k: l[k] for k in ("code", "kind", "description", "unit", "qty")}, "unit_price": 12.5}
             for l in po["lines"]]
    r = client.put(f"/api/purchase-orders/{po['id']}", headers=h, json={"lines": lines, "note": "acil"})
    assert r.status_code == 200 and r.json()["total"] > 0

    r = client.post(f"/api/purchase-orders/{po['id']}/status", headers=h, json={"status": "sent"})
    assert r.status_code == 200 and r.json()["order_date"]
    assert _part(client, h, pid, code)["progress"] == PROG_RUN
    fs = {f["key"]: f for f in client.get(f"/api/projects/{pid}/fasteners", headers=h).json()["items"]}
    assert fs[fkey]["order_status"] == "Sipariş Verildi"
    # lines are frozen once sent
    assert client.put(f"/api/purchase-orders/{po['id']}", headers=h, json={"lines": lines}).status_code == 400

    po = r.json()
    pl = next(l for l in po["lines"] if l["code"] == code)
    if pl["qty"] > 1:
        r = client.post(f"/api/purchase-orders/{po['id']}/receive", headers=h,
                        json={"lines": [{"line_id": pl["id"], "qty": 1}]})
        assert r.status_code == 200 and r.json()["status"] == "partial"
        assert _part(client, h, pid, code)["progress"] == PROG_RUN
    po = client.get(f"/api/purchase-orders/{po['id']}", headers=h).json()
    r = client.post(f"/api/purchase-orders/{po['id']}/receive", headers=h,
                    json={"lines": [{"line_id": l["id"], "qty": l["remaining"]} for l in po["lines"]]})
    assert r.status_code == 200 and r.json()["status"] == "received", r.text
    assert _part(client, h, pid, code)["progress"] == PROG_DONE
    fs = {f["key"]: f for f in client.get(f"/api/projects/{pid}/fasteners", headers=h).json()["items"]}
    assert fs[fkey]["order_status"] == "Teslim Edildi"

    # project goods are issued straight to the project: free stock stays 0, ledger shows both moves
    stock = {s["code"]: s for s in client.get("/api/stock", headers=h).json()["rows"]}
    assert stock[code]["qty"] == 0 and stock[code]["unit_cost"] == 12.5
    moves = client.get(f"/api/stock/{stock[code]['id']}/moves", headers=h).json()
    assert {m["kind"] for m in moves} == {"receipt", "issue"}
    n = _need(client, h, pid)[code]
    assert n["issued"] == n["required"] and n["shortage"] == 0

    # received orders are closed
    assert client.post(f"/api/purchase-orders/{po['id']}/status", headers=h,
                       json={"status": "cancelled"}).status_code == 400
    assert client.delete(f"/api/purchase-orders/{po['id']}", headers=h).status_code == 400

    r = client.get(f"/api/purchase-orders/{po['id']}/xlsx", headers=h)
    assert r.status_code == 200
    ws = load_workbook(io.BytesIO(r.content)).active
    assert ws["A1"].value == "SATIN ALMA SİPARİŞİ" and ws["B3"].value == po["no"]


def test_stock_issue_covers_requirement(client, admin_headers, pid):
    h = admin_headers
    need = _need(client, h, pid)
    code = next(c for c, r in need.items() if r["kind"] == "part" and r["action"] == "purchase" and r["shortage"])
    req = need[code]["required"]
    item = client.get("/api/stock", params={"q": code}, headers=h).json()["rows"]
    if item:
        sid = item[0]["id"]
    else:
        r = client.post("/api/stock", headers=h, json={"code": code, "name": "test", "qty": 0, "min_qty": 5})
        assert r.status_code == 201, r.text
        sid = r.json()["id"]
    r = client.post(f"/api/stock/{sid}/moves", headers=h, json={"kind": "in", "qty": req + 3, "unit_cost": 4})
    assert r.status_code == 200 and r.json()["qty"] == req + 3
    n = _need(client, h, pid)[code]
    assert n["action"] == "stock" and n["from_stock"] == req and n["shortage"] == 0

    r = client.post(f"/api/projects/{pid}/requirements/issue", headers=h, json=[{"code": code}])
    assert r.status_code == 200 and r.json()["issued"] == 1
    p = _part(client, h, pid, code)
    assert p["progress"] == PROG_DONE and p["material_status"] == "Stoktan"
    s = client.get("/api/stock", params={"q": code}, headers=h).json()["rows"][0]
    assert s["qty"] == 3 and s["low"] is True
    assert client.get("/api/stock", params={"low": True}, headers=h).json()["low_count"] >= 1

    # cannot take out more than is there; count sets the absolute quantity
    assert client.post(f"/api/stock/{sid}/moves", headers=h, json={"kind": "out", "qty": 99}).status_code == 400
    r = client.post(f"/api/stock/{sid}/moves", headers=h, json={"kind": "count", "qty": 0})
    assert r.status_code == 200 and r.json()["qty"] == 0
    costs = client.get(f"/api/projects/{pid}/costs", headers=h).json()
    assert any(s["name"] == "Stoktan" and s["actual"] == req * 4 for s in costs["by_source"])


def test_work_order_flow(client, admin_headers, pid):
    h = admin_headers
    need = _need(client, h, pid)
    code = next(c for c, r in need.items() if r["action"] == "work_order")
    r = client.post(f"/api/projects/{pid}/requirements/work-orders", headers=h,
                    json={"codes": [code], "firm_name": "Fason Kaynak"})
    assert r.status_code == 201, r.text
    wo = r.json()[0]
    assert wo["no"].startswith("IE-") and wo["subcontract"] and wo["status"] == "planned"
    assert _need(client, h, pid)[code]["in_production"] == wo["qty"]

    r = client.put(f"/api/work-orders/{wo['id']}", headers=h, json={"unit_cost": 100})
    assert r.status_code == 200 and r.json()["total_cost"] == 100 * wo["qty"]
    r = client.post(f"/api/work-orders/{wo['id']}/status", headers=h, json={"status": "in_progress"})
    assert r.status_code == 200 and r.json()["start_date"]
    p = _part(client, h, pid, code)
    assert p["progress"] == PROG_RUN and p["manufacturer"] == "Fason Kaynak"
    assert client.delete(f"/api/work-orders/{wo['id']}", headers=h).status_code == 400

    r = client.post(f"/api/work-orders/{wo['id']}/complete", headers=h, json={"qty": wo["qty"]})
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert _part(client, h, pid, code)["progress"] == PROG_DONE
    assert client.post(f"/api/work-orders/{wo['id']}/complete", headers=h, json={"qty": 1}).status_code == 400

    costs = client.get(f"/api/projects/{pid}/costs", headers=h).json()
    src = {s["name"]: s for s in costs["by_source"]}
    assert src["Fason iş emri"]["actual"] == 100 * wo["qty"]
    assert costs["committed"] >= costs["actual"] > 0
    assert any(f["name"] == "Fason Kaynak" for f in costs["by_firm"])


def test_manual_orders_and_numbering(client, admin_headers, firm_id):
    h = admin_headers
    a = client.post("/api/purchase-orders", headers=h, json={
        "firm_id": firm_id, "lines": [{"code": "", "kind": "other", "description": "Kesme hizmeti", "qty": 1}]}).json()
    b = client.post("/api/purchase-orders", headers=h, json={"lines": []}).json()
    assert int(b["no"].split("-")[-1]) == int(a["no"].split("-")[-1]) + 1
    assert client.post(f"/api/purchase-orders/{b['id']}/status", headers=h, json={"status": "sent"}).status_code == 400
    assert client.post(f"/api/purchase-orders/{a['id']}/receive", headers=h,
                       json={"lines": [{"line_id": a["lines"][0]["id"], "qty": 1}]}).status_code == 400
    assert client.post(f"/api/purchase-orders/{a['id']}/status", headers=h, json={"status": "sent"}).status_code == 200
    # a free-text line has no stock card; receiving it just closes the order
    r = client.post(f"/api/purchase-orders/{a['id']}/receive", headers=h,
                    json={"lines": [{"line_id": a["lines"][0]["id"], "qty": 1}]})
    assert r.json()["status"] == "received"
    assert client.delete(f"/api/purchase-orders/{b['id']}", headers=h).status_code == 200
    rows = client.get("/api/purchase-orders", params={"status": "open"}, headers=h).json()["rows"]
    assert all(r["status"] in ("draft", "sent", "partial") for r in rows)
    bad = client.post("/api/purchase-orders", headers=h, json={"lines": [{"code": "X", "qty": 0}]})
    assert bad.status_code == 422


def test_viewer_cannot_write(client, admin_headers):
    from app.auth import hash_password
    from app.db import SessionLocal
    from app.models import User
    name = f"izleyici_{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        db.add(User(username=name, role="viewer", password_hash=hash_password("izle-123")))
        db.commit()
    tok = client.post("/api/auth/login", data={"username": name, "password": "izle-123"}).json()["access_token"]
    vh = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/stock", headers=vh).status_code == 200
    assert client.post("/api/stock", headers=vh, json={"code": "V1"}).status_code == 403
    assert client.post("/api/purchase-orders", headers=vh, json={"lines": []}).status_code == 403
    assert client.post("/api/work-orders", headers=vh, json={"part_no": "X", "qty": 1}).status_code == 403
