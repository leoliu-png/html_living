from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.models import ApiKey, PageAsset
from app.routers.api_keys import create_key, list_keys, reveal_key, revoke_key
from app.routers.pages import publish_page
from app.schemas import ApiKeyCreateRequest, PagePublishRequest
from app.services.api_keys import hash_api_key


class FakeHeaders(dict):
    def get(self, key, default=None):
        return super().get(key.lower(), default)


class FakeRequest:
    def __init__(self, *, session=None, headers=None, query_params=None):
        self.session = session or {}
        self.headers = FakeHeaders({k.lower(): v for k, v in (headers or {}).items()})
        self.query_params = query_params or {}
        self.client = SimpleNamespace(host="127.0.0.1")


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        yield session


@pytest.fixture(autouse=True)
def auth_settings(monkeypatch):
    monkeypatch.setattr(settings, "api_token", "admin-token")
    monkeypatch.setattr(settings, "allowed_domain", "feedmob.com")
    monkeypatch.setattr(settings, "admin_emails", "admin@feedmob.com")


def session_request(email: str, sub: str = "user-1") -> FakeRequest:
    return FakeRequest(session={"user": {"sub": sub, "email": email, "name": email}})


def page_payload(slug: str = "api-key-page") -> PagePublishRequest:
    return PagePublishRequest(
        html="<html><body>API key page</body></html>",
        owner="api",
        description="Created by API key",
        title="API Key Page",
        slug=slug,
    )


def test_create_key_returns_plaintext_and_stores_hash_plus_ciphertext(db) -> None:
    response = create_key(
        payload=ApiKeyCreateRequest(name="Reports"),
        request=session_request("alice@feedmob.com", "alice-sub"),
        db=db,
    )

    assert response.data.key.startswith("ppk_")
    assert response.data.item.name == "Reports"
    assert response.data.item.key_prefix == response.data.key[:12]

    stored = db.scalar(select(ApiKey).where(ApiKey.id == response.data.item.id))
    assert stored is not None
    assert stored.user_email == "alice@feedmob.com"
    assert stored.user_id == "alice-sub"
    assert stored.key_hash == hash_api_key(response.data.key)
    assert response.data.key not in stored.key_hash
    assert stored.key_ciphertext is not None
    assert response.data.key not in stored.key_ciphertext

    listed = list_keys(request=session_request("alice@feedmob.com"), db=db)
    assert len(listed.data) == 1
    assert listed.data[0].id == response.data.item.id
    assert not hasattr(listed.data[0], "key")


def test_owner_can_reveal_api_key(db) -> None:
    created = create_key(
        payload=ApiKeyCreateRequest(name="Revealable"),
        request=session_request("alice@feedmob.com", "alice-sub"),
        db=db,
    )

    revealed = reveal_key(
        key_id=created.data.item.id,
        request=session_request("alice@feedmob.com", "alice-sub"),
        db=db,
    )

    assert revealed.data.key == created.data.key
    assert revealed.data.item.id == created.data.item.id


def test_other_user_cannot_reveal_api_key(db) -> None:
    created = create_key(
        payload=ApiKeyCreateRequest(name="Private"),
        request=session_request("alice@feedmob.com"),
        db=db,
    )

    with pytest.raises(HTTPException) as exc:
        reveal_key(
            key_id=created.data.item.id,
            request=session_request("erin@feedmob.com"),
            db=db,
        )

    assert exc.value.status_code == 404


def test_revoked_api_key_cannot_be_revealed(db) -> None:
    created = create_key(
        payload=ApiKeyCreateRequest(name="Temporary"),
        request=session_request("carol@feedmob.com", "carol-sub"),
        db=db,
    )
    revoke_key(
        key_id=created.data.item.id,
        request=session_request("carol@feedmob.com"),
        db=db,
    )

    with pytest.raises(HTTPException) as exc:
        reveal_key(
            key_id=created.data.item.id,
            request=session_request("carol@feedmob.com"),
            db=db,
        )

    assert exc.value.status_code == 400
    assert "Revoked" in str(exc.value.detail)


def test_legacy_api_key_without_ciphertext_cannot_be_revealed(db) -> None:
    created = create_key(
        payload=ApiKeyCreateRequest(name="Legacy"),
        request=session_request("alice@feedmob.com"),
        db=db,
    )
    stored = db.scalar(select(ApiKey).where(ApiKey.id == created.data.item.id))
    assert stored is not None
    stored.key_ciphertext = None
    db.commit()

    with pytest.raises(HTTPException) as exc:
        reveal_key(
            key_id=created.data.item.id,
            request=session_request("alice@feedmob.com"),
            db=db,
        )

    assert exc.value.status_code == 400
    assert "before re-display support" in str(exc.value.detail)


def test_api_key_can_publish_as_bound_user(db) -> None:
    created_key = create_key(
        payload=ApiKeyCreateRequest(name="Publisher"),
        request=session_request("bob@feedmob.com", "bob-sub"),
        db=db,
    )

    response = publish_page(
        payload=page_payload(),
        request=FakeRequest(headers={"Authorization": f"Bearer {created_key.data.key}"}),
        db=db,
    )

    page = db.scalar(select(PageAsset).where(PageAsset.id == response.data.id))
    assert page is not None
    assert page.submitter == "bob@feedmob.com"
    assert page.user_email == "bob@feedmob.com"
    assert page.user_id == "bob-sub"

    stored = db.scalar(select(ApiKey).where(ApiKey.id == created_key.data.item.id))
    assert stored is not None
    assert stored.last_used_at is not None


def test_revoked_api_key_cannot_publish(db) -> None:
    created_key = create_key(
        payload=ApiKeyCreateRequest(name="Temporary"),
        request=session_request("carol@feedmob.com", "carol-sub"),
        db=db,
    )

    revoked = revoke_key(
        key_id=created_key.data.item.id,
        request=session_request("carol@feedmob.com"),
        db=db,
    )
    assert revoked.data.active is False

    with pytest.raises(HTTPException) as exc:
        publish_page(
            payload=page_payload(slug="revoked"),
            request=FakeRequest(headers={"Authorization": f"Bearer {created_key.data.key}"}),
            db=db,
        )

    assert exc.value.status_code == 403


def test_user_cannot_list_or_revoke_another_users_keys(db) -> None:
    created_key = create_key(
        payload=ApiKeyCreateRequest(name="Private"),
        request=session_request("dana@feedmob.com"),
        db=db,
    )

    other_list = list_keys(request=session_request("erin@feedmob.com"), db=db)
    assert other_list.data == []

    with pytest.raises(HTTPException) as exc:
        revoke_key(
            key_id=created_key.data.item.id,
            request=session_request("erin@feedmob.com"),
            db=db,
        )

    assert exc.value.status_code == 404
