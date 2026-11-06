from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.models import PageAsset
from app.routers.pages import (
    claim_unassigned_page,
    delete_page_endpoint,
    get_page,
    publish_page,
    update_page,
)
from app.schemas import PagePublishRequest
from app.schemas.page import PageUpdateRequest


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
    monkeypatch.setattr(settings, "submitter_allowlist", "")


def make_payload(**overrides):
    data = {
        "html": "<!doctype html><html><body>Hello</body></html>",
        "owner": "demo",
        "description": "Demo page",
        "title": "Demo",
    }
    data.update(overrides)
    return PagePublishRequest(**data)


def test_publish_uses_session_email_and_ignores_body_submitter(db) -> None:
    request = FakeRequest(
        session={"user": {"sub": "u-1", "email": "alice@feedmob.com", "name": "Alice"}},
    )
    response = publish_page(
        payload=make_payload(submitter="mallory@feedmob.com"),
        request=request,
        db=db,
    )

    page = db.scalar(select(PageAsset).where(PageAsset.id == response.data.id))
    assert page is not None
    assert page.submitter == "alice@feedmob.com"
    assert page.user_email == "alice@feedmob.com"
    assert page.user_id == "u-1"


def test_publish_uses_forwarded_mcp_email_when_admin_token_is_present(db) -> None:
    request = FakeRequest(
        headers={
            "Authorization": "Bearer admin-token",
            "X-User-Id": "u-2",
            "X-User-Email": "bob@feedmob.com",
            "X-User-Name": "Bob",
        },
    )
    response = publish_page(payload=make_payload(slug="mcp-demo"), request=request, db=db)

    page = db.scalar(select(PageAsset).where(PageAsset.id == response.data.id))
    assert page is not None
    assert page.submitter == "bob@feedmob.com"
    assert page.user_email == "bob@feedmob.com"
    assert page.user_id == "u-2"


def test_session_identity_takes_precedence_over_forwarded_headers(db) -> None:
    request = FakeRequest(
        session={"user": {"sub": "session-user", "email": "alice@feedmob.com", "name": "Alice"}},
        headers={
            "Authorization": "Bearer admin-token",
            "X-User-Id": "forwarded-user",
            "X-User-Email": "bob@feedmob.com",
        },
    )
    response = publish_page(payload=make_payload(slug="session-wins"), request=request, db=db)

    page = db.scalar(select(PageAsset).where(PageAsset.id == response.data.id))
    assert page is not None
    assert page.submitter == "alice@feedmob.com"
    assert page.user_email == "alice@feedmob.com"
    assert page.user_id == "session-user"


def test_publish_accepts_admin_token_from_query_parameter(db) -> None:
    request = FakeRequest(query_params={"token": "admin-token"})
    response = publish_page(payload=make_payload(slug="query-token"), request=request, db=db)

    page = db.scalar(select(PageAsset).where(PageAsset.id == response.data.id))
    assert page is not None
    assert page.submitter == "admin-token@service-deployer.internal"


def test_publish_rejects_forged_forwarded_email_without_admin_token(db) -> None:
    request = FakeRequest(headers={"X-User-Email": "mallory@feedmob.com"})

    with pytest.raises(HTTPException) as exc:
        publish_page(payload=make_payload(slug="forged"), request=request, db=db)

    assert exc.value.status_code == 403


def test_publish_rejects_forwarded_email_from_disallowed_domain(db) -> None:
    request = FakeRequest(
        headers={
            "Authorization": "Bearer admin-token",
            "X-User-Id": "external",
            "X-User-Email": "mallory@example.com",
        },
    )

    with pytest.raises(HTTPException) as exc:
        publish_page(payload=make_payload(slug="bad-domain"), request=request, db=db)

    assert exc.value.status_code == 403


def test_publish_rejects_external_session_email_without_domain_gate(db, monkeypatch) -> None:
    monkeypatch.setattr(settings, "allowed_domain", "")
    request = FakeRequest(
        session={"user": {"sub": "external-user", "email": "mallory@example.com"}},
    )

    with pytest.raises(HTTPException) as exc:
        publish_page(payload=make_payload(slug="external-session"), request=request, db=db)

    assert exc.value.status_code == 403


def test_publish_rejects_internal_forwarded_identity(db) -> None:
    request = FakeRequest(
        headers={
            "Authorization": "Bearer admin-token",
            "X-User-Id": "static",
            "X-User-Email": "static@mcp.internal",
        },
    )

    with pytest.raises(HTTPException) as exc:
        publish_page(payload=make_payload(slug="internal-identity"), request=request, db=db)

    assert exc.value.status_code == 403


