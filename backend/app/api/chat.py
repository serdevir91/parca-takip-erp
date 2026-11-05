"""Chat: direct messages between two users and named groups, with one optional file per message.

Clients poll GET /chat/state (a few bytes) and refetch rooms/messages only when its `key` changes.
Chat writes are left out of the global live-sync counter (services/sync.SKIP_PATHS)."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import session_token, user_from_token
from ..config import get_settings
from ..models import ChatHidden, ChatMember, ChatMessage, ChatReaction, ChatRoom, User, utcnow
from ..permissions import can, require
from ..services import uploads
from .deps import get_db

router = APIRouter(prefix="/chat", tags=["chat"])

chat_view = require("chat", "view")
chat_edit = require("chat", "edit")
MAX_FILE_MB = 500
MAX_THUMB_MB = 2
# Files that run when opened; everything else (drawings, office files, archives) is fine to share
BLOCKED_EXT = {"exe", "msi", "bat", "cmd", "com", "scr", "pif", "ps1", "vbs", "vbe", "js", "jse", "wsf", "wsh",
               "hta", "lnk", "jar", "reg", "dll", "html", "htm", "xhtml", "svg", "shtml", "mht", "mhtml"}
PAGE = 60
EDIT_HOURS = 48
REACTIONS = ("👍", "❤️", "😂", "😮", "😢", "🙏")
FEED_LIMIT = 20


def display(u: User | None) -> str:
    return (u.full_name or u.username) if u else "Silinmiş kullanıcı"


def _iso(t: datetime | None) -> str | None:
    return t.isoformat() if t else None


def _member(db: Session, room_id: int, user: User) -> ChatMember:
    m = db.scalar(select(ChatMember).where(ChatMember.room_id == room_id, ChatMember.user_id == user.id))
    if m is None:
        raise HTTPException(404, "Sohbet bulunamadı")
    return m


def _active_user(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None or not u.active:
        raise HTTPException(404, "Kullanıcı bulunamadı veya pasif")
    if not can(u, "chat", "view"):
        raise HTTPException(400, f"{display(u)} sohbet modülünü kullanamıyor")
    return u


def _hidden(me: User) -> Any:
    """Ids of the messages this user deleted for themself."""
    return select(ChatHidden.message_id).where(ChatHidden.user_id == me.id)


def _summary(m: ChatMessage) -> str:
    return m.body or (f"📎 {m.file_name}" if m.file_name else "")


def _quote(m: ChatMessage | None) -> dict[str, Any] | None:
    """The short form shown above a reply and in the pinned bar."""
    if m is None:
        return None
    return {"id": m.id, "user_name": m.username, "deleted": m.deleted, "text": "" if m.deleted else _summary(m)[:200]}


def message_out(m: ChatMessage, reply: ChatMessage | None = None,
                reactions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    f = None
    if m.file_name and not m.deleted:
        f = {"name": m.file_name, "size": m.file_size or 0, "type": m.file_type or "",
             "image": uploads.ext_of(m.file_name) in uploads.PREVIEW_EXTS or m.thumb_path is not None}
    return {"id": m.id, "room_id": m.room_id, "user_id": m.user_id, "user_name": m.username, "kind": m.kind,
            "body": "" if m.deleted else m.body, "file": f, "deleted": m.deleted, "created_at": _iso(m.created_at),
            "edited_at": None if m.deleted else _iso(m.edited_at), "reply_to": _quote(reply),
            "forwarded_from": None if m.deleted else m.forwarded_from,
            "reactions": [] if m.deleted else reactions or []}


def messages_out(db: Session, rows: list[ChatMessage], me: User) -> list[dict[str, Any]]:
    """Messages with their quotes and reactions, two queries for the whole page."""
    ids = {m.reply_to_id for m in rows if m.reply_to_id}
    quoted = {m.id: m for m in db.scalars(select(ChatMessage).where(ChatMessage.id.in_(ids)))} if ids else {}
    marks: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    for r, u in db.execute(select(ChatReaction, User).outerjoin(User, User.id == ChatReaction.user_id)
                           .where(ChatReaction.message_id.in_([m.id for m in rows])).order_by(ChatReaction.id)):
        one = marks[r.message_id].setdefault(r.emoji, {"emoji": r.emoji, "count": 0, "mine": False, "names": []})
        one["count"] += 1
        one["mine"] = one["mine"] or r.user_id == me.id
        one["names"].append(display(u))
    return [message_out(m, quoted.get(m.reply_to_id or 0), list(marks[m.id].values())) for m in rows]


def _one(db: Session, m: ChatMessage, me: User) -> dict[str, Any]:
    return messages_out(db, [m], me)[0]


def _touch(db: Session, room_id: int) -> None:
    """Changes everybody's /state key, so an edit, a deletion or a reaction shows up."""
    db.get(ChatRoom, room_id).updated_at = utcnow()


