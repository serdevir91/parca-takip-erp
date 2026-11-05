"""Bağlantı elemanı stoğu: one list over BOM demand and stock cards, with cards opened on first use."""
import random
import uuid

import pytest

from tests.test_api_erp import DATA, F_V1


@pytest.fixture(scope="module")
def pid(client, admin_headers):
    """A BOM with a screw length no other test uses: that fastener has no stock card yet."""
    h = admin_headers
    pid = client.post("/api/projects", json={"name": f"Bağlantı {uuid.uuid4().hex[:8]}"}, headers=h).json()["id"]
    length = random.randint(1000, 9999)
    csv = (DATA / F_V1).read_text(encoding="utf-8").replace("M3 x 5 --- 5N", f"M3 x {length} --- {length}N")
    v = client.post(f"/api/projects/{pid}/bom/upload", headers=h,
                    files={"file": (F_V1, csv.encode("utf-8"), "text/csv")}).json()
    assert client.post(f"/api/projects/{pid}/bom/versions/{v['id']}/approve", headers=h).status_code == 200
    return pid


def _rows(client, h):
    return {r["key"]: r for r in client.get("/api/fastener-stock", headers=h).json()["rows"]}


def _no_card(client, h, pid):
    return next(r for r in _rows(client, h).values()
                if r["item_id"] is None and any(p["id"] == pid for p in r["projects"]))


def test_bom_fasteners_are_listed_before_any_card_exists(client, admin_headers, pid):
    need = _no_card(client, admin_headers, pid)
    assert need["type"] and need["size"] and need["open_need"] > 0 and need["shortage"] == need["open_need"]


def test_quick_moves_open_the_card_and_close_the_shortage(client, admin_headers, pid):
    h = admin_headers
    r = _no_card(client, h, pid)
    need = next(p for p in r["projects"] if p["id"] == pid)["open"]
    out = client.post("/api/fastener-stock/move", headers=h, json={"key": r["key"], "kind": "in", "qty": need + 5})
    assert out.status_code == 200 and out.json()["qty"] == need + 5
    now = _rows(client, h)[r["key"]]
    assert now["item_id"] and now["shortage"] == max(0, r["open_need"] - need - 5)
    out = client.post("/api/fastener-stock/move", headers=h,
                      json={"key": r["key"], "kind": "issue", "qty": need, "project_id": pid})
    assert out.status_code == 200 and out.json()["qty"] == 5
    assert all(p["id"] != pid for p in _rows(client, h)[r["key"]]["projects"])
    assert client.post("/api/fastener-stock/move", headers=h,
                       json={"key": r["key"], "kind": "out", "qty": 6}).status_code == 400
    out = client.post("/api/fastener-stock/move", headers=h, json={"key": r["key"], "kind": "count", "qty": 0})
    assert out.status_code == 200 and out.json()["qty"] == 0


def test_new_fastener_without_a_bom_and_its_minimum(client, admin_headers):
    h = admin_headers
    r = client.put("/api/fastener-stock/card", headers=h,
                   json={"type": "Somun", "std": "DIN 934", "size": "M10", "min_qty": 100, "location": "A-3"})
    assert r.status_code == 200 and r.json()["key"] == "Somun|DIN 934|M10"
    row = _rows(client, h)["Somun|DIN 934|M10"]
    assert row["low"] and row["location"] == "A-3" and row["std"] == "DIN 934"
    again = client.put("/api/fastener-stock/card", headers=h, json={"type": "Somun", "std": "DIN 934", "size": "M10"})
    assert again.status_code == 409
    assert client.put("/api/fastener-stock/card", headers=h, json={"type": "Somun"}).status_code == 400
    r = client.put("/api/fastener-stock/card", headers=h, json={"key": "Somun|DIN 934|M10", "min_qty": 0})
    assert r.status_code == 200 and not r.json()["low"] and r.json()["location"] == "A-3"


def test_a_part_card_with_the_same_code_is_left_alone(client, admin_headers):
    h = admin_headers
    client.post("/api/stock", headers=h, json={"code": "A|B|C", "name": "parça", "kind": "part"})
    r = client.post("/api/fastener-stock/move", headers=h, json={"key": "A|B|C", "kind": "in", "qty": 1})
    assert r.status_code == 409


def test_rights(client, admin_headers):
    from tests.test_security_fixes import _user
    _, h = _user(client, admin_headers, "fs_viewer")
    r = client.post("/api/fastener-stock/move", headers=h, json={"key": "x", "kind": "in", "qty": 1})
    assert r.status_code == 403