def test_publish_rejects_session_without_email(db) -> None:
    request = FakeRequest(session={"user": {"sub": "missing-email", "name": "No Email"}})

    with pytest.raises(HTTPException) as exc:
        publish_page(payload=make_payload(slug="missing-email"), request=request, db=db)

    assert exc.value.status_code == 403


def test_publish_with_admin_token_uses_admin_token_identity(db) -> None:
    request = FakeRequest(headers={"Authorization": "Bearer admin-token"})
    response = publish_page(payload=make_payload(slug="admin-token-demo"), request=request, db=db)

    page = db.scalar(select(PageAsset).where(PageAsset.id == response.data.id))
    assert page is not None
    assert page.submitter == "admin-token@service-deployer.internal"
    assert page.user_email == "admin-token@service-deployer.internal"
    assert page.user_id is None
    detail = get_page(owner=response.data.owner, slug=response.data.slug, request=request, db=db)
    assert detail.data.is_unassigned is True


def test_any_authenticated_user_can_update_and_claim_admin_token_page(db) -> None:
    created = publish_page(
        payload=make_payload(slug="admin-token-unassigned-update"),
        request=FakeRequest(headers={"Authorization": "Bearer admin-token"}),
        db=db,
    )

    response = update_page(
        page_id=created.data.id,
        payload=PageUpdateRequest(title="Claimed admin token page"),
        request=FakeRequest(
            session={"user": {"sub": "claimer-sub", "email": "claimer@feedmob.com"}}
        ),
        db=db,
    )

    assert response.data.title == "Claimed admin token page"
    assert response.data.submitter == "claimer@feedmob.com"
    assert response.data.user_email == "claimer@feedmob.com"
    assert response.data.user_id == "claimer-sub"
    assert response.data.is_unassigned is False


def test_any_authenticated_user_can_delete_admin_token_page(db) -> None:
    created = publish_page(
        payload=make_payload(slug="admin-token-unassigned-delete"),
        request=FakeRequest(headers={"Authorization": "Bearer admin-token"}),
        db=db,
    )

    response = delete_page_endpoint(
        page_id=created.data.id,
        request=FakeRequest(
            session={"user": {"sub": "deleter-sub", "email": "deleter@feedmob.com"}}
        ),
        db=db,
    )

    assert response.data["id"] == created.data.id
    assert db.scalar(select(PageAsset).where(PageAsset.id == created.data.id)) is None


def test_forwarded_mcp_user_can_update_own_page(db) -> None:
    created = publish_page(
        payload=make_payload(slug="owned"),
        request=FakeRequest(
            headers={
                "Authorization": "Bearer admin-token",
                "X-User-Id": "u-3",
                "X-User-Email": "carol@feedmob.com",
            },
        ),
        db=db,
    )

    response = update_page(
        page_id=created.data.id,
        payload=PageUpdateRequest(title="Updated"),
        request=FakeRequest(
            headers={
                "Authorization": "Bearer admin-token",
                "X-User-Id": "u-3",
                "X-User-Email": "carol@feedmob.com",
            },
        ),
        db=db,
    )

    assert response.data.title == "Updated"


def test_forwarded_mcp_user_cannot_update_another_users_page(db) -> None:
    created = publish_page(
        payload=make_payload(slug="update-not-owned"),
        request=FakeRequest(
            headers={
                "Authorization": "Bearer admin-token",
                "X-User-Id": "u-owner",
                "X-User-Email": "owner@feedmob.com",
            },
        ),
        db=db,
    )

    with pytest.raises(HTTPException) as exc:
        update_page(
            page_id=created.data.id,
            payload=PageUpdateRequest(title="Should Not Save"),
            request=FakeRequest(
                headers={
                    "Authorization": "Bearer admin-token",
                    "X-User-Id": "u-other",
                    "X-User-Email": "other@feedmob.com",
                },
            ),
            db=db,
        )

    assert exc.value.status_code == 403
    page = db.scalar(select(PageAsset).where(PageAsset.id == created.data.id))
    assert page is not None
    assert page.title == "Demo"


def test_any_authenticated_user_can_update_and_claim_unassigned_page(db, monkeypatch) -> None:
    monkeypatch.setattr(settings, "submitter_allowlist", "alice@feedmob.com")
    created = publish_page(
        payload=make_payload(slug="legacy-unassigned"),
        request=FakeRequest(headers={"Authorization": "Bearer admin-token"}),
        db=db,
    )
    page = db.scalar(select(PageAsset).where(PageAsset.id == created.data.id))
    assert page is not None
    page.submitter = "bad-agent-value"
    page.user_id = None
    page.user_email = None
    db.commit()

    response = update_page(
        page_id=created.data.id,
        payload=PageUpdateRequest(title="Claimed"),
        request=FakeRequest(
            session={"user": {"sub": "claimer-sub", "email": "claimer@feedmob.com"}}
        ),
        db=db,
    )

    assert response.data.title == "Claimed"
    assert response.data.submitter == "claimer@feedmob.com"
    assert response.data.is_unassigned is False
    claimed = db.scalar(select(PageAsset).where(PageAsset.id == created.data.id))
    assert claimed is not None
    assert claimed.submitter == "claimer@feedmob.com"
    assert claimed.user_email == "claimer@feedmob.com"
    assert claimed.user_id == "claimer-sub"


