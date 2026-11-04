"""Login brute-force guard: failed attempts per user name + client IP and per client IP, kept in memory.

After `login_attempts` failures for one user name from one address (or IP_LIMIT from one address, or
USER_LIMIT_FACTOR times `login_attempts` for one user name from anywhere) within
`login_lock_minutes`, further attempts are refused until the oldest failure leaves the window. A successful login clears
the user name's failures. One process serves the whole LAN, so memory is enough; a restart resets it.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from ..config import get_settings

IP_LIMIT = 30
USER_LIMIT_FACTOR = 10  # above IP_LIMIT on default settings: one machine alone cannot lock a colleague out

_lock = threading.Lock()
_fails: dict[str, deque[float]] = defaultdict(deque)


def _window() -> int:
    return get_settings().login_lock_minutes * 60


def _trim(q: deque[float], now: float) -> None:
    while q and q[0] <= now - _window():
        q.popleft()


def _keys(username: str, ip: str) -> tuple[tuple[str, int], ...]:
    name, limit = username.lower(), get_settings().login_attempts
    return ((f"p:{name}|{ip}", limit), (f"i:{ip}", IP_LIMIT), (f"u:{name}", limit * USER_LIMIT_FACTOR))


def blocked_for(username: str, ip: str) -> int:
    """Seconds until another attempt is allowed; 0 when allowed now."""
    now = time.monotonic()
    wait = 0.0
    with _lock:
        for key, limit in _keys(username, ip):
            q = _fails.get(key)
            if not q:
                continue
            _trim(q, now)
            if len(q) >= limit:
                wait = max(wait, q[0] + _window() - now)
    return int(wait) + 1 if wait > 0 else 0


def failed(username: str, ip: str) -> None:
    now = time.monotonic()
    with _lock:
        for key, _ in _keys(username, ip):
            q = _fails[key]
            _trim(q, now)
            q.append(now)


def succeeded(username: str, ip: str) -> None:
    with _lock:
        _fails.pop(f"p:{username.lower()}|{ip}", None)


SIGNUP_WINDOW = 60 * 60
SIGNUP_LIMIT = 5


def signup_allowed(ip: str) -> bool:
    """At most SIGNUP_LIMIT sign-up requests per address per hour (counts the request)."""
    now = time.monotonic()
    with _lock:
        q = _fails[f"s:{ip}"]
        while q and q[0] <= now - SIGNUP_WINDOW:
            q.popleft()
        if len(q) >= SIGNUP_LIMIT:
            return False
        q.append(now)
        return True


def reset() -> None:
    with _lock:
        _fails.clear()
