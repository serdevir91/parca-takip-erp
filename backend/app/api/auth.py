"""Login, current user and own password change."""
from __future__ import annotations

import logging
import re
from functools import lru_cache

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import (clear_session, create_ticket, create_token, dummy_verify, hash_password, oauth2, session_token,
                    set_session, user_from_token, verify_password)
from ..config import get_settings
from ..db import SessionLocal
from ..models import ROLE_ADMIN, ROLE_LABELS, ROLE_VIEWER, User
from ..permissions import effective
from ..services import audit, loginguard, mailer, system
from ..services.settings import signup_enabled
from .deps import any_user, get_db
from app.core.i18n import tx

log = logging.getLogger("erp.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

USERNAME_RE = re.compile(r"^[\w.\-]{3,64}$")


def user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "email": u.email or "",
            "role": u.role, "role_label": ROLE_LABELS.get(u.role, u.role), "active": u.active,
            "permissions": effective(u)}


@lru_cache(maxsize=32)
def _is_default_password(password_hash: str) -> bool:
    return verify_password("admin", password_hash)


def session_out(u: User, db: Session) -> dict:
    """The signed-in user with the system settings; admins still on admin/admin get a warning on every page."""
    return {**user_out(u), "system": system.for_user(db),
            "default_password": u.role == ROLE_ADMIN and _is_default_password(u.password_hash)}


def check_email(email: str) -> str:
    email = (email or "").strip()
    if email and not mailer.valid_email(email):
        raise HTTPException(400, tx("E-posta adresi geçersiz"))
    return email


def check_password_rules(pw: str) -> None:
    least = get_settings().password_min_length
    if len(pw) < least:
        raise HTTPException(400, tx("Şifre en az {0} karakter olmalı", least))


@router.post("/login")
def login(request: Request, response: Response, form: OAuth2PasswordRequestForm = Depends(),
          db: Session = Depends(get_db)) -> dict:
    system.apply_runtime(db)
    name = form.username.strip()
    ip = request.client.host if request.client else "?"
    wait = loginguard.blocked_for(name, ip)
    if wait:
        raise HTTPException(429, tx("Çok fazla hatalı deneme. {0} dakika sonra tekrar deneyin.", max(1, round(wait / 60))),
                            headers={"Retry-After": str(wait)})
    u = db.scalar(select(User).where(User.username == name))
    if u is None:
        dummy_verify(form.password)
    if u is None or not verify_password(form.password, u.password_hash):
        loginguard.failed(name, ip)
        raise HTTPException(401, tx("Kullanıcı adı veya şifre hatalı"))
    # The password was right: say why the account cannot log in yet
    if u.pending:
        raise HTTPException(403, tx("Hesabınız yönetici onayı bekliyor. Onaylandığında giriş yapabilirsiniz."))
    if not u.active:
        raise HTTPException(403, tx("Hesabınız pasif. Yöneticinize başvurun."))
    loginguard.succeeded(name, ip)
    token = create_token(u)
    set_session(response, request, token)
    return {"access_token": token, "token_type": "bearer", "user": session_out(u, db)}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    clear_session(response, request)
    return {"ok": True}


@router.post("/session")
def adopt_session(request: Request, response: Response, bearer: str | None = Depends(oauth2),
                  db: Session = Depends(get_db)) -> dict:
    """One-time move of a token left in localStorage by a version before the session cookie."""
    token = session_token(request, bearer)
    if not bearer or token is None:
        raise HTTPException(401, tx("Giriş yapılmadı"))
    user_from_token(token, db)
    set_session(response, request, token)
    return {"ok": True}


class TicketIn(BaseModel):
    path: str = Field(min_length=2, max_length=1000, pattern=r"^/")


@router.post("/file-ticket")
def file_ticket(body: TicketIn, user: User = Depends(any_user)) -> dict:
    """Token for one file download by the desktop or Android shell. `path` is the API path without /api."""
    return {"token": create_ticket(user, "/api" + body.path.split("?", 1)[0])}


@router.get("/options")
def options(db: Session = Depends(get_db)) -> dict:
    """What the login screen offers (no login needed)."""
    system.apply_runtime(db)
    return {"signup": signup_enabled(db), **system.for_login(db)}


class SignupIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    full_name: str = Field(default="", max_length=128)
    email: str = Field(default="", max_length=200)
    password: str


def _notify_admins(user_id: int) -> None:
    """E-mail the admins that a sign-up waits for them (only when SMTP is set up)."""
    with SessionLocal() as db:
        cfg = mailer.config(db)
        u = db.get(User, user_id)
        if not cfg.ready or u is None:
            return
        to = [a.email for a in db.scalars(select(User).where(User.role == ROLE_ADMIN, User.active.is_(True)))
              if a.email]
        if not to:
            return
        body = (f"Yeni hesap isteği:\n\nKullanıcı adı: {u.username}\nAd soyad: {u.full_name or '-'}\n"
                f"E-posta: {u.email or '-'}\n\nOnaylamak için {system.app_name(db)} > Yönetim > Kullanıcılar.")
        try:
            mailer.send(cfg, to, tx("{0}: {1} hesap onayı bekliyor", system.app_name(db), u.username), body)
        except RuntimeError as e:
            log.warning("sign-up notice not sent: %s", e)


@router.post("/register", status_code=201)
def register(body: SignupIn, request: Request, background: BackgroundTasks,
             db: Session = Depends(get_db)) -> dict:
    """Self sign-up: the account waits (pending) until an admin approves it and sets the permissions."""
    if not signup_enabled(db):
        raise HTTPException(403, tx("Hesap oluşturma kapalı. Hesabı yöneticiniz açabilir."))
    username = body.username.strip()
    if not USERNAME_RE.match(username):
        raise HTTPException(400, tx("Kullanıcı adı 3-64 karakter olmalı; harf, rakam, nokta, tire ve alt çizgi kullanılabilir (boşluk yok)"))
    email = check_email(body.email)
    check_password_rules(body.password)
    ip = request.client.host if request.client else "?"
    if not loginguard.signup_allowed(ip):
        raise HTTPException(429, tx("Bu cihazdan çok fazla hesap isteği gönderildi. Bir saat sonra tekrar deneyin."))
    if db.scalar(select(User).where(func.lower(User.username) == username.lower())):
        raise HTTPException(409, tx("Bu kullanıcı adı alınmış, başka bir ad seçin"))
    u = User(username=username, full_name=body.full_name.strip(), email=email, role=ROLE_VIEWER,
             password_hash=hash_password(body.password), active=False, pending=True)
    db.add(u)
    db.flush()
    audit.record(db, u, "user", u.id, "username", None, username, action="signup")
    db.commit()
    background.add_task(_notify_admins, u.id)
    return {"ok": True, "message": tx("Hesap isteğiniz yöneticiye gönderildi. Onaylandığında giriş yapabilirsiniz.")}


@router.get("/me")
def me(user: User = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    return session_out(user, db)


class ProfileIn(BaseModel):
    full_name: str
    email: str | None = None


@router.put("/me")
def update_me(body: ProfileIn, user: User = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    """Own profile: display name (user name, role and permissions stay with the admin)."""
    name = body.full_name.strip()[:128]
    u = db.merge(user)
    if name != u.full_name:
        audit.record(db, user, "user", u.id, "full_name", u.full_name, name)
        u.full_name = name
    if body.email is not None:
        email = check_email(body.email)
        if email != (u.email or ""):
            audit.record(db, user, "user", u.id, "email", u.email, email)
            u.email = email
    db.commit()
    return user_out(u)


class PasswordChange(BaseModel):
    old_password: str
    new_password: str


@router.post("/password")
def change_password(body: PasswordChange, request: Request, response: Response, user: User = Depends(any_user),
                    db: Session = Depends(get_db)) -> dict:
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(400, tx("Mevcut şifre hatalı"))
    check_password_rules(body.new_password)
    if body.new_password == body.old_password:
        raise HTTPException(400, tx("Yeni şifre eskisiyle aynı olamaz"))
    u = db.merge(user)
    u.password_hash = hash_password(body.new_password)
    u.token_version = (u.token_version or 0) + 1  # other sessions of this user end
    audit.record(db, user, "user", u.id, "password", None, "değiştirildi")
    db.commit()
    token = create_token(u)
    set_session(response, request, token)
    return {"ok": True, "access_token": token, "user": user_out(u)}