def test_any_authenticated_user_can_claim_unassigned_page_without_editing(db, monkeypatch) -> None:
    monkeypatch.setattr(settings, "submitter_allowlist", "alice@feedmob.com")
    created = publish_page(
        payload=make_payload(slug="claim-button"),
        request=FakeRequest(headers={"Authorization": "Bearer admin-token"}),
        db=db,
    )
    page = db.scalar(select(PageAsset).where(PageAsset.id == created.data.id))
    assert page is not None
    page.submitter = "legacy-agent"
    page.user_id = None
    page.user_email = None
    db.commit()

    response = claim_unassigned_page(
        page_id=created.data.id,
        request=FakeRequest(
            session={"user": {"sub": "claim-user", "email": "claimant@feedmob.com"}}
        ),
        db=db,
    )

    assert response.msg == "page claimed"
    assert response.data.title == "Demo"
    assert response.data.submitter == "claimant@feedmob.com"
    assert response.data.is_unassigned is False
    claimed = db.scalar(select(PageAsset).where(PageAsset.id == created.data.id))
    assert claimed is not None
    assert claimed.submitter == "claimant@feedmob.com"
    assert claimed.user_email == "claimant@feedmob.com"
    assert claimed.user_id == "claim-user"


def test_admin_token_cannot_claim_unassigned_page(db, monkeypatch) -> None:
    monkeypatch.setattr(settings, "submitter_allowlist", "alice@feedmob.com")
    created = publish_page(
        payload=make_payload(slug="admin-token-claim"),
        request=FakeRequest(headers={"Authorization": "Bearer admin-token"}),
        db=db,
    )
    page = db.scalar(select(PageAsset).where(PageAsset.id == created.data.id))
    assert page is not None
    page.submitter = "legacy-agent"
    page.user_id = None
    page.user_email = None
    db.commit()

    with pytest.raises(HTTPException) as exc:
        claim_unassigned_page(
            page_id=created.data.id,
            request=FakeRequest(headers={"Authorization": "Bearer admin-token"}),
            db=db,
        )

    assert exc.value.status_code == 401


def test_claim_rejects_assigned_page(db, monkeypatch) -> None:
    monkeypatch.setattr(settings, "submitter_allowlist", "owner@feedmob.com,other@feedmob.com")
    created = publish_page(
        payload=make_payload(slug="already-assigned"),
        request=FakeRequest(
            session={"user": {"sub": "owner-sub", "email": "owner@feedmob.com"}}
        ),
        db=db,
    )

    with pytest.raises(HTTPException) as exc:
        claim_unassigned_page(
            page_id=created.data.id,
            request=FakeRequest(
                session={"user": {"sub": "other-sub", "email": "other@feedmob.com"}}
            ),
            db=db,
        )

    assert exc.value.status_code == 409


def test_unassigned_page_claimed_by_api_key_user(db, monkeypatch) -> None:
    from app.routers.api_keys import create_key
    from app.schemas import ApiKeyCreateRequest

    monkeypatch.setattr(settings, "submitter_allowlist", "alice@feedmob.com")
    key_response = create_key(
        payload=ApiKeyCreateRequest(name="Claim legacy"),
        request=FakeRequest(
            session={"user": {"sub": "api-sub", "email": "api-user@feedmob.com"}}
        ),
        db=db,
    )
    created = publish_page(
        payload=make_payload(slug="api-claim"),
        request=FakeRequest(headers={"Authorization": "Bearer admin-token"}),
        db=db,
    )
    page = db.scalar(select(PageAsset).where(PageAsset.id == created.data.id))
    assert page is not None
    page.submitter = "not-an-email"
    page.user_id = None
    page.user_email = None
    db.commit()

    response = update_page(
        page_id=created.data.id,
        payload=PageUpdateRequest(description="Claimed by API key"),
        request=FakeRequest(headers={"Authorization": f"Bearer {key_response.data.key}"}),
        db=db,
    )

    assert response.data.description == "Claimed by API key"
    assert response.data.submitter == "api-user@feedmob.com"
    assert response.data.is_unassigned is False


