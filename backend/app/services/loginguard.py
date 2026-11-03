"""Login brute-force guard: failed attempts per user name and per client IP, kept in memory.

After USER_LIMIT failures for one user name (or IP_LIMIT from one address) within WINDOW seconds,
further attempts are refused until the oldest failure leaves the window. A successful login clears
the user name's failures. One process serves the whole LAN, so memory is enough; a restart resets it.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

WINDOW = 15 * 60
USER_LIMIT = 5
IP_LIMIT = 30

_lock = threading.Lock()
_fails: dict[str, deque[float]] = defaultdict(deque)


def _trim(q: deque[float], now: float) -> None:
    while q and q[0] <= now - WINDOW:
        q.popleft()


def blocked_for(username: str, ip: str) -> int:
    """Seconds until another attempt is allowed; 0 when allowed now."""
    now = time.monotonic()
    wait = 0.0
    with _lock:
        for key, limit in ((f"u:{username.lower()}", USER_LIMIT), (f"i:{ip}", IP_LIMIT)):
            q = _fails.get(key)
            if not q:
                continue
            _trim(q, now)
            if len(q) >= limit:
                wait = max(wait, q[0] + WINDOW - now)
    return int(wait) + 1 if wait > 0 else 0


def failed(username: str, ip: str) -> None:
    now = time.monotonic()
    with _lock:
        for key in (f"u:{username.lower()}", f"i:{ip}"):
            q = _fails[key]
            _trim(q, now)
            q.append(now)


def succeeded(username: str) -> None:
    with _lock:
        _fails.pop(f"u:{username.lower()}", None)


def reset() -> None:
    with _lock:
        _fails.clear()
