"""Kurlar: exchange rates by hand or from the Merkez Bankası bulletin. Reading is open to every user, because the
purchasing and sales forms fill the document rate from it; rates are public figures and show no company money."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..models import User
from ..permissions import require
from ..services import fx
from .deps import any_user, get_db

finance_edit = require("finance", "edit")

router = APIRouter(tags=["rates"])


class RateIn(BaseModel):
    currency: str = Field(max_length=8)
    rate: float = Field(gt=0, allow_inf_nan=False)
    rate_date: date | None = None


@router.get("/rates")
def list_rates(_: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return fx.listing(db)


@router.get("/rates/on")
def rate_on(currency: str, day: date | None = None, _: User = Depends(any_user),
            db: Session = Depends(get_db)) -> dict[str, Any]:
    """The rate a document of that day would take; null when the table has none."""
    return {"currency": fx.norm(currency), "day": (day or date.today()).isoformat(), "base": fx.base_currency(db),
            "rate": fx.rate_on(db, currency, day)}


@router.post("/rates", status_code=201)
def add_rate(body: RateIn, me: User = Depends(finance_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    row = fx.set_manual(db, me, body.currency, body.rate, body.rate_date)
    db.commit()
    return fx.rate_out(row)


@router.post("/rates/fetch")
def fetch_rates(me: User = Depends(finance_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        out = fx.fetch(db, me)
    except fx.RateFetchError as e:
        raise HTTPException(502, str(e)) from e
    db.commit()
    return out
