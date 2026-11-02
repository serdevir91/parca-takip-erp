from __future__ import annotations

import uuid

import pytest

from app.core.status import PROG_DONE, PROG_RUN, PROG_WAIT

F_V1 = "BOM_T01_0004_0000_v1.csv"


def _project_with_bom(client, h, data_file, prefix: str, fname: str = F_V1) -> int:
    pid = client.post("/api/projects", json={"name": f"{prefix} {uuid.uuid4().hex[:8]}"}, headers=h).json()["id"]
    with open(data_file(fname), "rb") as f:
        v = client.post(f"/api/projects/{pid}/bom/upload", headers=h,
                        files={"file": (fname, f, "text/csv")}).json()
    r = client.post(f"/api/projects/{pid}/bom/versions/{v['id']}/approve", headers=h)
    assert r.status_code == 200, r.text
    return pid


def _parts(client, h, pid, **params) -> list[dict]:
    r = client.get(f"/api/projects/{pid}/parts", params=params, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["rows"]


@pytest.fixture(scope="module")
def viewer_headers(client):
    from app.auth import hash_password
    from app.db import SessionLocal
    from app.models import User
    name = f"izleyici_{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        db.add(User(username=name, role="viewer", password_hash=hash_password("izle-123")))
        db.commit()
    r = client.post("/api/auth/login", data={"username": name, "password": "izle-123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_list_filters_and_choices(client, admin_headers, data_file):
    h = admin_headers
    pid = _project_with_bom(client, h, data_file, "Parça liste")
    flat = client.get(f"/api/projects/{pid}/parts", headers=h).json()
    assert flat["count"] == flat["total"] > 0 and flat["total_qty"] > 0
    assert len({p["part_no"] for p in flat["rows"]}) == flat["count"]
    tree = client.get(f"/api/projects/{pid}/parts", params={"view": "tree"}, headers=h).json()
    assert tree["count"] >= flat["count"]
    first = flat["rows"][0]
    found = _parts(client, h, pid, q=first["part_no"].lower())
    assert first["part_no"] in [p["part_no"] for p in found]
    by_status = _parts(client, h, pid, status=first["status"])
    assert by_status and all(p["status"] == first["status"] for p in by_status)
    page = client.get(f"/api/projects/{pid}/parts", params={"limit": 2, "offset": 1}, headers=h).json()
    assert len(page["rows"]) == min(2, flat["count"] - 1) and page["count"] == flat["count"]
    ch = client.get(f"/api/projects/{pid}/parts/choices", headers=h).json()
    assert ch["progress_choices"] == [PROG_WAIT, PROG_RUN, PROG_DONE]
    assert "İmalat" in ch["temin_choices"] and ch["statuses"]


def test_inline_bulk_edit_and_detail(client, admin_headers, data_file):
    h = admin_headers
    pid = _project_with_bom(client, h, data_file, "Parça düzen")
    parts = _parts(client, h, pid)
    a, b = parts[0]["part_no"], parts[1]["part_no"]

    r = client.patch(f"/api/projects/{pid}/parts/{a}",
                     json={"progress": PROG_RUN, "note": "kaynak bekliyor", "procurement_override": "İmalat"},
                     headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["changed"] == 3
    assert body["part"]["progress"] == PROG_RUN and body["part"]["note"] == "kaynak bekliyor"
    assert body["part"]["procurement"] == "İmalat"
    # Same values again: nothing changes
    assert client.patch(f"/api/projects/{pid}/parts/{a}", json={"progress": PROG_RUN},
                        headers=h).json()["changed"] == 0

    for bad in ({"progress": "Bitti"}, {"procurement_override": "Kiralık"}, {"material_status": "Yok"},
                {"progress": None}):
        assert client.patch(f"/api/projects/{pid}/parts/{a}", json=bad, headers=h).status_code == 400, bad
    assert client.patch(f"/api/projects/{pid}/parts/YOK_BOYLE_PARCA", json={"note": "x"},
                        headers=h).status_code == 404

    r = client.post(f"/api/projects/{pid}/parts/bulk",
                    json={"part_nos": [a, b, "YOK_BOYLE_PARCA"], "changes": {"progress": PROG_DONE}}, headers=h)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["updated"] == 2 and res["not_found"] == ["YOK_BOYLE_PARCA"]
    rows = {p["part_no"]: p for p in _parts(client, h, pid, progress=PROG_DONE)}
    assert {a, b} <= set(rows)
    assert client.post(f"/api/projects/{pid}/parts/bulk", json={"part_nos": [a], "changes": {}},
                       headers=h).status_code == 400

    d = client.get(f"/api/projects/{pid}/parts/{a}", headers=h).json()
    assert d["part"]["progress"] == PROG_DONE and d["occurrences"]
    fields = [x["field"] for x in d["history"]]
    assert "progress" in fields and "note" in fields
    assert d["history"][0]["new"] == PROG_DONE
    assert client.get(f"/api/projects/{pid}/parts/YOK_BOYLE_PARCA", headers=h).status_code == 404

    dash = client.get(f"/api/projects/{pid}/dashboard", headers=h).json()
    assert dash["project"]["id"] == pid and dash["kpi"]["unique_parts"] > 0
    assert dash["kpi"]["progress_pct"] > 0
    assert client.get(f"/api/projects/{pid}/dashboard", params={"version_id": 999999},
                      headers=h).status_code == 404


def test_missing_rows(client, admin_headers, data_file):
    h = admin_headers
    pid = _project_with_bom(client, h, data_file, "Eksik")
    pno = _parts(client, h, pid)[0]["part_no"]
    r = client.post(f"/api/projects/{pid}/missing", json={"part_no": pno, "qty": 3, "reason": "Hurda"}, headers=h)
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["qty"] == 3 and m["progress"] == PROG_WAIT and m["in_bom"]
    assert client.post(f"/api/projects/{pid}/missing", json={"part_no": "YOK_BOYLE_PARCA"},
                       headers=h).status_code == 400
    assert client.post(f"/api/projects/{pid}/missing", json={"part_no": pno, "qty": 0},
                       headers=h).status_code == 422
    assert client.post(f"/api/projects/{pid}/missing", json={"part_no": pno, "progress": "x"},
                       headers=h).status_code == 400

    r = client.patch(f"/api/projects/{pid}/missing/{m['id']}", json={"qty": 5, "progress": PROG_DONE}, headers=h)
    assert r.status_code == 200 and r.json()["qty"] == 5 and r.json()["progress"] == PROG_DONE
    lst = client.get(f"/api/projects/{pid}/missing", params={"part_no": pno}, headers=h).json()
    assert lst["count"] == 1 and lst["total_qty"] == 5
    d = client.get(f"/api/projects/{pid}/parts/{pno}", headers=h).json()
    assert d["missing"][0]["id"] == m["id"]
    assert any(x["entity"] == "missing" for x in d["history"])

    other = _project_with_bom(client, h, data_file, "Eksik diğer")
    assert client.delete(f"/api/projects/{other}/missing/{m['id']}", headers=h).status_code == 404
    assert client.delete(f"/api/projects/{pid}/missing/{m['id']}", headers=h).status_code == 200
    assert client.get(f"/api/projects/{pid}/missing", headers=h).json()["count"] == 0


def test_viewer_read_only(client, admin_headers, viewer_headers, data_file):
    pid = _project_with_bom(client, admin_headers, data_file, "İzleyici")
    v = viewer_headers
    pno = _parts(client, v, pid)[0]["part_no"]
    assert client.get(f"/api/projects/{pid}", headers=v).status_code == 200
    assert client.get(f"/api/projects/{pid}/parts/{pno}", headers=v).status_code == 200
    assert client.get(f"/api/projects/{pid}/dashboard", headers=v).status_code == 200
    assert client.get(f"/api/projects/{pid}/bom/versions", headers=v).status_code == 200
    with open(data_file(F_V1), "rb") as f:
        up = client.post(f"/api/projects/{pid}/bom/upload", headers=v, files={"file": (F_V1, f, "text/csv")})
    denied = [
        client.post("/api/projects", json={"name": f"izleyici {uuid.uuid4().hex[:6]}"}, headers=v),
        client.patch(f"/api/projects/{pid}", json={"description": "x"}, headers=v),
        client.delete(f"/api/projects/{pid}", headers=v),
        up,
        client.post(f"/api/projects/{pid}/bom/undo", headers=v),
        client.patch(f"/api/projects/{pid}/parts/{pno}", json={"progress": PROG_DONE}, headers=v),
        client.post(f"/api/projects/{pid}/parts/bulk", json={"part_nos": [pno], "changes": {"note": "x"}},
                    headers=v),
        client.post(f"/api/projects/{pid}/missing", json={"part_no": pno}, headers=v),
        client.post(f"/api/projects/{pid}/aliases", json={"alias": "A", "part_no": "B"}, headers=v),
    ]
    assert [r.status_code for r in denied] == [403] * len(denied)