def _text_message(db: Session, message_id: int) -> ChatMessage:
    msg = db.get(ChatMessage, message_id)
    if msg is None or msg.kind != "text":
        raise HTTPException(404, "Mesaj bulunamadı")
    return msg


def _system(db: Session, room: ChatRoom, user: User, text: str) -> ChatMessage:
    msg = ChatMessage(room_id=room.id, user_id=user.id, username=display(user), kind="system", body=text)
    db.add(msg)
    room.updated_at = utcnow()
    db.flush()
    return msg


def room_out(db: Session, room: ChatRoom, me: User, unread: int = 0) -> dict[str, Any]:
    members = sorted(room.members, key=lambda m: (m.user_id != me.id, display(m.user).casefold()))
    mine = next((m for m in members if m.user_id == me.id), None)
    others = [m for m in members if m.user_id != me.id]
    name = room.name if room.kind == "group" else (display(others[0].user) if others else "Ben")
    last = db.scalar(select(ChatMessage).where(ChatMessage.room_id == room.id, ChatMessage.id.not_in(_hidden(me)))
                     .order_by(ChatMessage.id.desc()).limit(1))
    pinned = db.get(ChatMessage, room.pinned_id) if room.pinned_id else None
    preview = ""
    if last is not None:
        preview = "Mesaj silindi" if last.deleted else _summary(last)
        if last.kind == "text" and room.kind == "group":
            preview = f"{'Siz' if last.user_id == me.id else last.username}: {preview}"
    return {"id": room.id, "kind": room.kind, "name": name, "is_admin": bool(mine and mine.is_admin),
            "members": [{"id": m.user_id, "name": display(m.user), "username": m.user.username if m.user else "",
                         "is_admin": m.is_admin, "active": bool(m.user and m.user.active)} for m in members],
            "last_message": preview[:120], "last_at": _iso(last.created_at if last else room.created_at),
            "last_id": last.id if last else 0, "unread": unread, "created_by": room.created_by,
            "pinned": _quote(pinned)}


def _unread_by_room(db: Session, me: User) -> dict[int, int]:
    rows = db.execute(
        select(ChatMessage.room_id, func.count())
        .join(ChatMember, (ChatMember.room_id == ChatMessage.room_id) & (ChatMember.user_id == me.id))
        .where(ChatMessage.id > ChatMember.last_read_id, ChatMessage.user_id != me.id, ChatMessage.kind == "text",
               ChatMessage.deleted.is_(False), ChatMessage.id.not_in(_hidden(me)))
        .group_by(ChatMessage.room_id)).all()
    return {r: n for r, n in rows}


