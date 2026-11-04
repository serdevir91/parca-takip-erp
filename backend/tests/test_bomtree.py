from __future__ import annotations

import uuid

from app.core import bomtree
from app.core.bomparse import parse_bom
from app.core.status import DEFAULT_TEMIN_TYPES


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
