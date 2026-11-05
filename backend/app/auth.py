"""Password hashing, JWT tokens and role checks."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import ROLE_ADMIN, ROLE_DESIGNER, ROLE_PLANNER, User
from .services.system import apply_runtime
from app.core.i18n import tx

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# The web session lives in an httpOnly cookie, out of reach of page scripts. A browser never lets plain http replace a
# Secure cookie, so http and https sessions have their own names: turning HTTPS off must not lock anyone out.
COOKIE_HTTP = "erp_session"
COOKIE_HTTPS = "erp_session_s"
# Unsafe requests must carry this header when they ride on the cookie. Another site cannot add it without a CORS
# grant, which this server never gives, and SameSite alone does not help: another port of the same host is same-site.
APP_HEADER = "x-requested-with"
APP_HEADER_VALUE = "LabERP"
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
TICKET_SECONDS = 120

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


def create_ticket(user: User, path: str) -> str:
    """A short token good for one API path. The native shells fetch files outside the web view, where the httpOnly
    cookie is out of their reach, and they get one of these per download."""
    exp = datetime.now(timezone.utc) + timedelta(seconds=TICKET_SECONDS)
    return jwt.encode({"sub": str(user.id), "tv": user.token_version or 0, "exp": exp, "p": path},
                      get_settings().jwt_secret, algorithm="HS256")


def _decode(token: str) -> tuple[int, int, str | None]:
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
        return int(payload["sub"]), int(payload.get("tv", 0)), payload.get("p")
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, tx("Oturum geçersiz veya süresi doldu"))


def user_from_token(token: str | None, db: Session) -> User:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, tx("Giriş yapılmadı"))
    apply_runtime(db)
    uid, tv, _ = _decode(token)
    user = db.get(User, uid)
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, tx("Kullanıcı bulunamadı veya pasif"))
    if tv != (user.token_version or 0):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, tx("Oturum sona erdi, tekrar giriş yapın"))
    return user


def is_https(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    return (forwarded or request.url.scheme) == "https"


def set_session(response: Response, request: Request, token: str) -> None:
    secure = is_https(request)
    response.set_cookie(COOKIE_HTTPS if secure else COOKIE_HTTP, token, max_age=get_settings().jwt_expire_hours * 3600,
                        path="/api", httponly=True, secure=secure, samesite="strict")


def clear_session(response: Response, request: Request) -> None:
    response.delete_cookie(COOKIE_HTTP, path="/api", httponly=True, samesite="strict")
    if is_https(request):
        response.delete_cookie(COOKIE_HTTPS, path="/api", httponly=True, secure=True, samesite="strict")


def session_token(request: Request, bearer: str | None = Depends(oauth2)) -> str | None:
    """The token of this request: a Bearer header (scripts, native shells) or the session cookie (web views)."""
    if bearer:
        bound = _decode(bearer)[2]
        if bound is not None and bound != request.url.path:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, tx("Bu bilet başka bir dosya için"))
        return bearer
    token = request.cookies.get(COOKIE_HTTPS) or request.cookies.get(COOKIE_HTTP)
    if token and request.method not in SAFE_METHODS and request.headers.get(APP_HEADER) != APP_HEADER_VALUE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, tx("İstek reddedildi"))
    return token


def current_user(token: str | None = Depends(session_token), db: Session = Depends(get_db)) -> User:
    return user_from_token(token, db)


def require_roles(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, tx("Bu işlem için yetkiniz yok"))
        return user
    return dep
