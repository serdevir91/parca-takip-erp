"""Login, current user and own password change."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import create_token, dummy_verify, hash_password, verify_password
from ..models import ROLE_LABELS, User
from ..permissions import effective
from ..services import audit, loginguard
from .deps import any_user, get_db


router = APIRouter(prefix="/auth", tags=["auth"])


def user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role,
            "role_label": ROLE_LABELS.get(u.role, u.role), "active": u.active, "permissions": effective(u)}

MIN_PASSWORD = 8


def check_password_rules(pw: str) -> None:
    if len(pw) < MIN_PASSWORD:
        raise HTTPException(400, f"Şifre en az {MIN_PASSWORD} karakter olmalı")


@router.post("/login")
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> dict:
    name = form.username.strip()
    ip = request.client.host if request.client else "?"
    wait = loginguard.blocked_for(name, ip)
    if wait:
        raise HTTPException(429, f"Çok fazla hatalı deneme. {max(1, round(wait / 60))} dakika sonra tekrar deneyin.",
                            headers={"Retry-After": str(wait)})
    u = db.scalar(select(User).where(User.username == name))
    if u is None:
        dummy_verify(form.password)
    if u is None or not u.active or not verify_password(form.password, u.password_hash):
        loginguard.failed(name, ip)
        raise HTTPException(401, "Kullanıcı adı veya şifre hatalı")
    loginguard.succeeded(name)
    return {"access_token": create_token(u), "token_type": "bearer", "user": user_out(u)}


@router.get("/me")
def me(user: User = Depends(any_user)) -> dict:
    return user_out(user)


class ProfileIn(BaseModel):
    full_name: str


@router.put("/me")
def update_me(body: ProfileIn, user: User = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    """Own profile: display name (user name, role and permissions stay with the admin)."""
    name = body.full_name.strip()[:128]
    u = db.merge(user)
    if name != u.full_name:
        audit.record(db, user, "user", u.id, "full_name", u.full_name, name)
        u.full_name = name
        db.commit()
    return user_out(u)


class PasswordChange(BaseModel):
    old_password: str
    new_password: str


@router.post("/password")
def change_password(body: PasswordChange, user: User = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(400, "Mevcut şifre hatalı")
    check_password_rules(body.new_password)
    if body.new_password == body.old_password:
        raise HTTPException(400, "Yeni şifre eskisiyle aynı olamaz")
    u = db.merge(user)
    u.password_hash = hash_password(body.new_password)
    u.token_version = (u.token_version or 0) + 1  # other sessions of this user end
    audit.record(db, user, "user", u.id, "password", None, "değiştirildi")
    db.commit()
    return {"ok": True, "access_token": create_token(u), "user": user_out(u)}