def test_forwarded_mcp_user_cannot_delete_another_users_page(db) -> None:
    created = publish_page(
        payload=make_payload(slug="not-owned"),
        request=FakeRequest(
            headers={
                "Authorization": "Bearer admin-token",
                "X-User-Id": "u-4",
                "X-User-Email": "dana@feedmob.com",
            },
        ),
        db=db,
    )

    with pytest.raises(HTTPException) as exc:
        delete_page_endpoint(
            page_id=created.data.id,
            request=FakeRequest(
                headers={
                    "Authorization": "Bearer admin-token",
                    "X-User-Id": "u-5",
                    "X-User-Email": "erin@feedmob.com",
                },
            ),
            db=db,
        )

    assert exc.value.status_code == 403


def test_any_authenticated_user_can_delete_unassigned_page(db, monkeypatch) -> None:
    monkeypatch.setattr(settings, "submitter_allowlist", "alice@feedmob.com")
    created = publish_page(
        payload=make_payload(slug="delete-unassigned"),
        request=FakeRequest(headers={"Authorization": "Bearer admin-token"}),
        db=db,
    )
    page = db.scalar(select(PageAsset).where(PageAsset.id == created.data.id))
    assert page is not None
    page.submitter = "test-agent"
    page.user_id = None
    page.user_email = None
    db.commit()

    response = delete_page_endpoint(
        page_id=created.data.id,
        request=FakeRequest(session={"user": {"sub": "other-sub", "email": "other@feedmob.com"}}),
        db=db,
    )

    assert response.data["id"] == created.data.id
    assert db.scalar(select(PageAsset).where(PageAsset.id == created.data.id)) is None


def test_non_owner_cannot_update_allowlisted_assigned_page(db, monkeypatch) -> None:
    monkeypatch.setattr(settings, "submitter_allowlist", "owner@feedmob.com,other@feedmob.com")
    created = publish_page(
        payload=make_payload(slug="assigned-update"),
        request=FakeRequest(
            session={"user": {"sub": "owner-sub", "email": "owner@feedmob.com"}}
        ),
        db=db,
    )

    with pytest.raises(HTTPException) as exc:
        update_page(
            page_id=created.data.id,
            payload=PageUpdateRequest(title="Should Not Save"),
            request=FakeRequest(
                session={"user": {"sub": "other-sub", "email": "other@feedmob.com"}}
            ),
            db=db,
        )

    assert exc.value.status_code == 403


def test_non_owner_cannot_delete_allowlisted_assigned_page(db, monkeypatch) -> None:
    monkeypatch.setattr(settings, "submitter_allowlist", "owner@feedmob.com,other@feedmob.com")
    created = publish_page(
        payload=make_payload(slug="assigned-delete"),
        request=FakeRequest(
            session={"user": {"sub": "owner-sub", "email": "owner@feedmob.com"}}
        ),
        db=db,
    )

    with pytest.raises(HTTPException) as exc:
        delete_page_endpoint(
            page_id=created.data.id,
            request=FakeRequest(
                session={"user": {"sub": "other-sub", "email": "other@feedmob.com"}}
            ),
            db=db,
        )

    assert exc.value.status_code == 403


def test_admin_email_session_can_delete_any_page(db) -> None:
    created = publish_page(
        payload=make_payload(slug="admin-email-delete"),
        request=FakeRequest(
            session={"user": {"sub": "u-7", "email": "owner@feedmob.com", "name": "Owner"}},
        ),
        db=db,
    )

    response = delete_page_endpoint(
        page_id=created.data.id,
        request=FakeRequest(
            session={"user": {"sub": "admin-1", "email": "admin@feedmob.com", "name": "Admin"}},
        ),
        db=db,
    )

    assert response.data["id"] == created.data.id


def test_admin_token_can_delete_any_page(db) -> None:
    created = publish_page(
        payload=make_payload(slug="admin-delete"),
        request=FakeRequest(
            session={"user": {"sub": "u-6", "email": "frank@feedmob.com", "name": "Frank"}},
        ),
        db=db,
    )

    response = delete_page_endpoint(
        page_id=created.data.id,
        request=FakeRequest(headers={"Authorization": "Bearer admin-token"}),
        db=db,
    )

    assert response.data["id"] == created.data.id


def test_page_detail_returns_html_for_editing(db) -> None:
    html = "<!doctype html><html><body><h1>Editable</h1></body></html>"
    created = publish_page(
        payload=make_payload(slug="detail-html", html=html),
        request=FakeRequest(
            session={"user": {"sub": "u-8", "email": "gina@feedmob.com", "name": "Gina"}},
        ),
        db=db,
    )

    detail = get_page(
        owner=created.data.owner,
        slug=created.data.slug,
        request=FakeRequest(session={"user": {"sub": "u-8", "email": "gina@feedmob.com"}}),
        db=db,
    )

    assert detail.data.html == html
    assert detail.data.submitter == "gina@feedmob.com"
