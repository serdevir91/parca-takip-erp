"""Exchange rates (döviz kuru).

A rate is the value of one unit of a currency in the base currency (setting commerce.currency), so
amount * rate = base amount. The base currency itself is always 1. Most sites run on an offline LAN: rates can
be typed by hand and nothing here needs the internet. The Merkez Bankası bulletin is an optional convenience.

Rates in `exchange_rates` are in the base currency that was set when they were written, like the `rate` fixed on
a document: changing commerce.currency later does not restate them.
Like `erp`, these functions do not commit; the caller commits.
"""
from __future__ import annotations

import http.client
import re
import time
import urllib.error
import urllib.request
from bisect import bisect_right
from datetime import date, datetime
from typing import Any

from defusedxml import ElementTree
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..models import ExchangeRate, SyncState, User
from . import audit, system

TCMB_URL = "https://www.tcmb.gov.tr/kurlar/today.xml"
FETCH_TIMEOUT = 10          # seconds, for the whole download
FETCH_MAX_BYTES = 1 << 20
SOURCES = {"tcmb": "Merkez Bankası", "manual": "Elle girildi"}
_OFFLINE = "Merkez Bankası kurlarına ulaşılamadı. Sunucunun internet bağlantısı yoksa kurları elle girin."
_BAD_REPLY = "Merkez Bankası yanıtı okunamadı. Kurları elle girebilirsiniz."


class RateFetchError(Exception):
    """A fetch that did not work; the text is shown to the user."""


def base_currency(db: Session) -> str:
    return system.system(db)["commerce"]["currency"]


def norm(currency: str | None) -> str:
    return (currency or "").strip().upper()


def clean_currency(currency: str | None) -> str:
    """Currency of a new or edited document, or 400."""
    cur = norm(currency)
    if not re.fullmatch(r"[A-Z]{3}", cur):
        raise HTTPException(400, "Para birimi TRY, EUR, USD gibi üç harfli kod olmalı")
    return cur


def first_day(*days: date | datetime | None) -> date:
    """The first of the given dates that is set (document date, then creation date), else today."""
    for d in days:
        if isinstance(d, datetime):
            return d.date()
        if d is not None:
            return d
    return date.today()


def rate_on(db: Session, currency: str | None, day: date | None = None) -> float | None:
    """Latest rate on or before the day. The base currency is 1, None if unknown."""
    cur = norm(currency)
    if not cur or cur == base_currency(db):
        return 1.0
    return db.scalar(select(ExchangeRate.rate)
                     .where(ExchangeRate.currency == cur, ExchangeRate.rate_date <= (day or date.today()))
                     .order_by(ExchangeRate.rate_date.desc()).limit(1))


