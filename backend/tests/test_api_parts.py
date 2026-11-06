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


# ---------- temin types, part names, table cells ----------

def _leaf(client, h, pid) -> dict:
    return next(r for r in _parts(client, h, pid) if not r["is_assembly"] and not r["fastener"])


@pytest.fixture
def temins(client, admin_headers):
    """Restores the default temin list after a test changes it."""
    from app.core.status import DEFAULT_TEMIN_TYPES
    yield
    client.put("/api/admin/settings/temin_types", json={"value": DEFAULT_TEMIN_TYPES}, headers=admin_headers)


def test_default_temin_types_are_offered(client, admin_headers, data_file):
    pid = _project_with_bom(client, admin_headers, data_file, "TeminA")
    c = client.get(f"/api/projects/{pid}/parts/choices", headers=admin_headers).json()
    assert {"İmalat", "Hazır Alım", "Fason İmalat", "Stoktan Karşılama", "Müşteri Malı"} <= set(c["temin_choices"])
    assert c["temin_kinds"]["Fason İmalat"] == "Hazır Alım" and c["temin_kinds"]["İmalat"] == "İmalat"


def test_a_temin_type_decides_status_drawing_and_planning(client, admin_headers, data_file):
    pid = _project_with_bom(client, admin_headers, data_file, "TeminB")
    pno = _leaf(client, admin_headers, pid)["part_no"]

    def row(temin: str) -> dict:
        r = client.patch(f"/api/projects/{pid}/parts/{pno}", json={"procurement_override": temin}, headers=admin_headers)
        assert r.status_code == 200, r.text
        return next(x for x in _parts(client, admin_headers, pid) if x["part_no"] == pno)

    fason = row("Fason İmalat")
    assert fason["status_kind"] == "Hazır Alım" and fason["needs_drawing"]
    assert not row("Standart Parça")["needs_drawing"]
    row("Stoktan Karşılama")
    need = {r["code"]: r for r in client.get(f"/api/projects/{pid}/requirements", headers=admin_headers).json()["rows"]}
    assert need[pno]["action"] == ""


def test_a_new_temin_type_is_accepted_and_the_fixed_ones_stay(client, admin_headers, data_file, temins):
    url = "/api/admin/settings/temin_types"
    types = client.get("/api/admin/settings", headers=admin_headers).json()["temin_types"]
    extra = {"name": "Su Jeti Kesim", "kind": "Hazır Alım", "drawing": True, "order": True}
    assert client.put(url, json={"value": [*types, extra]}, headers=admin_headers).status_code == 200
    pid = _project_with_bom(client, admin_headers, data_file, "TeminC")
    pno = _leaf(client, admin_headers, pid)["part_no"]
    assert client.patch(f"/api/projects/{pid}/parts/{pno}", json={"procurement_override": "Su Jeti Kesim"},
                        headers=admin_headers).status_code == 200
    assert client.put(url, json={"value": [t for t in types if t["name"] != "İmalat"]},
                      headers=admin_headers).status_code == 400
    assert client.put(url, json={"value": [*types, types[0]]}, headers=admin_headers).status_code == 400
    assert client.put(url, json={"value": [*types, {**extra, "kind": "Başka"}]}, headers=admin_headers).status_code == 400
    moved = [{**t, "kind": "Hazır Alım"} if t["name"] == "İmalat" else t for t in types]
    assert client.put(url, json={"value": moved}, headers=admin_headers).status_code == 200
    kinds = {t["name"]: t["kind"] for t in client.get("/api/admin/settings", headers=admin_headers).json()["temin_types"]}
    assert kinds["İmalat"] == "İmalat"


def test_table_cells_save_and_report_the_bad_ones(client, admin_headers, data_file):
    pid = _project_with_bom(client, admin_headers, data_file, "Cells")
    a, b = [r["part_no"] for r in _parts(client, admin_headers, pid) if not r["is_assembly"]][:2]
    r = client.post(f"/api/projects/{pid}/parts/cells", headers=admin_headers, json={"changes": [
        {"part_no": a, "field": "progress", "value": PROG_RUN},
        {"part_no": b, "field": "progress", "value": PROG_DONE},
        {"part_no": a, "field": "part_name", "value": "Sol kapak"},
        {"part_no": b, "field": "procurement_override", "value": "Yok böyle"},
        {"part_no": "OLMAYAN-123", "field": "progress", "value": PROG_RUN},
    ]}).json()
    assert r["fields_changed"] == 3 and r["error_count"] == 1 and r["not_found"] == ["OLMAYAN-123"]
    rows = {x["part_no"]: x for x in _parts(client, admin_headers, pid)}
    assert rows[a]["progress"] == PROG_RUN and rows[b]["progress"] == PROG_DONE and rows[a]["part_name"] == "Sol kapak"


def test_cells_need_the_edit_permission(client, viewer_headers, admin_headers, data_file):
    pid = _project_with_bom(client, admin_headers, data_file, "CellsV")
    body = {"changes": [{"part_no": "X", "field": "progress", "value": PROG_RUN}]}
    assert client.post(f"/api/projects/{pid}/parts/cells", json=body, headers=viewer_headers).status_code == 403
    body = {"items": [{"part_no": "X", "name": "Y"}]}
    assert client.post(f"/api/projects/{pid}/parts/names", json=body, headers=viewer_headers).status_code == 403


