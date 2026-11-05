from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ApiKey

API_KEY_PREFIX = "ppk"
API_KEY_SECRET_BYTES = 32
_API_KEY_SERIALIZER_SALT = "service-deployer-api-key-v1"


@dataclass(frozen=True)
class ApiKeyPrincipal:
    user_email: str
    user_id: Optional[str]
    key_id: str


class ApiKeyRevealError(Exception):
    """Raised when an API key cannot be revealed to its owner."""


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    return f"{API_KEY_PREFIX}_{secrets.token_urlsafe(API_KEY_SECRET_BYTES)}"


def _key_serializer() -> URLSafeSerializer:
    return URLSafeSerializer(settings.session_secret, salt=_API_KEY_SERIALIZER_SALT)


def encrypt_api_key(key: str) -> str:
    return _key_serializer().dumps(key)


def decrypt_api_key(ciphertext: str) -> str:
    value = _key_serializer().loads(ciphertext)
    if not isinstance(value, str) or not value:
        raise ApiKeyRevealError("Stored API key ciphertext is invalid.")
    return value


def create_api_key(
    db: Session,
    *,
    user_email: str,
    user_id: Optional[str],
    name: str,
) -> tuple[ApiKey, str]:
    key = generate_api_key()
    email = user_email.strip().lower()
    api_key = ApiKey(
        user_email=email,
        user_id=user_id,
        name=name.strip(),
        key_hash=hash_api_key(key),
        key_prefix=key[:12],
        key_ciphertext=encrypt_api_key(key),
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return api_key, key


def list_api_keys(db: Session, *, user_email: str) -> list[ApiKey]:
    return list(
        db.scalars(
            select(ApiKey)
            .where(ApiKey.user_email == user_email.lower())
            .order_by(ApiKey.created_at.desc(), ApiKey.id)
        ).all()
    )


def revoke_api_key(db: Session, *, key_id: str, user_email: str) -> ApiKey:
    api_key = db.scalar(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_email == user_email.lower())
    )
    if api_key is None:
        raise KeyError("API key not found.")
    if api_key.active:
        api_key.active = False
        api_key.revoked_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(api_key)
    return api_key


def reveal_api_key(db: Session, *, key_id: str, user_email: str) -> tuple[ApiKey, str]:
    api_key = db.scalar(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_email == user_email.lower())
    )
    if api_key is None:
        raise KeyError("API key not found.")
    if not api_key.active:
        raise ApiKeyRevealError("Revoked API keys cannot be revealed. Create a new key.")
    if not api_key.key_ciphertext:
        raise ApiKeyRevealError(
            "This API key was created before re-display support and cannot be revealed. "
            "Create a new key."
        )
    try:
        raw_key = decrypt_api_key(api_key.key_ciphertext)
    except BadSignature as exc:
        raise ApiKeyRevealError(
            "Stored API key cannot be decrypted with the current server secret. Create a new key."
        ) from exc
    if hash_api_key(raw_key) != api_key.key_hash:
        raise ApiKeyRevealError("Stored API key ciphertext does not match the key hash.")
    return api_key, raw_key


def authenticate_api_key(db: Session, key: str) -> Optional[ApiKeyPrincipal]:
    api_key = db.scalar(
        select(ApiKey).where(ApiKey.key_hash == hash_api_key(key), ApiKey.active.is_(True))
    )
    if api_key is None:
        return None
    api_key.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return ApiKeyPrincipal(
        user_email=api_key.user_email,
        user_id=api_key.user_id,
        key_id=api_key.id,
    )
