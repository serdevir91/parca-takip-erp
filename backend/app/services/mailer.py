"""Outgoing e-mail over SMTP. The admin enters the server in Yönetim > E-posta (settings key "smtp").

The password is stored encrypted in the settings table and never sent back to the browser. Sending is
synchronous with a short timeout; callers that must not wait (sign-up notices) run it in the
background.
"""
from __future__ import annotations

import logging
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Any

from sqlalchemy.orm import Session

from . import secretbox, system
from .settings import get_setting, set_setting
from app.core.i18n import tx

log = logging.getLogger("erp.mail")

EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
SECURITY = ("starttls", "ssl", "none")
TIMEOUT = 20


def valid_email(s: str) -> bool:
    return bool(EMAIL_RE.match(s)) and len(s) <= 200


@dataclass
class SmtpConfig:
    host: str = ""
    port: int = 587
    security: str = "starttls"
    username: str = ""
    password: str = ""
    from_addr: str = ""
    from_name: str = "LAB ERP"

    @property
    def ready(self) -> bool:
        return bool(self.host and self.from_addr)


def config(db: Session) -> SmtpConfig:
    v = get_setting(db, "smtp") or {}
    c = SmtpConfig()
    for k in c.__dataclass_fields__:
        if k in v and v[k] is not None:
            setattr(c, k, v[k])
    c.password = secretbox.open_(c.password)
    return c


def seal_stored(db: Session) -> None:
    """Encrypt a password saved in plain text by an older version."""
    v = get_setting(db, "smtp") or {}
    raw = v.get("password") or ""
    if raw and not secretbox.sealed(raw):
        set_setting(db, "smtp", {**v, "password": secretbox.seal(raw)})
        db.commit()


def public(c: SmtpConfig) -> dict[str, Any]:
    """Settings for the admin form: everything but the password."""
    return {"host": c.host, "port": c.port, "security": c.security, "username": c.username,
            "from_addr": c.from_addr, "from_name": c.from_name, "has_password": bool(c.password),
            "ready": c.ready}


def save(db: Session, body: dict[str, Any]) -> SmtpConfig:
    """Store new settings; an empty or missing password keeps the stored one."""
    old = config(db)
    c = SmtpConfig(host=str(body.get("host") or "").strip(), port=int(body.get("port") or 587),
                   security=str(body.get("security") or "starttls"),
                   username=str(body.get("username") or "").strip(),
                   password=str(body.get("password") or "") or old.password,
                   from_addr=str(body.get("from_addr") or "").strip(),
                   from_name=str(body.get("from_name") or "").strip() or system.app_name(db))
    if body.get("clear_password"):
        c.password = ""
    if c.security not in SECURITY:
        raise ValueError(tx("Güvenlik türü starttls, ssl veya none olmalı"))
    if not 1 <= c.port <= 65535:
        raise ValueError(tx("Port 1-65535 arasında olmalı"))
    if c.from_addr and not valid_email(c.from_addr):
        raise ValueError(tx("Gönderen adresi geçerli bir e-posta olmalı"))
    set_setting(db, "smtp", {**c.__dict__, "password": secretbox.seal(c.password)})
    return c


@dataclass
class Attachment:
    filename: str
    data: bytes
    content_type: str = "application/octet-stream"


def send(c: SmtpConfig, to: list[str], subject: str, body: str, attachments: list[Attachment] = (),
         reply_to: str = "", cc: list[str] = ()) -> None:
    """Send one message. Raises RuntimeError with a Turkish message the UI can show."""
    if not c.ready:
        raise RuntimeError(tx("E-posta sunucusu ayarlanmamış (Yönetim > E-posta)"))
    msg = EmailMessage()
    msg["From"] = formataddr((c.from_name, c.from_addr))
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=c.from_addr.split("@")[-1])
    msg.set_content(body or "")
    for a in attachments:
        main, _, sub = (a.content_type or "application/octet-stream").partition("/")
        msg.add_attachment(a.data, maintype=main or "application", subtype=sub or "octet-stream",
                           filename=a.filename)
    try:
        if c.security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(c.host, c.port, timeout=TIMEOUT,
                                                    context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(c.host, c.port, timeout=TIMEOUT)
        with server:
            if c.security == "starttls":
                server.starttls(context=ssl.create_default_context())
            if c.username:
                server.login(c.username, c.password)
            server.send_message(msg, to_addrs=[*to, *cc])
    except smtplib.SMTPAuthenticationError as e:
        raise RuntimeError(tx("E-posta sunucusu kullanıcı adı/şifreyi kabul etmedi. Gmail için uygulama şifresi kullanın.")) from e
    except smtplib.SMTPRecipientsRefused as e:
        raise RuntimeError(tx("Alıcı reddedildi: {0}", ', '.join(e.recipients))) from e
    except (OSError, smtplib.SMTPException) as e:
        log.warning("mail send failed: %s", e)
        raise RuntimeError(tx("E-posta gönderilemedi: {0}", e)) from e