# ---------- polling ----------
@router.get("/state")
def state(db: Session = Depends(get_db), me: User = Depends(chat_view)) -> dict[str, Any]:
    """Cheap poll: `key` changes when a message arrives in any of my rooms, my room list changes, a message is
    deleted or a room is edited (rooms.updated_at), or somebody reads further (sum of read markers)."""
    room_ids = select(ChatMember.room_id).where(ChatMember.user_id == me.id)
    n_rooms = db.scalar(select(func.count()).select_from(room_ids.subquery())) or 0
    last_id = db.scalar(select(func.max(ChatMessage.id)).where(ChatMessage.room_id.in_(room_ids))) or 0
    touched = db.scalar(select(func.max(ChatRoom.updated_at)).where(ChatRoom.id.in_(room_ids)))
    reads = db.scalar(select(func.sum(ChatMember.last_read_id)).where(ChatMember.room_id.in_(room_ids))) or 0
    unread = _unread_by_room(db, me)
    return {"key": f"{last_id}:{n_rooms}:{_iso(touched) or ''}:{reads}", "unread": sum(unread.values()),
            "last_id": last_id}


def feed(db: Session, me: User, after: int) -> dict[str, Any]:
    """New messages for the desktop and phone notifications. after=0 answers only where the end is, so a device
    that starts up does not announce the whole history. What was read on another device is left out."""
    rooms = select(ChatMember.room_id).where(ChatMember.user_id == me.id)
    last_id = db.scalar(select(func.max(ChatMessage.id)).where(ChatMessage.room_id.in_(rooms))) or 0
    if after <= 0:
        return {"last_id": last_id, "messages": []}
    rows = db.execute(
        select(ChatMessage, ChatRoom)
        .join(ChatRoom, ChatRoom.id == ChatMessage.room_id)
        .join(ChatMember, (ChatMember.room_id == ChatMessage.room_id) & (ChatMember.user_id == me.id))
        .where(ChatMessage.id > after, ChatMessage.id > ChatMember.last_read_id, ChatMessage.user_id != me.id,
               ChatMessage.kind == "text", ChatMessage.deleted.is_(False), ChatMessage.id.not_in(_hidden(me)))
        .order_by(ChatMessage.id.desc()).limit(FEED_LIMIT)).all()
    return {"last_id": last_id, "messages": [
        {"id": m.id, "room_id": m.room_id, "link": f"/chat?r={m.room_id}", "text": _summary(m)[:200],
         "title": f"{m.username} · {r.name}" if r.kind == "group" else m.username}
        for m, r in reversed(rows)]}


@router.get("/users")
def users(db: Session = Depends(get_db), me: User = Depends(chat_view)) -> list[dict[str, Any]]:
    """Active users that can be messaged (people without chat access are left out)."""
    rows = db.scalars(select(User).where(User.active.is_(True), User.id != me.id)).all()
    return sorted(({"id": u.id, "name": display(u), "username": u.username} for u in rows if can(u, "chat", "view")),
                  key=lambda r: r["name"].casefold())


# ---------- rooms ----------
@router.get("/rooms")
def rooms(db: Session = Depends(get_db), me: User = Depends(chat_view)) -> list[dict[str, Any]]:
    unread = _unread_by_room(db, me)
    rs = db.scalars(select(ChatRoom).join(ChatMember).where(ChatMember.user_id == me.id)
                    .order_by(ChatRoom.updated_at.desc())).all()
    return [room_out(db, r, me, unread.get(r.id, 0)) for r in rs]


class DirectIn(BaseModel):
    user_id: int


@router.post("/direct")
def direct(body: DirectIn, db: Session = Depends(get_db), me: User = Depends(chat_edit)) -> dict[str, Any]:
    """Open (or create) the one-to-one conversation with a user."""
    if body.user_id == me.id:
        raise HTTPException(400, "Kendinize mesaj gönderemezsiniz")
    other = _active_user(db, body.user_id)
    if not can(other, "chat", "view"):
        raise HTTPException(400, f"{display(other)} sohbet modülünü kullanamıyor")
    key = f"{min(me.id, other.id)}:{max(me.id, other.id)}"
    room = db.scalar(select(ChatRoom).where(ChatRoom.dm_key == key))
    if room is None:
        room = ChatRoom(kind="direct", dm_key=key, created_by=me.username)
        room.members = [ChatMember(user_id=me.id), ChatMember(user_id=other.id)]
        db.add(room)
        db.commit()
    return room_out(db, room, me)


class GroupIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    member_ids: list[int] = Field(default_factory=list)


@router.post("/groups", status_code=201)
def create_group(body: GroupIn, db: Session = Depends(get_db), me: User = Depends(chat_edit)) -> dict[str, Any]:
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Grup adı boş olamaz")
    ids = [i for i in dict.fromkeys(body.member_ids) if i != me.id]
    if not ids:
        raise HTTPException(400, "Gruba en az bir kişi ekleyin")
    added = [_active_user(db, i) for i in ids]
    room = ChatRoom(kind="group", name=name, created_by=me.username)
    room.members = [ChatMember(user_id=me.id, is_admin=True)] + [ChatMember(user_id=u.id) for u in added]
    db.add(room)
    db.flush()
    _system(db, room, me, f"{display(me)} “{name}” grubunu oluşturdu")
    db.commit()
    return room_out(db, room, me)


class GroupPatch(BaseModel):
    name: str | None = Field(None, max_length=120)
    add: list[int] = Field(default_factory=list)
    remove: list[int] = Field(default_factory=list)
    admins: list[int] | None = None   # full list of group admins (me included or not)


@router.patch("/rooms/{room_id}")
def edit_group(room_id: int, body: GroupPatch, db: Session = Depends(get_db),
               me: User = Depends(chat_edit)) -> dict[str, Any]:
    mine = _member(db, room_id, me)
    room = mine.room
    if room.kind != "group":
        raise HTTPException(400, "Birebir sohbet düzenlenemez")
    if not mine.is_admin:
        raise HTTPException(403, "Grubu yalnızca grup yöneticileri düzenleyebilir")
    if body.name is not None and body.name.strip() and body.name.strip() != room.name:
        room.name = body.name.strip()
        _system(db, room, me, f"{display(me)} grubun adını “{room.name}” yaptı")
    current = {m.user_id: m for m in room.members}
    for uid in dict.fromkeys(body.add):
        if uid not in current:
            u = _active_user(db, uid)
            m = ChatMember(user_id=u.id)
            room.members.append(m)
            current[uid] = m
            # New members start at the current end: they see the history but get no unread backlog
            m.last_read_id = db.scalar(select(func.max(ChatMessage.id)).where(ChatMessage.room_id == room.id)) or 0
            _system(db, room, me, f"{display(me)}, {display(u)} kişisini ekledi")
    for uid in dict.fromkeys(body.remove):
        if uid == me.id:
            raise HTTPException(400, "Kendinizi çıkarmak için “Gruptan ayrıl” kullanın")
        m = current.pop(uid, None)
        if m is not None:
            name = display(m.user)
            room.members.remove(m)
            _system(db, room, me, f"{display(me)}, {name} kişisini çıkardı")
    if body.admins is not None:
        wanted = set(body.admins) | {me.id}
        for uid, m in current.items():
            m.is_admin = uid in wanted
    db.commit()
    return room_out(db, room, me)


@router.post("/rooms/{room_id}/leave")
def leave(room_id: int, db: Session = Depends(get_db), me: User = Depends(chat_view)) -> dict[str, Any]:
    mine = _member(db, room_id, me)
    room = mine.room
    if room.kind != "group":
        raise HTTPException(400, "Birebir sohbetten ayrılınamaz")
    room.members.remove(mine)
    db.flush()
    if room.members and not any(m.is_admin for m in room.members):
        min(room.members, key=lambda m: m.id).is_admin = True   # the longest-standing member takes over
    _system(db, room, me, f"{display(me)} gruptan ayrıldı")
    db.commit()
    return {"ok": True}


