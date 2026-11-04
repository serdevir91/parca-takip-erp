"""Encrypts secrets kept in the database, so a stolen database file or backup does not give them away.

The key comes from the JWT secret, which lives in data_dir/.jwt_secret (or the environment) and is left out
of backups. A database restored on another server therefore cannot open these values: open_() returns ""
and the admin types the secret once more."""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from ..config import get_settings

PREFIX = "enc1:"


def _fernet() -> Fernet:
    digest = hashlib.sha256(b"lab-erp-secretbox:" + get_settings().jwt_secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def sealed(value: str) -> bool:
    return value.startswith(PREFIX)


def seal(value: str) -> str:
    return PREFIX + _fernet().encrypt(value.encode()).decode() if value else ""


def open_(value: str) -> str:
    """The plain text. Values stored before encryption came in pass through unchanged."""
    if not sealed(value):
        return value
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken:
        return ""