class Book:
    """rate_on for reports that convert many documents: one query per foreign currency."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.base = base_currency(db)
        self._rates: dict[str, tuple[list[date], list[float]]] = {}

    def on(self, currency: str | None, day: date | None = None) -> float | None:
        cur = norm(currency)
        if not cur or cur == self.base:
            return 1.0
        if cur not in self._rates:
            rows = self.db.execute(select(ExchangeRate.rate_date, ExchangeRate.rate)
                                   .where(ExchangeRate.currency == cur).order_by(ExchangeRate.rate_date)).all()
            self._rates[cur] = ([r[0] for r in rows], [r[1] for r in rows])
        days, rates = self._rates[cur]
        i = bisect_right(days, day or date.today())
        return rates[i - 1] if i else None

    def doc(self, currency: str | None, rate: float | None, *days: date | datetime | None) -> float | None:
        """Rate of a document: the one fixed on it; null on old documents means rate_on by the document date."""
        if norm(currency) == self.base:
            return 1.0
        return rate if rate is not None else self.on(currency, first_day(*days))


def _lock(db: Session) -> None:
    # Same write lock as erp.next_no: two writers of one (day, currency) queue up instead of a UNIQUE error
    db.execute(update(SyncState).where(SyncState.id == 1).values(rev=SyncState.rev))


def _put(db: Session, day: date, currency: str, rate: float, source: str) -> ExchangeRate:
    row = db.scalar(select(ExchangeRate).where(ExchangeRate.rate_date == day, ExchangeRate.currency == currency))
    if row is None:
        row = ExchangeRate(rate_date=day, currency=currency, rate=rate, source=source)
        db.add(row)
    else:
        row.rate, row.source = rate, source
    return row


def set_manual(db: Session, user: User, currency: str, rate: float, day: date | None = None) -> ExchangeRate:
    """Rate typed by hand. It replaces a fetched rate of the same day, and a later fetch leaves it alone."""
    cur = clean_currency(currency)
    if cur == base_currency(db):
        raise HTTPException(400, f"{cur} ana para birimi, kuru her zaman 1")
    day = day or date.today()
    if day > date.today():
        raise HTTPException(400, "İleri tarihli kur girilemez")
    _lock(db)
    old = rate_on(db, cur, day)
    row = _put(db, day, cur, rate, "manual")
    audit.record(db, user, "exchange_rate", f"{cur} {day.isoformat()}", "rate", old, rate)
    return row


def rate_out(r: ExchangeRate) -> dict[str, Any]:
    return {"id": r.id, "rate_date": r.rate_date.isoformat(), "currency": r.currency, "rate": r.rate,
            "source": r.source, "source_label": SOURCES.get(r.source, r.source)}


def listing(db: Session, limit: int = 300) -> dict[str, Any]:
    newest = (select(ExchangeRate.currency, func.max(ExchangeRate.rate_date).label("day"))
              .group_by(ExchangeRate.currency).subquery())
    latest = db.scalars(select(ExchangeRate).join(newest, (ExchangeRate.currency == newest.c.currency)
                                                  & (ExchangeRate.rate_date == newest.c.day))
                        .order_by(ExchangeRate.currency))
    rows = db.scalars(select(ExchangeRate).order_by(ExchangeRate.rate_date.desc(), ExchangeRate.currency).limit(limit))
    return {"base": base_currency(db), "latest": [rate_out(r) for r in latest], "rows": [rate_out(r) for r in rows]}


# ---------- Merkez Bankası bulletin ----------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """The address is fixed: a redirect is a failed fetch, never a second request."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def download() -> bytes:
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(TCMB_URL, headers={"User-Agent": "LAB-ERP"})
    deadline = time.monotonic() + FETCH_TIMEOUT
    buf = bytearray()
    try:
        with opener.open(req, timeout=FETCH_TIMEOUT) as r:
            while chunk := r.read1(65536):
                buf += chunk
                if len(buf) > FETCH_MAX_BYTES:
                    raise RateFetchError(_BAD_REPLY)
                if time.monotonic() > deadline:
                    raise RateFetchError(_OFFLINE)
    except (OSError, http.client.HTTPException) as e:   # URLError, HTTPError and timeouts are OSError
        raise RateFetchError(_OFFLINE) from e
    return bytes(buf)


def _bulletin_day(root: Any) -> date:
    for key, fmt in (("Date", "%m/%d/%Y"), ("Tarih", "%d.%m.%Y")):
        try:
            return datetime.strptime(root.get(key) or "", fmt).date()
        except ValueError:
            continue
    return date.today()


def parse_bulletin(data: bytes) -> tuple[date, dict[str, float]]:
    """Bulletin day and TRY per one unit of each currency: ForexSelling / Unit."""
    try:
        root = ElementTree.fromstring(data)
    except Exception as e:  # noqa: BLE001 - ParseError and the defusedxml refusals
        raise RateFetchError(_BAD_REPLY) from e
    out: dict[str, float] = {}
    for c in root.findall("Currency"):
        code = norm(c.get("CurrencyCode") or c.get("Kod"))
        try:
            sell, unit = float((c.findtext("ForexSelling") or "").strip()), float((c.findtext("Unit") or "1").strip())
        except ValueError:
            continue        # XDR and a few others have no forex selling rate
        if re.fullmatch(r"[A-Z]{3}", code) and sell > 0 and unit > 0:
            out[code] = sell / unit
    if not out:
        raise RateFetchError(_BAD_REPLY)
    return _bulletin_day(root), out


def store_bulletin(db: Session, user: User | None, day: date, try_rates: dict[str, float]) -> int:
    """Write one bulletin in base currency units, through TRY when the base is something else.
    A rate typed by hand for that day stays."""
    base = base_currency(db)
    in_try = {**try_rates, "TRY": 1.0}
    if base not in in_try:
        raise RateFetchError(f"Merkez Bankası listesinde {base} yok. Kurları elle girin.")
    _lock(db)
    manual = set(db.scalars(select(ExchangeRate.currency).where(ExchangeRate.rate_date == day,
                                                                ExchangeRate.source == "manual")))
    n = 0
    for cur, v in in_try.items():
        if cur != base and cur not in manual:
            _put(db, day, cur, v / in_try[base], "tcmb")
            n += 1
    audit.record(db, user, "exchange_rate", f"TCMB {day.isoformat()}", "count", None, n)
    return n


def fetch(db: Session, user: User | None = None) -> dict[str, Any]:
    day, rates = parse_bulletin(download())
    return {"rate_date": day.isoformat(), "count": store_bulletin(db, user, day, rates)}
