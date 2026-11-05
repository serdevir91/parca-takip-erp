"""Chat: direct messages between two users and named groups, with one optional file per message.

Clients poll GET /chat/state (a few bytes) and refetch rooms/messages only when its `key` changes.
Chat writes are left out of the global live-sync counter (services/sync.SKIP_PATHS)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import session_token, user_from_token
from ..config import get_settings
from ..models import ChatMember, ChatMessage, ChatRoom, User, utcnow
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


def message_out(m: ChatMessage) -> dict[str, Any]:
    f = None
    if m.file_name and not m.deleted:
        f = {"name": m.file_name, "size": m.file_size or 0, "type": m.file_type or "",
             "image": uploads.ext_of(m.file_name) in uploads.PREVIEW_EXTS or m.thumb_path is not None}
    return {"id": m.id, "room_id": m.room_id, "user_id": m.user_id, "user_name": m.username, "kind": m.kind,
            "body": "" if m.deleted else m.body, "file": f, "deleted": m.deleted, "created_at": _iso(m.created_at)}


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
    last = db.scalar(select(ChatMessage).where(ChatMessage.room_id == room.id).order_by(ChatMessage.id.desc()).limit(1))
    preview = ""
    if last is not None:
        preview = "Mesaj silindi" if last.deleted else (last.body or (f"📎 {last.file_name}" if last.file_name else ""))
        if last.kind == "text" and room.kind == "group":
            preview = f"{'Siz' if last.user_id == me.id else last.username}: {preview}"
    return {"id": room.id, "kind": room.kind, "name": name, "is_admin": bool(mine and mine.is_admin),
            "members": [{"id": m.user_id, "name": display(m.user), "username": m.user.username if m.user else "",
                         "is_admin": m.is_admin, "active": bool(m.user and m.user.active)} for m in members],
            "last_message": preview[:120], "last_at": _iso(last.created_at if last else room.created_at),
            "last_id": last.id if last else 0, "unread": unread, "created_by": room.created_by}


def _unread_by_room(db: Session, me: User) -> dict[int, int]:
    rows = db.execute(
        select(ChatMessage.room_id, func.count())
        .join(ChatMember, (ChatMember.room_id == ChatMessage.room_id) & (ChatMember.user_id == me.id))
        .where(ChatMessage.id > ChatMember.last_read_id, ChatMessage.user_id != me.id, ChatMessage.kind == "text")
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
    q = select(ChatMessage).where(ChatMessage.room_id == room_id)
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
    return {"messages": [message_out(m) for m in rows], "more": more, "last_read_id": mine.last_read_id,
            # For "seen" ticks on my messages: everybody else has read up to this id
            "read_by_all": min(others) if others else 0}


@router.post("/rooms/{room_id}/messages", status_code=201)
async def send(room_id: int, body: str = Form(""), file: UploadFile | None = File(None),
               thumb: UploadFile | None = File(None), db: Session = Depends(get_db),
               me: User = Depends(chat_edit)) -> dict[str, Any]:
    mine = _member(db, room_id, me)
    text = body.strip()
    has_file = file is not None and bool(file.filename)
    if not text and not has_file:
        raise HTTPException(400, "Boş mesaj gönderilemez")
    if len(text) > 10000:
        raise HTTPException(400, "Mesaj çok uzun (en fazla 10.000 karakter)")
    msg = ChatMessage(room_id=room_id, user_id=me.id, username=display(me), body=text)
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
    return message_out(msg)


class ReadIn(BaseModel):
    last_id: int


@router.post("/rooms/{room_id}/read")
def mark_read(room_id: int, body: ReadIn, db: Session = Depends(get_db), me: User = Depends(chat_view)) -> dict:
    mine = _member(db, room_id, me)
    top = db.scalar(select(func.max(ChatMessage.id)).where(ChatMessage.room_id == room_id)) or 0
    mine.last_read_id = max(mine.last_read_id, min(body.last_id, top))
    db.commit()
    return {"last_read_id": mine.last_read_id}


@router.delete("/messages/{message_id}")
def delete_message(message_id: int, db: Session = Depends(get_db), me: User = Depends(chat_edit)) -> dict[str, Any]:
    msg = db.get(ChatMessage, message_id)
    if msg is None or msg.kind != "text":
        raise HTTPException(404, "Mesaj bulunamadı")
    _member(db, msg.room_id, me)
    if msg.user_id != me.id:
        raise HTTPException(403, "Yalnızca kendi mesajınızı silebilirsiniz")
    paths = (msg.file_path, msg.thumb_path)
    msg.deleted, msg.body, msg.file_path, msg.thumb_path = True, "", None, None
    db.get(ChatRoom, msg.room_id).updated_at = utcnow()   # changes everybody's /state key, so the deletion shows up
    db.commit()
    uploads.remove(*paths)
    return message_out(msg)


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