def test_a_part_name_is_shared_searchable_and_removable(client, admin_headers, data_file):
    pid = _project_with_bom(client, admin_headers, data_file, "NameA")
    other = _project_with_bom(client, admin_headers, data_file, "NameB")
    pno = _leaf(client, admin_headers, pid)["part_no"]
    tag = f"ad{uuid.uuid4().hex[:8]}"
    r = client.post(f"/api/projects/{pid}/parts/names", headers=admin_headers,
                    json={"items": [{"part_no": pno, "name": tag}, {"part_no": "OLMAYAN-9", "name": "x"}]}).json()
    assert r == {"updated": 1, "matched": 1, "not_found": ["OLMAYAN-9"]}
    assert [x["part_no"] for x in _parts(client, admin_headers, other, q=tag)] == [pno]
    client.post(f"/api/projects/{pid}/parts/names", headers=admin_headers, json={"items": [{"part_no": pno, "name": ""}]})
    assert _parts(client, admin_headers, other, q=tag) == []


def test_grid_export_gives_an_excel_file(client, admin_headers):
    from io import BytesIO

    from openpyxl import load_workbook
    fid = client.post("/api/export/grid", headers=admin_headers, json={
        "columns": ["No", "Adet"], "widths": [140, 70],
        "rows": [["A-1", 2], ['=HYPERLINK("http://x","y")', 3]]}).json()["id"]
    r = client.get(f"/api/export/grid/{fid}", params={"name": "Parçalar"}, headers=admin_headers)
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert client.get("/api/export/grid/" + "0" * 32, headers=admin_headers).status_code == 404
    assert client.get("/api/export/grid/..%2F..%2Fsecret", headers=admin_headers).status_code == 404
    ws = load_workbook(BytesIO(r.content)).active
    assert [c.value for c in ws[1]] == ["No", "Adet"] and ws["B2"].value == 2
    assert ws.freeze_panes == "A2" and ws.auto_filter.ref == "A1:B3"
    assert ws["A3"].data_type == "s"


def _other_editor(client, admin_headers, name):
    assert client.post("/api/admin/users", headers=admin_headers, json={
        "username": name, "password": "pass1234", "full_name": name, "role": "designer"}).status_code == 201
    token = client.post("/api/auth/login", data={"username": name, "password": "pass1234"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_a_stale_edit_does_not_overwrite_someone_else(client, admin_headers, data_file):
    pid = _project_with_bom(client, admin_headers, data_file, "Clash")
    other = _other_editor(client, admin_headers, "clash_other")
    a = next(r["part_no"] for r in _parts(client, admin_headers, pid) if not r["is_assembly"])
    rev = client.get(f"/api/projects/{pid}/parts", headers=admin_headers).json()["rev"]
    url = f"/api/projects/{pid}/parts/{a}"
    assert client.patch(url, json={"note": "onların"}, headers=other).status_code == 200

    r = client.patch(f"{url}?rev={rev}", json={"note": "benim"}, headers=admin_headers)
    assert r.status_code == 409
    c = r.json()["detail"]["conflicts"][0]
    assert (c["field"], c["theirs"], c["mine"], c["by"]) == ("note", "onların", "benim", "clash_other")
    row = next(x for x in _parts(client, admin_headers, pid) if x["part_no"] == a)
    assert row["note"] == "onların"

    # Another field of the same part, and the same value, are no conflict
    assert client.patch(f"{url}?rev={rev}", json={"progress": PROG_RUN}, headers=admin_headers).status_code == 200
    assert client.patch(f"{url}?rev={rev}", json={"note": "onların"}, headers=admin_headers).status_code == 200
    # Nor is one's own earlier edit
    assert client.patch(f"{url}?rev={rev}", json={"progress": PROG_DONE}, headers=admin_headers).status_code == 200
    assert client.patch(f"{url}?rev={rev}&force=true", json={"note": "benim"}, headers=admin_headers).status_code == 200


def test_stale_cells_come_back_and_the_rest_are_saved(client, admin_headers, data_file):
    pid = _project_with_bom(client, admin_headers, data_file, "ClashCells")
    other = _other_editor(client, admin_headers, "clash_cells")
    a, b = [r["part_no"] for r in _parts(client, admin_headers, pid) if not r["is_assembly"]][:2]
    url = f"/api/projects/{pid}/parts/cells"
    rev = client.get(f"/api/projects/{pid}/parts", headers=admin_headers).json()["rev"]
    assert client.post(url, headers=other, json={"changes": [
        {"part_no": a, "field": "progress", "value": PROG_RUN},
        {"part_no": a, "field": "part_name", "value": "Onların adı"}]}).status_code == 200

    body = {"rev": rev, "changes": [
        {"part_no": a, "field": "progress", "value": PROG_DONE},
        {"part_no": a, "field": "part_name", "value": "Benim adım"},
        {"part_no": b, "field": "progress", "value": PROG_DONE}]}
    r = client.post(url, headers=admin_headers, json=body).json()
    assert r["fields_changed"] == 1 and {c["field"] for c in r["conflicts"]} == {"progress", "part_name"}
    rows = {x["part_no"]: x for x in _parts(client, admin_headers, pid)}
    assert rows[a]["progress"] == PROG_RUN and rows[a]["part_name"] == "Onların adı" and rows[b]["progress"] == PROG_DONE

    r = client.post(url, headers=admin_headers, json={**body, "force": True}).json()
    assert not r["conflicts"]
    rows = {x["part_no"]: x for x in _parts(client, admin_headers, pid)}
    assert rows[a]["progress"] == PROG_DONE and rows[a]["part_name"] == "Benim adım"