# ---------- messages ----------
@router.get("/rooms/{room_id}/messages")
def messages(room_id: int, after: int | None = None, before: int | None = None, limit: int = PAGE,
             db: Session = Depends(get_db), me: User = Depends(chat_view)) -> dict[str, Any]:
    mine = _member(db, room_id, me)
    q = select(ChatMessage).where(ChatMessage.room_id == room_id, ChatMessage.id.not_in(_hidden(me)))
    limit = max(1, min(limit, 200))
    if after is not None:
        rows = db.scalars(q.where(ChatMessage.id > after).order_by(ChatMessage.id).limit(500)).all()
        more = False
    else:
        if before is not None:
            q = q.where(ChatMessage.id < before)
        rows = list(reversed(db.scalars(q.order_by(ChatMessage.id.desc()).limit(limit + 1)).all()))
        more = len(rows) > limit
        rows = rows[-limit:]
    others = [m.last_read_id for m in mine.room.members if m.user_id != me.id]
    return {"messages": messages_out(db, list(rows), me), "more": more, "last_read_id": mine.last_read_id,
            # For "seen" ticks on my messages: everybody else has read up to this id
            "read_by_all": min(others) if others else 0}


@router.post("/rooms/{room_id}/messages", status_code=201)
async def send(room_id: int, body: str = Form(""), reply_to: int | None = Form(None),
               file: UploadFile | None = File(None), thumb: UploadFile | None = File(None), db: Session = Depends(get_db),
               me: User = Depends(chat_edit)) -> dict[str, Any]:
    mine = _member(db, room_id, me)
    text = body.strip()
    has_file = file is not None and bool(file.filename)
    if not text and not has_file:
        raise HTTPException(400, "Boş mesaj gönderilemez")
    if len(text) > 10000:
        raise HTTPException(400, "Mesaj çok uzun (en fazla 10.000 karakter)")
    if reply_to is not None:
        quoted = db.get(ChatMessage, reply_to)
        if quoted is None or quoted.room_id != room_id or quoted.kind != "text":
            raise HTTPException(400, "Yanıtlanan mesaj bu sohbette yok")
    msg = ChatMessage(room_id=room_id, user_id=me.id, username=display(me), body=text, reply_to_id=reply_to)
    if has_file:
        assert file is not None
        if uploads.ext_of(uploads.safe_name(file.filename)) in BLOCKED_EXT:
            raise HTTPException(415, "Bu dosya türü sohbette paylaşılamaz (program veya web sayfası). "
                                     "Gerekirse sıkıştırıp gönderin.")
        folder = get_settings().chat_dir / str(room_id)
        try:
            path, size = await uploads.store(file, folder, MAX_FILE_MB)
            if thumb is not None and thumb.filename:
                thumb.filename = "t.jpg"
                msg.thumb_path = str((await uploads.store(thumb, folder / "thumbs", MAX_THUMB_MB))[0])
        except uploads.UploadTooLarge as e:
            raise HTTPException(413, str(e)) from e
        msg.file_name = uploads.safe_name(file.filename)
        msg.file_size, msg.file_type, msg.file_path = size, file.content_type or "", str(path)
    db.add(msg)
    mine.room.updated_at = utcnow()
    db.flush()
    mine.last_read_id = msg.id
    db.commit()
    return _one(db, msg, me)


class ReadIn(BaseModel):
    last_id: int


@router.post("/rooms/{room_id}/read")
def mark_read(room_id: int, body: ReadIn, db: Session = Depends(get_db), me: User = Depends(chat_view)) -> dict:
    mine = _member(db, room_id, me)
    top = db.scalar(select(func.max(ChatMessage.id)).where(ChatMessage.room_id == room_id)) or 0
    mine.last_read_id = max(mine.last_read_id, min(body.last_id, top))
    db.commit()
    return {"last_read_id": mine.last_read_id}


class EditIn(BaseModel):
    body: str = Field(max_length=10000)


