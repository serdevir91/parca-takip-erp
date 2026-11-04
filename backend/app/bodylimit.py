"""Request body limits, applied before anything parses the body.

FastAPI reads a body before it checks the login, so without this anyone on the network could send a huge JSON
document to any route and exhaust the server's memory. Without a valid token a body stays under OPEN_LIMIT
(login and sign-up are tiny). With one, JSON stays under JSON_LIMIT; file uploads spool to disk and each route
enforces its own size limit.
"""
from __future__ import annotations

from fastapi import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .auth import _decode

OPEN_LIMIT = 1 << 20
JSON_LIMIT = 64 << 20
_NO_LOGIN = (401, "Giriş yapılmadı")
_TOO_BIG = (413, "Gönderilen veri çok büyük")


def _logged_in(headers: dict[bytes, bytes]) -> bool:
    scheme, _, token = headers.get(b"authorization", b"").decode("latin-1").partition(" ")
    if scheme.lower() != "bearer" or not token:
        return False
    try:
        _decode(token.strip())
    except HTTPException:
        return False
    return True


class BodyLimit:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        limit, refusal = OPEN_LIMIT, _NO_LOGIN
        if _logged_in(headers):
            if headers.get(b"content-type", b"").lower().startswith(b"multipart/"):
                await self.app(scope, receive, send)
                return
            limit, refusal = JSON_LIMIT, _TOO_BIG
        length = headers.get(b"content-length", b"")
        if length.isdigit() and int(length) > limit:
            await JSONResponse({"detail": refusal[1]}, refusal[0])(scope, receive, send)
            return
        seen = 0

        async def counted() -> Message:  # a chunked body declares no length
            nonlocal seen
            message = await receive()
            seen += len(message.get("body", b""))
            if seen > limit:
                raise HTTPException(*refusal)
            return message

        await self.app(scope, counted, send)
