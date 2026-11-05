from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.routers.admin import get_admin_settings, update_admin_settings
from app.schemas import AdminSettingsUpdateRequest


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
    monkeypatch.setattr(settings, "submitter_allowlist", "alice@feedmob.com,bob@feedmob.com")


def admin_request() -> FakeRequest:
    return FakeRequest(session={"user": {"sub": "admin-sub", "email": "admin@feedmob.com"}})


def user_request() -> FakeRequest:
    return FakeRequest(session={"user": {"sub": "user-sub", "email": "user@feedmob.com"}})


def test_admin_settings_reads_env_allowlist_default(db) -> None:
    response = get_admin_settings(request=admin_request(), db=db)

    assert response.data.submitter_allowlist == ["alice@feedmob.com", "bob@feedmob.com"]


def test_admin_can_update_submitter_allowlist(db) -> None:
    response = update_admin_settings(
        payload=AdminSettingsUpdateRequest(
            submitter_allowlist=[
                " Alice@FeedMob.com ",
                "carol@feedmob.com",
                "alice@feedmob.com",
                "",
            ]
        ),
        request=admin_request(),
        db=db,
    )

    assert response.data.submitter_allowlist == ["alice@feedmob.com", "carol@feedmob.com"]

    next_response = get_admin_settings(request=admin_request(), db=db)
    assert next_response.data.submitter_allowlist == ["alice@feedmob.com", "carol@feedmob.com"]


def test_non_admin_cannot_update_submitter_allowlist(db) -> None:
    with pytest.raises(HTTPException) as exc:
        update_admin_settings(
            payload=AdminSettingsUpdateRequest(submitter_allowlist=["user@feedmob.com"]),
            request=user_request(),
            db=db,
        )

    assert exc.value.status_code == 403
