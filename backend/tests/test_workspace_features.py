"""Bildirim merkezi, screen settings kept on the server, project templates."""
from datetime import date, timedelta

from tests.test_security_fixes import _user


def _keys(client, headers):
    return {i["key"]: i for i in client.get("/api/notifications", headers=headers).json()["items"]}


def test_notifications_follow_the_users_modules(client, admin_headers):
    item = client.post("/api/stock", headers=admin_headers, json={"code": "BLD-1", "name": "Vida", "unit": "adet",
                                                                  "min_qty": 5}).json()
    _, planner = _user(client, admin_headers, "bld_planner", "planner")
    assert client.post("/api/admin/users", headers=admin_headers, json={
        "username": "bld_none", "password": "pass1234", "role": "viewer", "permissions": {"stock": "none"}}).status_code == 201
    token = client.post("/api/auth/login", data={"username": "bld_none", "password": "pass1234"}).json()["access_token"]
    key = f"low:{item['id']}:0"
    assert key in _keys(client, admin_headers) and key in _keys(client, planner)
    assert key not in _keys(client, {"Authorization": f"Bearer {token}"})


def test_a_dismissed_warning_returns_when_the_facts_change(client, admin_headers):
    item = client.post("/api/stock", headers=admin_headers, json={"code": "BLD-2", "name": "Somun", "unit": "adet",
                                                                  "min_qty": 5}).json()
    key = f"low:{item['id']}:0"
    assert client.post("/api/notifications/read", headers=admin_headers, json={"keys": [key, "uydurma"]}).status_code == 200
    assert key not in _keys(client, admin_headers)
    r = client.post(f"/api/stock/{item['id']}/moves", headers=admin_headers, json={"kind": "in", "qty": 2})
    assert r.status_code in (200, 201), r.text
    assert f"low:{item['id']}:2" in _keys(client, admin_headers)


def test_late_purchase_order_warns_only_after_it_is_sent(client, admin_headers):
    firm = client.post("/api/admin/firms", headers=admin_headers, json={"name": "Bildirim Tedarik"}).json()
    late = (date.today() - timedelta(days=3)).isoformat()
    po = client.post("/api/purchase-orders", headers=admin_headers, json={
        "firm_id": firm["id"], "due_date": late,
        "lines": [{"part_no": "BLD-P", "description": "x", "qty": 1, "unit_price": 1}]}).json()
    key = f"po:{po['id']}:{late}"
    assert key not in _keys(client, admin_headers)
    assert client.post(f"/api/purchase-orders/{po['id']}/status", headers=admin_headers, json={"status": "sent"}).status_code == 200
    assert _keys(client, admin_headers)[key]["urgent"] is True


def test_prefs_belong_to_their_user(client, admin_headers):
    _, a = _user(client, admin_headers, "pref_a", "viewer")
    _, b = _user(client, admin_headers, "pref_b", "viewer")
    assert client.put("/api/me/prefs/dg.views.parts", json={"value": "[1]"}, headers=a).status_code == 200
    assert client.put("/api/me/prefs/dg.views.parts", json={"value": "[1,2]"}, headers=a).status_code == 200
    assert client.get("/api/me/prefs", headers=a).json() == {"dg.views.parts": "[1,2]"}
    assert client.get("/api/me/prefs", headers=b).json() == {}
    assert client.put("/api/me/prefs/kötü anahtar", json={"value": "x"}, headers=a).status_code == 422
    assert client.delete("/api/me/prefs/dg.views.parts", headers=a).status_code == 200
    assert client.get("/api/me/prefs", headers=a).json() == {}


def _project(client, headers, name, **extra):
    r = client.post("/api/projects", json={"name": name, **extra}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_a_template_starts_a_project_with_its_tree(client, admin_headers):
    pid = _project(client, admin_headers, "Şablon kaynağı")
    url = "/api/project-templates"
    assert client.post(url, json={"project_id": pid, "name": "Boş"}, headers=admin_headers).status_code == 400
    tree = {"part_no": "ANA-1", "name": "Ana", "assembly": True, "children": [{"part_no": "ALT-1", "name": "Alt", "qty": 2}]}
    assert client.put(f"/api/projects/{pid}/bom/draft", json={"tree": tree}, headers=admin_headers).status_code == 200

    t = client.post(url, json={"project_id": pid, "name": "Standart makine"}, headers=admin_headers).json()
    assert t["nodes"] == 2
    assert client.post(url, json={"project_id": pid, "name": "Standart makine"}, headers=admin_headers).status_code == 400

    new = _project(client, admin_headers, "Şablondan proje", template_id=t["id"])
    draft = client.get(f"/api/projects/{new}/bom/draft", headers=admin_headers).json()["draft"]
    assert draft["tree"]["part_no"] == "ANA-1" and draft["tree"]["children"][0]["qty"] == 2
    assert client.post("/api/projects", json={"name": "Olmayan", "template_id": 99999}, headers=admin_headers).status_code == 404

    assert client.delete(f"{url}/{t['id']}", headers=admin_headers).status_code == 200
    assert client.get(f"/api/projects/{new}/bom/draft", headers=admin_headers).json()["draft"]["tree"]["part_no"] == "ANA-1"


def test_templates_need_project_rights(client, admin_headers):
    uid, h = _user(client, admin_headers, "tpl_none", "viewer")
    assert client.post("/api/project-templates", json={"project_id": 1, "name": "x"}, headers=h).status_code == 403
