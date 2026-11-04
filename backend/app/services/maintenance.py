"""A short stop for the whole API while a backup is restored: new requests get 503, running ones finish first."""
from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

_lock = threading.Lock()
_active = False
_running = 0


def enter() -> bool:
    """Count a request in. False while the API is stopped."""
    global _running
    with _lock:
        if _active:
            return False
        _running += 1
        return True


def leave() -> None:
    global _running
    with _lock:
        _running -= 1


@contextmanager
def exclusive(wait: float = 20) -> Iterator[None]:
    """Stop new requests and wait for the running ones, except the caller's own."""
    global _active
    with _lock:
        if _active:
            raise TimeoutError("Başka bir geri yükleme sürüyor")
        _active = True
    try:
        end = time.monotonic() + wait
        while True:
            with _lock:
                if _running <= 1:
                    break
            if time.monotonic() > end:
                raise TimeoutError("Devam eden işlemler bitmedi, biraz sonra tekrar deneyin")
            time.sleep(0.05)
        yield
    finally:
        with _lock:
            _active = False
