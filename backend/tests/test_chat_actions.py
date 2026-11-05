"""Chat actions: edit, reply, forward, delete for me or everyone, reactions, pin, and the notification feed."""
from datetime import timedelta

import pytest

from app.api.chat import EDIT_HOURS
from app.db import SessionLocal
from app.models import ChatMessage, utcnow
from tests.test_security_fixes import _user


@pytest.fixture(scope="module")
def pair(client, admin_headers):
    a_id, a = _user(client, admin_headers, "chat_a")
    b_id, b = _user(client, admin_headers, "chat_b")
    room = client.post("/api/chat/direct", json={"user_id": b_id}, headers=a).json()["id"]
    return a_id, a, b_id, b, room


def _send(client, h, room, text, **extra):
    r = client.post(f"/api/chat/rooms/{room}/messages", headers=h, data={"body": text, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _bodies(client, h, room):
    return {m["id"]: m for m in client.get(f"/api/chat/rooms/{room}/messages", headers=h).json()["messages"]}


def test_edit_shows_for_everyone_and_only_the_author_may(client, pair):
    _, a, _, b, room = pair
    m = _send(client, a, room, "ilk hali")
    key = client.get("/api/chat/state", headers=b).json()["key"]
    assert client.patch(f"/api/chat/messages/{m['id']}", headers=b, json={"body": "x"}).status_code == 403
    r = client.patch(f"/api/chat/messages/{m['id']}", headers=a, json={"body": "son hali"})
    assert r.status_code == 200 and r.json()["edited_at"]
    assert _bodies(client, b, room)[m["id"]]["body"] == "son hali"
    assert client.get("/api/chat/state", headers=b).json()["key"] != key
    assert client.patch(f"/api/chat/messages/{m['id']}", headers=a, json={"body": "  "}).status_code == 400


def test_edit_closes_after_the_limit(client, pair):
    _, a, _, _, room = pair
    m = _send(client, a, room, "eski")
    with SessionLocal() as db:
        db.get(ChatMessage, m["id"]).created_at = utcnow() - timedelta(hours=EDIT_HOURS + 1)
        db.commit()
    assert client.patch(f"/api/chat/messages/{m['id']}", headers=a, json={"body": "yeni"}).status_code == 400


def test_reply_quotes_the_message_and_stays_in_the_room(client, pair, admin_headers):
    _, a, _, b, room = pair
    m = _send(client, a, room, "soru")
    r = _send(client, b, room, "cevap", reply_to=m["id"])
    assert r["reply_to"]["id"] == m["id"] and r["reply_to"]["text"] == "soru"
    assert client.delete(f"/api/chat/messages/{m['id']}", headers=a).status_code == 200
    quote = _bodies(client, b, room)[r["id"]]["reply_to"]
    assert quote["deleted"] and quote["text"] == ""
    other = client.post("/api/chat/direct", json={"user_id": 1}, headers=a).json()["id"]
    bad = client.post(f"/api/chat/rooms/{other}/messages", headers=a, data={"body": "x", "reply_to": r["id"]})
    assert bad.status_code == 400


def test_delete_for_me_hides_it_only_from_me(client, pair):
    _, a, _, b, room = pair
    m = _send(client, a, room, "gizlenecek")
    assert client.delete(f"/api/chat/messages/{m['id']}?scope=me", headers=b).status_code == 200
    assert m["id"] not in _bodies(client, b, room)
    assert _bodies(client, a, room)[m["id"]]["body"] == "gizlenecek"
    assert client.delete(f"/api/chat/messages/{m['id']}", headers=b).status_code == 403


def test_delete_for_everyone_drops_it_from_unread(client, pair):
    _, a, _, b, room = pair
    client.post(f"/api/chat/rooms/{room}/read", headers=b, json={"last_id": 10 ** 9})
    m = _send(client, a, room, "yanlış kişi")
    assert client.get("/api/chat/state", headers=b).json()["unread"] == 1
    client.delete(f"/api/chat/messages/{m['id']}", headers=a)
    assert client.get("/api/chat/state", headers=b).json()["unread"] == 0
    assert _bodies(client, b, room)[m["id"]]["deleted"]


def test_group_admin_deletes_others_messages(client, admin_headers, pair):
    a_id, a, b_id, b, _ = pair
    g = client.post("/api/chat/groups", headers=a, json={"name": "Montaj", "member_ids": [b_id]}).json()["id"]
    m = _send(client, b, g, "uygunsuz")
    assert client.delete(f"/api/chat/messages/{m['id']}", headers=a).status_code == 200
    mine = _send(client, a, g, "yönetici yazdı")
    assert client.delete(f"/api/chat/messages/{mine['id']}", headers=b).status_code == 403


def test_forward_keeps_the_file_when_the_original_goes(client, pair, admin_headers):
    _, a, _, b, room = pair
    up = client.post(f"/api/chat/rooms/{room}/messages", headers=b, data={"body": "resim"},
                     files={"file": ("plan.pdf", b"%PDF-1.4 x", "application/pdf")}).json()
    target = client.post("/api/chat/direct", json={"user_id": 1}, headers=a).json()["id"]
    r = client.post("/api/chat/forward", headers=a, json={"message_ids": [up["id"]], "room_ids": [target]})
    assert r.status_code == 201 and r.json() == {"sent": 1}
    copy = list(_bodies(client, a, target).values())[-1]
    assert copy["forwarded_from"] == "chat_b" and copy["file"]["name"] == "plan.pdf"
    client.delete(f"/api/chat/messages/{up['id']}", headers=b)
    got = client.get(f"/api/chat/messages/{copy['id']}/file", headers=a)
    assert got.status_code == 200 and got.content == b"%PDF-1.4 x"
    assert client.patch(f"/api/chat/messages/{copy['id']}", headers=a, json={"body": "x"}).status_code == 400


def test_forward_needs_membership_on_both_sides(client, pair, admin_headers):
    _, a, _, b, room = pair
    _, c = _user(client, admin_headers, "chat_c")
    m = _send(client, a, room, "özel")
    mine = client.post("/api/chat/direct", json={"user_id": 1}, headers=c).json()["id"]
    r = client.post("/api/chat/forward", headers=c, json={"message_ids": [m["id"]], "room_ids": [mine]})
    assert r.status_code == 404
    r = client.post("/api/chat/forward", headers=c, json={"message_ids": [m["id"]], "room_ids": [room]})
    assert r.status_code == 404


def test_reaction_toggles_and_replaces(client, pair):
    _, a, _, b, room = pair
    m = _send(client, a, room, "tepki")
    url = f"/api/chat/messages/{m['id']}/reaction"
    assert client.put(url, headers=b, json={"emoji": "💣"}).status_code == 400
    assert client.put(url, headers=b, json={"emoji": "👍"}).json()["reactions"][0]["count"] == 1
    r = client.put(url, headers=a, json={"emoji": "👍"}).json()["reactions"][0]
    assert r["count"] == 2 and r["mine"]
    assert {x["emoji"] for x in client.put(url, headers=b, json={"emoji": "❤️"}).json()["reactions"]} == {"👍", "❤️"}
    assert client.put(url, headers=b, json={"emoji": "❤️"}).json()["reactions"][0]["count"] == 1


def test_pin_clears_when_the_message_goes(client, pair):
    a_id, a, b_id, b, room = pair
    m = _send(client, a, room, "sabit")
    assert client.post(f"/api/chat/rooms/{room}/pin", headers=b, json={"message_id": m["id"]}).json()["pinned"]["id"] == m["id"]
    client.delete(f"/api/chat/messages/{m['id']}", headers=a)
    rooms = {r["id"]: r for r in client.get("/api/chat/rooms", headers=a).json()}
    assert rooms[room]["pinned"] is None
    g = client.post("/api/chat/groups", headers=a, json={"name": "Sabit", "member_ids": [b_id]}).json()["id"]
    g1 = _send(client, a, g, "duyuru")
    assert client.post(f"/api/chat/rooms/{g}/pin", headers=b, json={"message_id": g1["id"]}).status_code == 403


def test_feed_starts_at_the_end_and_skips_what_was_read(client, pair):
    _, a, _, b, room = pair
    client.post(f"/api/chat/rooms/{room}/read", headers=b, json={"last_id": 10 ** 9})
    start = client.get("/api/notifications/feed", headers=b).json()
    assert start["messages"] == [] and start["last_id"] > 0
    m = _send(client, a, room, "gözüksün")
    got = client.get(f"/api/notifications/feed?after={start['last_id']}", headers=b).json()
    assert [(x["id"], x["title"], x["text"], x["link"]) for x in got["messages"]] == [
        (m["id"], "chat_a", "gözüksün", f"/chat?r={room}")]
    assert client.get(f"/api/notifications/feed?after={start['last_id']}", headers=a).json()["messages"] == []
    client.post(f"/api/chat/rooms/{room}/read", headers=b, json={"last_id": m["id"]})
    assert client.get(f"/api/notifications/feed?after={start['last_id']}", headers=b).json()["messages"] == []


def test_feed_without_chat_right_still_gives_the_bell(client, admin_headers):
    r = client.get("/api/notifications/feed?after=1", headers=admin_headers)
    assert r.status_code == 200 and "items" in r.json()
