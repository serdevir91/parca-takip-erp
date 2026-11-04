"""Live sync between computers: one counter (sync_state.rev) goes up after every successful write
request. Open screens poll GET /api/sync every few seconds and refetch when the number changes.
Stored in the database so it works with several uvicorn workers."""
from __future__ import annotations

import logging

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from ..models import SyncState, utcnow

log = logging.getLogger("erp.sync")
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# Writes that change nothing other screens show. Chat has its own lighter poll (GET /api/chat/state),
# so a message does not make every open screen refetch.
SKIP_PATHS = ("/api/auth/login", "/api/auth/password", "/api/fastener-rules/test", "/api/chat/", "/api/scan/resolve")


def bump(engine: Engine) -> None:
    try:
        with engine.begin() as c:
            if not c.execute(update(SyncState).where(SyncState.id == 1)
                             .values(rev=SyncState.rev + 1, updated_at=utcnow())).rowcount:
                c.execute(insert(SyncState).values(id=1, rev=1, updated_at=utcnow()))
    except Exception:  # noqa: BLE001 - sync is best effort, the write itself already succeeded
        log.exception("sync bump failed")


def current(engine: Engine) -> int:
    with engine.connect() as c:
        return c.scalar(select(SyncState.rev).where(SyncState.id == 1)) or 0


def counts(method: str, path: str, status: int) -> bool:
    return (method in WRITE_METHODS and status < 400 and path.startswith("/api/")
            and not path.startswith(SKIP_PATHS) and not path.endswith(("/preview", "/bom/draft")))
