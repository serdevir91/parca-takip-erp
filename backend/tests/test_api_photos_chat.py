"""Product photos and chat (direct messages, groups, attachments, unread counts)."""
from __future__ import annotations

import uuid

import pytest

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
       b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x9a\xa0\xa1\x00\x00\x00\x00IEND\xaeB`\x82")


def _uid(p: str) -> str:
    return f"{p}{uuid.uuid4().hex[:6]}"


def _user(client, admin_headers, role: str = "designer", **perm) -> tuple[int, dict[str, str]]:
    name = _uid("u")
    r = client.post("/api/admin/users", headers=admin_headers,
                    json={"username": name, "full_name": name.upper(), "password": "pass1234", "role": role,
                          "permissions": perm})
    assert r.status_code == 201, r.text
    tok = client.post("/api/auth/login", data={"username": name, "password": "pass1234"}).json()["access_token"]
    return r.json()["id"], {"Authorization": f"Bearer {tok}"}


def test_part_photos(client, admin_headers):
    h = admin_headers
    part = _uid("T01_PH_")
    for i in range(2):
        r = client.post("/api/photos", headers=h, data={"entity": "part", "key": part, "caption": f"Ön {i}"},
                        files={"file": (f"foto{i}.png", PNG, "image/png"), "thumb": ("t.jpg", b"\xff\xd8thumb", "image/jpeg")})
        assert r.status_code == 201, r.text
    bad = client.post("/api/photos", headers=h, data={"entity": "part", "key": part},
                      files={"file": ("not.txt", b"x", "text/plain")})
    assert bad.status_code == 400
    assert client.post("/api/photos", headers=h, data={"entity": "x", "key": part},
                       files={"file": ("a.png", PNG, "image/png")}).status_code == 400

    rows = client.get("/api/photos", headers=h, params={"entity": "part", "key": part}).json()
    assert [p["caption"] for p in rows] == ["Ön 0", "Ön 1"] and rows[0]["preview"]
    assert client.get("/api/photos/counts", headers=h, params={"entity": "part"}).json()[part] == 2

    pid = rows[0]["id"]
    f = client.get(f"/api/photos/{pid}/file", headers=h)
    assert f.status_code == 200 and f.content == PNG
    tok = h["Authorization"].split()[1]
    t = client.get(f"/api/photos/{pid}/thumb", params={"access_token": tok})
    assert t.status_code == 200 and t.content == b"\xff\xd8thumb" and t.headers["content-type"] == "image/jpeg"
    assert client.get(f"/api/photos/{pid}/file").status_code == 401

    assert client.patch(f"/api/photos/{pid}", headers=h, json={"caption": "Yan"}).json()["caption"] == "Yan"
    # Viewers see photos but cannot add or delete them
    _, vh = _user(client, h, "viewer")
    assert client.get("/api/photos", headers=vh, params={"entity": "part", "key": part}).status_code == 200
    assert client.delete(f"/api/photos/{pid}", headers=vh).status_code == 403
    _, nh = _user(client, h, "viewer", parts="none")
    assert client.get("/api/photos", headers=nh, params={"entity": "part", "key": part}).status_code == 403

    assert client.delete(f"/api/photos/{pid}", headers=h).json() == {"ok": True}
    assert client.get(f"/api/photos/{pid}/file", headers=h).status_code == 404
    assert len(client.get("/api/photos", headers=h, params={"entity": "part", "key": part}).json()) == 1


def test_stock_photos_need_an_existing_item(client, admin_headers):
    r = client.post("/api/photos", headers=admin_headers, data={"entity": "stock", "key": "999999"},
                    files={"file": ("a.png", PNG, "image/png")})
    assert r.status_code == 404


@pytest.fixture(scope="module")
def people(client, admin_headers):
    return [_user(client, admin_headers) for _ in range(3)]


def test_direct_messages_and_unread(client, people):
    (a, ah), (b, bh), _ = people
    r = client.post("/api/chat/direct", headers=ah, json={"user_id": b})
    assert r.status_code == 200, r.text
    room = r.json()
    assert room["kind"] == "direct" and len(room["members"]) == 2
    # Same pair, either direction = same room
    assert client.post("/api/chat/direct", headers=bh, json={"user_id": a}).json()["id"] == room["id"]
    assert client.post("/api/chat/direct", headers=ah, json={"user_id": a}).status_code == 400

    before = client.get("/api/chat/state", headers=bh).json()
    m = client.post(f"/api/chat/rooms/{room['id']}/messages", headers=ah, data={"body": "Merhaba"})
    assert m.status_code == 201, m.text
    assert client.post(f"/api/chat/rooms/{room['id']}/messages", headers=ah, data={"body": "  "}).status_code == 400
    st = client.get("/api/chat/state", headers=bh).json()
    assert st["unread"] == before["unread"] + 1 and st["key"] != before["key"]
    rooms_b = {x["id"]: x for x in client.get("/api/chat/rooms", headers=bh).json()}
    assert rooms_b[room["id"]]["unread"] == 1 and rooms_b[room["id"]]["last_message"] == "Merhaba"

    page = client.get(f"/api/chat/rooms/{room['id']}/messages", headers=bh).json()
    assert [x["body"] for x in page["messages"]] == ["Merhaba"]
    client.post(f"/api/chat/rooms/{room['id']}/read", headers=bh, json={"last_id": page["messages"][-1]["id"]})
    assert client.get("/api/chat/state", headers=bh).json()["unread"] == before["unread"]
    # Sender sees the message as read by everybody
    assert client.get(f"/api/chat/rooms/{room['id']}/messages", headers=ah).json()["read_by_all"] == m.json()["id"]

    # Only the author deletes; outsiders do not see the room at all
    assert client.delete(f"/api/chat/messages/{m.json()['id']}", headers=bh).status_code == 403
    assert client.delete(f"/api/chat/messages/{m.json()['id']}", headers=ah).json()["deleted"] is True
    _, outsider = people[2]
    assert client.get(f"/api/chat/rooms/{room['id']}/messages", headers=outsider).status_code == 404


def test_group_with_file(client, people):
    (a, ah), (b, bh), (c, ch) = people
    r = client.post("/api/chat/groups", headers=ah, json={"name": "Montaj ekibi", "member_ids": [b]})
    assert r.status_code == 201, r.text
    gid = r.json()["id"]
    assert r.json()["is_admin"] is True
    assert client.post("/api/chat/groups", headers=ah, json={"name": "Boş", "member_ids": []}).status_code == 400

    f = client.post(f"/api/chat/rooms/{gid}/messages", headers=bh, data={"body": "Resim ekte"},
                    files={"file": ("kaynak.png", PNG, "image/png")})
    assert f.status_code == 201, f.text
    msg = f.json()
    assert msg["file"] == {"name": "kaynak.png", "size": len(PNG), "type": "image/png", "image": True}
    tok = ah["Authorization"].split()[1]
    dl = client.get(f"/api/chat/messages/{msg['id']}/file", params={"access_token": tok, "download": True})
    assert dl.status_code == 200 and dl.content == PNG and "attachment" in dl.headers["content-disposition"]
    assert client.get(f"/api/chat/messages/{msg['id']}/thumb", headers=ah).content == PNG
    ctok = ch["Authorization"].split()[1]
    assert client.get(f"/api/chat/messages/{msg['id']}/file", params={"access_token": ctok}).status_code == 404

    # Members cannot manage the group; admins add/remove/rename
    assert client.patch(f"/api/chat/rooms/{gid}", headers=bh, json={"add": [c]}).status_code == 403
    g = client.patch(f"/api/chat/rooms/{gid}", headers=ah, json={"add": [c], "name": "Montaj"}).json()
    assert g["name"] == "Montaj" and {m["id"] for m in g["members"]} == {a, b, c}
    # c joins without an unread backlog but sees the history
    assert next(x for x in client.get("/api/chat/rooms", headers=ch).json() if x["id"] == gid)["unread"] == 0
    kinds = [m["kind"] for m in client.get(f"/api/chat/rooms/{gid}/messages", headers=ch).json()["messages"]]
    assert kinds.count("system") == 3 and "text" in kinds

    # The only admin leaves: the longest-standing member takes over
    assert client.post(f"/api/chat/rooms/{gid}/leave", headers=ah).json() == {"ok": True}
    after = next(x for x in client.get("/api/chat/rooms", headers=bh).json() if x["id"] == gid)
    assert after["is_admin"] is True and a not in {m["id"] for m in after["members"]}
    assert all(x["id"] != gid for x in client.get("/api/chat/rooms", headers=ah).json())


def test_chat_permission_and_sync(client, admin_headers, people):
    _, ah = people[0]
    _, ro = _user(client, admin_headers, "viewer", chat="view")
    no_id, no = _user(client, admin_headers, "viewer", chat="none")
    assert client.get("/api/chat/rooms", headers=ro).status_code == 200
    assert client.post("/api/chat/groups", headers=ro, json={"name": "x", "member_ids": [1]}).status_code == 403
    assert client.get("/api/chat/state", headers=no).status_code == 403
    # People without chat access are not offered as contacts
    ids = {u["id"] for u in client.get("/api/chat/users", headers=ah).json()}
    assert people[1][0] in ids and no_id not in ids
    # Chat writes do not bump the global live-sync counter
    rev = client.get("/api/sync").json()["rev"]
    room = client.get("/api/chat/rooms", headers=ah).json()[0]["id"]
    client.post(f"/api/chat/rooms/{room}/messages", headers=ah, data={"body": "sessiz"})
    assert client.get("/api/sync").json()["rev"] == rev