@router.patch("/messages/{message_id}")
def edit_message(message_id: int, body: EditIn, db: Session = Depends(get_db),
                 me: User = Depends(chat_edit)) -> dict[str, Any]:
    msg = _text_message(db, message_id)
    _member(db, msg.room_id, me)
    if msg.user_id != me.id:
        raise HTTPException(403, "Yalnızca kendi mesajınızı düzenleyebilirsiniz")
    if msg.deleted:
        raise HTTPException(400, "Silinmiş mesaj düzenlenemez")
    if msg.forwarded_from:
        raise HTTPException(400, "İletilen mesaj düzenlenemez")
    if utcnow() - msg.created_at > timedelta(hours=EDIT_HOURS):
        raise HTTPException(400, f"Mesaj yalnızca ilk {EDIT_HOURS} saat içinde düzenlenebilir")
    text = body.body.strip()
    if not text and not msg.file_name:
        raise HTTPException(400, "Boş mesaj gönderilemez")
    if text != msg.body:
        msg.body, msg.edited_at = text, utcnow()
        _touch(db, msg.room_id)
        db.commit()
    return _one(db, msg, me)


@router.delete("/messages/{message_id}")
def delete_message(message_id: int, scope: str = Query("all", pattern="^(all|me)$"), db: Session = Depends(get_db),
                   me: User = Depends(chat_view)) -> dict[str, Any]:
    """scope=me hides the message from this user only. scope=all deletes it for everybody: the author, or a group
    admin for anyone's message. The row stays as "Bu mesaj silindi", the file goes."""
    msg = _text_message(db, message_id)
    mine = _member(db, msg.room_id, me)
    if scope == "me":
        if db.scalar(select(ChatHidden).where(ChatHidden.message_id == msg.id, ChatHidden.user_id == me.id)) is None:
            db.add(ChatHidden(message_id=msg.id, user_id=me.id))
            db.commit()
        return _one(db, msg, me)
    if not can(me, "chat", "edit"):
        raise HTTPException(403, "Bu işlem için yetkiniz yok")
    if msg.user_id != me.id and not (mine.room.kind == "group" and mine.is_admin):
        raise HTTPException(403, "Yalnızca kendi mesajınızı silebilirsiniz")
    paths = (msg.file_path, msg.thumb_path)
    msg.deleted, msg.body, msg.file_path, msg.thumb_path = True, "", None, None
    if mine.room.pinned_id == msg.id:
        mine.room.pinned_id = None
    _touch(db, msg.room_id)
    db.commit()
    uploads.remove(*paths)
    return _one(db, msg, me)


class ForwardIn(BaseModel):
    message_ids: list[int] = Field(min_length=1, max_length=50)
    room_ids: list[int] = Field(min_length=1, max_length=20)


@router.post("/forward", status_code=201)
def forward(body: ForwardIn, db: Session = Depends(get_db), me: User = Depends(chat_edit)) -> dict[str, int]:
    """Copies messages into other rooms, oldest first. A copy has its own file, so deleting the original leaves it."""
    sources = []
    for mid in sorted(set(body.message_ids)):
        msg = _text_message(db, mid)
        _member(db, msg.room_id, me)
        if msg.deleted:
            raise HTTPException(400, "Silinmiş mesaj iletilemez")
        sources.append(msg)
    targets = [_member(db, rid, me) for rid in dict.fromkeys(body.room_ids)]
    sent = 0
    for mine in targets:
        folder = get_settings().chat_dir / str(mine.room_id)
        for src in sources:
            copy = ChatMessage(room_id=mine.room_id, user_id=me.id, username=display(me), body=src.body,
                               forwarded_from=src.forwarded_from or src.username)
            if src.file_path:
                try:
                    copy.file_path = str(uploads.clone(src.file_path, folder))
                    if src.thumb_path:
                        copy.thumb_path = str(uploads.clone(src.thumb_path, folder / "thumbs"))
                except OSError as e:
                    raise HTTPException(404, f"{src.file_name}: dosya kopyalanamadı") from e
                copy.file_name, copy.file_size, copy.file_type = src.file_name, src.file_size, src.file_type
            db.add(copy)
            db.flush()
            mine.last_read_id = copy.id
            sent += 1
        mine.room.updated_at = utcnow()
    db.commit()
    return {"sent": sent}


