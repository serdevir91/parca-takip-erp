"""E-mail: SMTP settings (admin), sending lists and files from any screen, recipient suggestions."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Firm, User
from ..permissions import can, require
from ..services import audit, mailer, system
from .deps import admin, any_user, get_db
from app.core.i18n import tx

router = APIRouter(prefix="/mail", tags=["mail"])
mail_edit = require("mail", "edit")

MAX_RECIPIENTS = 20
MAX_BYTES = 20 * 1024 * 1024   # most providers refuse bigger messages
HOURLY_LIMIT = 60              # messages per user per hour

_lock = threading.Lock()
_sent: dict[int, deque[float]] = defaultdict(deque)


def _rate_ok(user_id: int) -> bool:
    now = time.monotonic()
    with _lock:
        q = _sent[user_id]
        while q and q[0] <= now - 3600:
            q.popleft()
        if len(q) >= HOURLY_LIMIT:
            return False
        q.append(now)
        return True


def _addresses(raw: str, what: str) -> list[str]:
    out: list[str] = []
    for a in (x.strip() for x in raw.replace(";", ",").replace("\n", ",").split(",")):
        if not a:
            continue
        if not mailer.valid_email(a):
            raise HTTPException(400, tx("{0} adresi geçersiz: {1}", what, a))
        if a.lower() not in (o.lower() for o in out):
            out.append(a)
    return out


@router.get("/status")
def status(_: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Whether "E-posta ile gönder" can work (the SMTP server is set up)."""
    return {"ready": mailer.config(db).ready}


@router.get("/recipients")
def recipients(user: User = Depends(mail_edit), db: Session = Depends(get_db)) -> list[dict[str, str]]:
    """Address suggestions: colleagues with an e-mail, plus firms when the user may see contacts."""
    out = [{"name": u.full_name or u.username, "email": u.email, "kind": "Kullanıcı"}
           for u in db.scalars(select(User).where(User.active.is_(True), User.email != "").order_by(User.full_name))]
    if can(user, "contacts"):
        out += [{"name": f.name, "email": f.email, "kind": "Firma"}
                for f in db.scalars(select(Firm).where(Firm.active.is_(True), Firm.email != "").order_by(Firm.name))]
    return [r for r in out if mailer.valid_email(r["email"])]


@router.post("/send")
async def send(to: str = Form(...), subject: str = Form(...), body: str = Form(""), cc: str = Form(""),
               files: list[UploadFile] = File(default=[]), user: User = Depends(mail_edit),
               db: Session = Depends(get_db)) -> dict[str, Any]:
    """Send a message with attachments (the lists the screen exported). Reply-To is the sender."""
    cfg = mailer.config(db)
    if not cfg.ready:
        raise HTTPException(400, tx("E-posta sunucusu ayarlanmamış. Yönetici Yönetim > E-posta ekranından ayarlamalı."))
    to_list, cc_list = _addresses(to, "Alıcı"), _addresses(cc, "Bilgi")
    if not to_list:
        raise HTTPException(400, tx("En az bir alıcı yazın"))
    if len(to_list) + len(cc_list) > MAX_RECIPIENTS:
        raise HTTPException(400, tx("En fazla {0} alıcı", MAX_RECIPIENTS))
    subject = subject.strip()[:200] or system.app_name(db)
    atts: list[mailer.Attachment] = []
    total = 0
    for f in files:
        data = await f.read(MAX_BYTES + 1)
        total += len(data)
        if total > MAX_BYTES:
            raise HTTPException(413, tx("Ekler en fazla 20 MB olabilir"))
        atts.append(mailer.Attachment(f.filename or "dosya", data, f.content_type or "application/octet-stream"))
    if not _rate_ok(user.id):
        raise HTTPException(429, tx("Saatte en fazla 60 e-posta gönderilebilir"))
    sender = user.full_name or user.username
    text = (body.strip() + "\n\n" if body.strip() else "") + f"-- \n{sender} tarafından {system.app_name(db)} ile gönderildi."
    try:
        mailer.send(cfg, to_list, subject, text, atts, reply_to=user.email or "", cc=cc_list)
    except RuntimeError as e:
        raise HTTPException(502, str(e)) from e
    audit.record(db, user, "mail", None, "to", None,
                 f"{', '.join(to_list + cc_list)} | {subject} | {', '.join(a.filename for a in atts)}"[:1000],
                 action="mail")
    db.commit()
    return {"ok": True, "to": to_list, "cc": cc_list}


# ---------- admin: SMTP server ----------
class SmtpIn(BaseModel):
    host: str = ""
    port: int = 587
    security: str = "starttls"
    username: str = ""
    password: str = ""          # empty keeps the stored one
    clear_password: bool = False
    from_addr: str = ""
    from_name: str = ""


@router.get("/settings")
def get_smtp(_: User = Depends(admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    return mailer.public(mailer.config(db))


@router.put("/settings")
def put_smtp(body: SmtpIn, me: User = Depends(admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    before = mailer.public(mailer.config(db))
    try:
        c = mailer.save(db, body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    after = mailer.public(c)
    if before != after:
        audit.record(db, me, "setting", "smtp", "smtp", f"{before['host']}:{before['port']}",
                     f"{after['host']}:{after['port']}")
    db.commit()
    return after


class TestIn(BaseModel):
    to: str = ""


@router.post("/test")
def test_smtp(body: TestIn, me: User = Depends(admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Send a test message to the given address (default: the admin's own e-mail)."""
    to = _addresses(body.to or me.email or "", "Alıcı")
    if not to:
        raise HTTPException(400, tx("Test için bir alıcı adresi yazın (veya Profilim'e e-posta ekleyin)"))
    try:
        mailer.send(mailer.config(db), to, tx("{0} test e-postası", system.app_name(db)),
                    tx("Bu bir test e-postasıdır. E-posta ayarlarınız çalışıyor."))
    except RuntimeError as e:
        raise HTTPException(502, str(e)) from e
    return {"ok": True, "to": to}
