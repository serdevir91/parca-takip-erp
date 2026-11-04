"""Password hashing, JWT tokens and role checks."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import ROLE_ADMIN, ROLE_DESIGNER, ROLE_PLANNER, User
from .services.system import apply_runtime

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# Roles allowed to change tracking data (progress, notes, procurement)
EDIT_ROLES = (ROLE_ADMIN, ROLE_DESIGNER, ROLE_PLANNER)
# Roles allowed to upload/approve BOMs and drawings
DESIGN_ROLES = (ROLE_ADMIN, ROLE_DESIGNER)


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode()


# Checked when the user name is unknown, so a failed login takes as long either way
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password", bcrypt.gensalt()).decode()

def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8"), hashed.encode())
    except ValueError:
        return False


def dummy_verify(pw: str) -> None:
    verify_password(pw, _DUMMY_HASH)


def create_token(user: User) -> str:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(hours=s.jwt_expire_hours)
    return jwt.encode({"sub": str(user.id), "tv": user.token_version or 0, "exp": exp}, s.jwt_secret,
                      algorithm="HS256")


def _decode(token: str) -> tuple[int, int]:
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
        return int(payload["sub"]), int(payload.get("tv", 0))
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Oturum geçersiz veya süresi doldu")


def user_from_token(token: str | None, db: Session) -> User:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Giriş yapılmadı")
    apply_runtime(db)
    uid, tv = _decode(token)
    user = db.get(User, uid)
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Kullanıcı bulunamadı veya pasif")
    if tv != (user.token_version or 0):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Oturum sona erdi, tekrar giriş yapın")
    return user


def current_user(token: str | None = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    return user_from_token(token, db)


def require_roles(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Bu işlem için yetkiniz yok")
        return user
    return dep