class ReactIn(BaseModel):
    emoji: str = ""


@router.put("/messages/{message_id}/reaction")
def react(message_id: int, body: ReactIn, db: Session = Depends(get_db), me: User = Depends(chat_edit)) -> dict[str, Any]:
    """The same emoji again, or an empty one, takes the reaction back."""
    if body.emoji and body.emoji not in REACTIONS:
        raise HTTPException(400, "Bu tepki kullanılamıyor")
    msg = _text_message(db, message_id)
    _member(db, msg.room_id, me)
    if msg.deleted:
        raise HTTPException(400, "Silinmiş mesaja tepki verilemez")
    row = db.scalar(select(ChatReaction).where(ChatReaction.message_id == msg.id, ChatReaction.user_id == me.id))
    if row is not None and (not body.emoji or row.emoji == body.emoji):
        db.delete(row)
    elif row is not None:
        row.emoji = body.emoji
    elif body.emoji:
        db.add(ChatReaction(message_id=msg.id, user_id=me.id, emoji=body.emoji))
    _touch(db, msg.room_id)
    db.commit()
    return _one(db, msg, me)


class PinIn(BaseModel):
    message_id: int | None = None


@router.post("/rooms/{room_id}/pin")
def pin(room_id: int, body: PinIn, db: Session = Depends(get_db), me: User = Depends(chat_edit)) -> dict[str, Any]:
    """One pinned message per room. In a group only its admins pin."""
    mine = _member(db, room_id, me)
    if mine.room.kind == "group" and not mine.is_admin:
        raise HTTPException(403, "Grupta mesajı yalnızca yöneticiler sabitler")
    if body.message_id is not None:
        msg = _text_message(db, body.message_id)
        if msg.room_id != room_id or msg.deleted:
            raise HTTPException(400, "Bu mesaj sabitlenemez")
    mine.room.pinned_id = body.message_id
    mine.room.updated_at = utcnow()
    db.commit()
    return room_out(db, mine.room, me)


def _file_user(token: str | None = Depends(session_token), db: Session = Depends(get_db)) -> User:
    user = user_from_token(token, db)
    if not can(user, "chat", "view"):
        raise HTTPException(403, "Bu işlem için yetkiniz yok")
    return user


def _attachment(db: Session, message_id: int, me: User) -> ChatMessage:
    msg = db.get(ChatMessage, message_id)
    if msg is None or msg.deleted or not msg.file_path:
        raise HTTPException(404, "Dosya bulunamadı")
    _member(db, msg.room_id, me)
    return msg


@router.get("/messages/{message_id}/file")
def message_file(message_id: int, download: bool = False, db: Session = Depends(get_db),
                 me: User = Depends(_file_user)) -> FileResponse:
    msg = _attachment(db, message_id, me)
    if not Path(msg.file_path or "").is_file():
        raise HTTPException(404, "Dosya bulunamadı")
    media, inline = uploads.media_for(msg.file_name or "")
    return FileResponse(msg.file_path or "", media_type=media, filename=msg.file_name,
                        content_disposition_type="inline" if inline and not download else "attachment")


@router.get("/messages/{message_id}/thumb")
def message_thumb(message_id: int, db: Session = Depends(get_db), me: User = Depends(_file_user)) -> FileResponse:
    msg = _attachment(db, message_id, me)
    path = msg.thumb_path if msg.thumb_path and Path(msg.thumb_path).is_file() else msg.file_path
    if not path or not Path(path).is_file():
        raise HTTPException(404, "Dosya bulunamadı")
    media = "image/jpeg" if path == msg.thumb_path else uploads.media_for(msg.file_name or "")[0]
    return FileResponse(path, media_type=media,
                        headers={"Cache-Control": "private, max-age=86400"})
