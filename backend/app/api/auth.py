"""Login, current user and own password change."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import create_token, hash_password, verify_password
from ..models import ROLE_LABELS, User
from ..permissions import effective
from ..services import audit
from .deps import any_user, get_db


router = APIRouter(prefix="/auth", tags=["auth"])


def user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role,
            "role_label": ROLE_LABELS.get(u.role, u.role), "active": u.active, "permissions": effective(u)}


@router.post("/login")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> dict:
    u = db.scalar(select(User).where(User.username == form.username.strip()))
    if u is None or not u.active or not verify_password(form.password, u.password_hash):
        raise HTTPException(401, "Kullanıcı adı veya şifre hatalı")
    return {"access_token": create_token(u), "token_type": "bearer", "user": user_out(u)}


@router.get("/me")
def me(user: User = Depends(any_user)) -> dict:
    return user_out(user)


class PasswordChange(BaseModel):
    old_password: str
    new_password: str


@router.post("/password")
def change_password(body: PasswordChange, user: User = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(400, "Mevcut şifre hatalı")
    if len(body.new_password) < 6:
        raise HTTPException(400, "Yeni şifre en az 6 karakter olmalı")
    u = db.merge(user)
    u.password_hash = hash_password(body.new_password)
    audit.record(db, user, "user", u.id, "password", None, "değiştirildi")
    db.commit()
    return {"ok": True}
