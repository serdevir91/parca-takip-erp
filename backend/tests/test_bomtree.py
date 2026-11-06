from __future__ import annotations

import json
import uuid

from openpyxl import Workbook

from app.core import bomtree
from app.core.bomparse import parse_bom
from app.core.status import DEFAULT_TEMIN_TYPES
from app.services import tree_excel


def _node(part_no: str, qty: int = 1, assembly: bool = False, *children: dict, **extra) -> dict:
    return {"part_no": part_no, "qty": qty, "assembly": assembly, "children": list(children), **extra}


def _tree(tag: str = "A") -> dict:
    return _node(f"{tag}_ROOT", 1, True,
                 _node(f"{tag}_SUB", 2, True,
                       _node(f"{tag}_PLATE", 3, procurement="İmalat", material="S235", weight=1.5, rev="B",
                             coating="Boya; mat"),
                       _node("DIN 912 M10 x 60", 4)),
                 _node(f"{tag}_MOTOR", 1, True, _node(f"{tag}_ROTOR", 1), procurement="Hazır Alım"))


def _project(client, headers) -> int:
    r = client.post("/api/projects", json={"name": f"Ağaç {uuid.uuid4().hex[:8]}"}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_csv_goes_through_the_parser():
    bom = parse_bom(bomtree.to_csv(_tree()))
    rows = {r.part_no: r for r in bom.rows}
    assert bom.root_part_no == "A_ROOT"
    assert [r.level for r in bom.rows] == ["1", "1.1", "1.1.1", "1.1.2", "1.2", "1.2.1"]
    assert rows["A_PLATE"].total_qty == 6
    assert (rows["A_PLATE"].material, rows["A_PLATE"].weight, rows["A_PLATE"].rev) == ("S235", 1.5, "B")
    assert rows["A_PLATE"].coating == "Boya; mat"
    assert rows["DIN 912 M10 x 60"].fastener is not None and rows["DIN 912 M10 x 60"].total_qty == 8
    assert rows["A_MOTOR"].is_purchased_assembly and rows["A_ROTOR"].in_purchased


def test_tree_survives_the_round_trip():
    tree = bomtree.from_rows(parse_bom(bomtree.to_csv(_tree())).rows)
    assert tree["part_no"] == "A_ROOT"
    sub = tree["children"][0]
    assert sub["assembly"] and sub["qty"] == 2
    assert [c["part_no"] for c in sub["children"]] == ["A_PLATE", "DIN 912 M10 x 60"]
    assert sub["children"][0]["weight"] == 1.5


def test_validate_finds_what_makes_a_wrong_bom():
    def errors(root: dict) -> str:
        return "\n".join(bomtree.validate(root, [t["name"] for t in DEFAULT_TEMIN_TYPES]))

    assert errors(_tree()) == ""
    assert "boş" in errors(_node("R", 1, True, _node("")))
    assert "en az 1" in errors(_node("R", 1, True, _node("P", 0)))
    assert "kendi altına" in errors(_node("R", 1, True, _node("S", 1, True, _node("R", 1, True))))
    assert "iki kez" in errors(_node("R", 1, True, _node("P"), _node("P")))
    assert "hem parça hem montaj" in errors(_node("R", 1, True, _node("S", 1, True, _node("P")), _node("P", 1, True)))
    assert "montaj olmalı" in errors(_node("R", 1, True, _node("S", 1, False, _node("P"))))
    assert "temin" in errors(_node("R", 1, True, _node("P", procurement="Hediye")))


def test_submit_makes_a_pending_version_that_approves(client, admin_headers):
    pid = _project(client, admin_headers)
    tag = "T" + uuid.uuid4().hex[:6]
    r = client.post(f"/api/projects/{pid}/bom/tree/submit", json={"tree": _tree(tag), "note": "elle"},
                    headers=admin_headers)
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["status"] == "pending" and v["note"] == "elle"
    assert client.post(f"/api/projects/{pid}/bom/versions/{v['id']}/approve", json={},
                       headers=admin_headers).status_code == 200
    rows = client.get(f"/api/projects/{pid}/parts", headers=admin_headers).json()["rows"]
    assert {r["part_no"] for r in rows} >= {f"{tag}_PLATE", f"{tag}_SUB"}

    back = client.get(f"/api/projects/{pid}/bom/versions/{v['id']}/tree", headers=admin_headers).json()["tree"]
    assert back["children"][0]["part_no"] == f"{tag}_SUB"

    other = _project(client, admin_headers)
    found = client.get(f"/api/projects/{other}/bom/items", params={"q": f"{tag}_pl"}, headers=admin_headers).json()
    assert [i["part_no"] for i in found] == [f"{tag}_PLATE"] and found[0]["material"] == "S235"
    sub = client.get(f"/api/projects/{other}/bom/items/tree", params={"part_no": f"{tag}_SUB"},
                     headers=admin_headers).json()["tree"]
    assert [c["part_no"] for c in sub["children"]] == [f"{tag}_PLATE", "DIN 912 M10 x 60"]


def test_submit_refuses_a_bad_tree_and_keeps_the_draft(client, admin_headers):
    pid = _project(client, admin_headers)
    bad = _node("R", 1, True, _node(""))
    assert client.put(f"/api/projects/{pid}/bom/draft", json={"tree": bad}, headers=admin_headers).status_code == 200
    r = client.post(f"/api/projects/{pid}/bom/tree/submit", json={"tree": bad}, headers=admin_headers)
    assert r.status_code == 400 and "boş" in r.json()["detail"]
    assert client.get(f"/api/projects/{pid}/bom/versions", headers=admin_headers).json() == []
    assert client.get(f"/api/projects/{pid}/bom/draft", headers=admin_headers).json()["draft"] is not None


def test_draft_rev_stops_a_silent_overwrite(client, admin_headers):
    pid = _project(client, admin_headers)
    url, tree = f"/api/projects/{pid}/bom/draft", _node("R", 1, True)
    assert client.get(url, headers=admin_headers).json()["draft"] is None
    assert client.put(url, json={"tree": tree, "rev": 0}, headers=admin_headers).json()["rev"] == 1
    assert client.put(url, json={"tree": tree, "rev": 1}, headers=admin_headers).json()["rev"] == 2
    assert client.put(url, json={"tree": tree, "rev": 1}, headers=admin_headers).status_code == 409
    assert client.put(url, json={"tree": tree, "rev": None}, headers=admin_headers).json()["rev"] == 3
    assert client.delete(url, headers=admin_headers).status_code == 200
    assert client.get(url, headers=admin_headers).json()["draft"] is None


def test_submit_clears_the_draft(client, admin_headers):
    pid = _project(client, admin_headers)
    tree = _tree("T" + uuid.uuid4().hex[:6])
    client.put(f"/api/projects/{pid}/bom/draft", json={"tree": tree}, headers=admin_headers)
    assert client.post(f"/api/projects/{pid}/bom/tree/submit", json={"tree": tree},
                       headers=admin_headers).status_code == 201
    assert client.get(f"/api/projects/{pid}/bom/draft", headers=admin_headers).json()["draft"] is None


def test_hidden_only_dims(client, admin_headers):
    """The flag is shown on the rows and changes no quantity, status or requirement."""
    pid = _project(client, admin_headers)
    tag = "T" + uuid.uuid4().hex[:6]
    v = client.post(f"/api/projects/{pid}/bom/tree/submit", json={"tree": _tree(tag)}, headers=admin_headers).json()
    client.post(f"/api/projects/{pid}/bom/versions/{v['id']}/approve", json={}, headers=admin_headers)
    url = f"/api/projects/{pid}/parts"
    before = client.get(url, headers=admin_headers).json()["rows"]
    need_before = client.get(f"/api/projects/{pid}/requirements", headers=admin_headers).json()["summary"]

    r = client.post(f"{url}/bulk", json={"part_nos": [f"{tag}_PLATE"], "changes": {"hidden": True}},
                    headers=admin_headers)
    assert r.status_code == 200 and r.json()["updated"] == 1
    after = client.get(url, headers=admin_headers).json()["rows"]
    assert [p["part_no"] for p in after if p["hidden"]] == [f"{tag}_PLATE"]
    strip = lambda rows: [{k: v for k, v in p.items() if k not in ("hidden", "updated_at", "updated_by")} for p in rows]  # noqa: E731
    assert strip(after) == strip(before)
    assert client.get(f"/api/projects/{pid}/requirements", headers=admin_headers).json()["summary"] == need_before

    key = client.get(f"/api/projects/{pid}/fasteners", headers=admin_headers).json()["items"][0]["key"]
    r = client.put(f"/api/projects/{pid}/fasteners/settings", json={"keys": [key], "hidden": True}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["items"][0]["hidden"] is True
    needs = client.get(f"/api/projects/{pid}/requirements", headers=admin_headers).json()["rows"]
    assert {n["code"] for n in needs if n["hidden"]} == {f"{tag}_PLATE", key}

    client.post(f"{url}/bulk", json={"part_nos": [f"{tag}_PLATE"], "changes": {"hidden": False}}, headers=admin_headers)
    assert not any(p["hidden"] for p in client.get(url, headers=admin_headers).json()["rows"])


def test_tree_names_are_saved_and_come_back(client, admin_headers):
    pid = _project(client, admin_headers)
    tag = f"AD{uuid.uuid4().hex[:6]}"
    plate = {**_node(f"{tag}_P"), "name": "Yan sac"}
    r = client.post(f"/api/projects/{pid}/bom/tree/submit", json={"tree": _node(f"{tag}_R", 1, True, plate)},
                    headers=admin_headers)
    assert r.status_code == 201, r.text
    tree = client.get(f"/api/projects/{pid}/bom/versions/{r.json()['id']}/tree", headers=admin_headers).json()["tree"]
    assert tree["children"][0]["name"] == "Yan sac"
    found = client.get(f"/api/projects/{pid}/bom/items", params={"q": "yan sac"}, headers=admin_headers).json()
    assert f"{tag}_P" in [i["part_no"] for i in found]


def _book(tmp_path, rows, name="liste.xlsx"):
    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    p = tmp_path / name
    wb.save(p)
    return p


def _item(no, *children, **kw):
    return {"part_no": no, "name": "", "assembly": bool(children), "qty": 1, "material": "", "weight": None, "rev": "",
            "procurement": "", "coating": "", "children": list(children), **kw}


TEMINS = ["Lazer Kesim", "Talaşlı İmalat", "Montaj"]


def test_excel_changes_new_rows_and_absent_parts(tmp_path):
    tree = _item("KOK", _item("M-1", _item("P-1", qty=2, material="S235"), _item("P-2")), _item("P-3"))
    p = _book(tmp_path, [
        ["Parça No", "Parça Adı", "Adet", "Malzeme", "Ağırlık (kg)", "Temin Şekli", "Üst Montaj"],
        ["p 1.SLDPRT", "Mil", 3, "S355", 1.5, "lazer", "M-1"],
        ["P-9", "Yeni", 2, "", "", "Talaşlı İmalat", "M-1"],
        ["P-9", "", 1, "", "", "", "M-1"],
        ["P-2", "", "bir", "", "", "Bilinmeyen", "M-1"],
    ])
    r = tree_excel.compare(p, tree, {}, TEMINS)
    got = {(c["part_no"], c["field"]): (c["old"], c["new"]) for c in r["changes"]}
    assert got == {("P-1", "name"): ("", "Mil"), ("P-1", "material"): ("S235", "S355"), ("P-1", "weight"): (None, 1500.0),
                   ("P-1", "procurement"): ("", "Lazer Kesim"), ("P-1", "qty"): (2, 3)}
    assert [(a["part_no"], a["qty"], a["parent_no"], a["procurement"]) for a in r["add"]] == [("P-9", 3, "M-1", "Talaşlı İmalat")]
    assert {a["part_no"] for a in r["absent"]} == {"M-1", "P-3"}
    assert sorted(i["field"] for i in r["invalid"]) == ["qty", "temin"]
    assert r["layouts"][0]["cols"]["part_no"] == 1 and r["placed"]


def test_excel_level_column_builds_an_empty_tree(tmp_path):
    p = _book(tmp_path, [
        ["Seviye", "Parça No", "Tip", "Adet"],
        [0, "MAKINE", "Montaj", 1],
        [1, "GOVDE", "Montaj", 1],
        ["1.1", "SAC", "Parça", 4],
        [1, "KAPAK", "Parça", 2],
    ])
    r = tree_excel.compare(p, _item(""), {}, TEMINS)
    assert r["root"]["part_no"] == "MAKINE"
    assert {(a["part_no"], a["parent_no"], a["assembly"]) for a in r["add"]} == {
        ("GOVDE", "MAKINE", True), ("KAPAK", "MAKINE", False), ("SAC", "GOVDE", False)}
    names = [a["part_no"] for a in r["add"]]
    assert names.index("GOVDE") < names.index("SAC")


def test_excel_without_places_keeps_a_shared_quantity(tmp_path):
    tree = _item("KOK", _item("A", _item("P", qty=2)), _item("B", _item("P", qty=5)))
    p = _book(tmp_path, [["Parça No", "Adet", "Malzeme"], ["P", 9, "S235"]])
    r = tree_excel.compare(p, tree, {}, TEMINS)
    assert [(c["field"], c["new"]) for c in r["changes"]] == [("material", "S235")]
    assert not r["placed"] and not r["add"]


def test_excel_column_correction_and_api(client, admin_headers, tmp_path):
    h = admin_headers
    pid = client.post("/api/projects", headers=h, json={"name": f"Excel ağacı {uuid.uuid4().hex[:6]}"}).json()["id"]
    p = _book(tmp_path, [["X-1", "Sac"], ["X-2", "Mil"], ["X-3", "Pim"]])
    tree = json.dumps(_item("KOK", _item("X-1"), _item("X-2")))

    def send(config=None):
        with open(p, "rb") as f:
            return client.post(f"/api/projects/{pid}/bom/tree/excel", headers=h, data={"tree": tree, **config},
                               files={"file": ("l.xlsx", f, "application/octet-stream")})

    r = send({}).json()
    assert r["layouts"][0]["cols"] == {"part_no": 1} and [a["part_no"] for a in r["add"]] == ["X-3"]
    cfg = {"sheets": {r["layouts"][0]["name"]: {"use": True, "cols": {"part_no": 1, "name": 2, "unknown": 2, "qty": 99}}}}
    r = send({"config": json.dumps(cfg)}).json()
    assert r["layouts"][0]["cols"] == {"part_no": 1, "name": 2}
    assert {(c["part_no"], c["new"]) for c in r["changes"]} == {("X-1", "Sac"), ("X-2", "Mil")}
    assert send({"config": "["}).status_code == 400
    assert client.post(f"/api/projects/{pid}/bom/tree/excel", headers=h, data={"tree": "{"},
                       files={"file": ("l.xlsx", b"x", "application/octet-stream")}).status_code == 400
