from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AppSetting

SUBMITTER_ALLOWLIST_KEY = "submitter_allowlist"


def get_setting(db: Session, key: str) -> str | None:
    item = db.scalar(select(AppSetting).where(AppSetting.key == key))
    return item.value if item is not None else None


def set_setting(db: Session, key: str, value: str) -> AppSetting:
    item = db.scalar(select(AppSetting).where(AppSetting.key == key))
    if item is None:
        item = AppSetting(key=key, value=value)
        db.add(item)
    else:
        item.value = value
    db.commit()
    db.refresh(item)
    return item


def get_submitter_allowlist_value(db: Session) -> str:
    stored_value = get_setting(db, SUBMITTER_ALLOWLIST_KEY)
    if stored_value is not None:
        return stored_value
    return settings.submitter_allowlist
