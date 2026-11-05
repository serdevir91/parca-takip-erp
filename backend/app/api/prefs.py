"""Screen settings of the signed-in user: saved views, column layouts and theme follow them between devices."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import User, UserPref
from .deps import any_user, get_db
from app.core.i18n import tx

router = APIRouter(prefix="/me/prefs", tags=["prefs"])

MAX_KEYS = 300
Key = Path(min_length=1, max_length=120, pattern=r"^[\w.\-:]+$")


class PrefIn(BaseModel):
    value: str = Field(max_length=200_000)


@router.get("")
def all_prefs(me: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, str]:
    return {p.key: p.value for p in db.scalars(select(UserPref).where(UserPref.user_id == me.id))}


@router.put("/{key}")
def set_pref(body: PrefIn, key: str = Key, me: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, bool]:
    pref = db.get(UserPref, (me.id, key))
    if pref is not None:
        pref.value = body.value
    else:
        count = db.scalar(select(func.count()).select_from(UserPref).where(UserPref.user_id == me.id)) or 0
        if count >= MAX_KEYS:
            raise HTTPException(400, tx("Kayıtlı görünüm sınırına ulaşıldı"))
        db.add(UserPref(user_id=me.id, key=key, value=body.value))
    db.commit()
    return {"ok": True}


@router.delete("/{key}")
def delete_pref(key: str = Key, me: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, bool]:
    pref = db.get(UserPref, (me.id, key))
    if pref is not None:
        db.delete(pref)
        db.commit()
    return {"ok": True}
