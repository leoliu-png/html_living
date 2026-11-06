from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.routers.pages import list_pages
from app.services.pages import PublishHtmlPageInput, SubmissionContext, publish_html_page


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    return session_factory()


class FakeHeaders(dict):
    def get(self, key, default=None):
        return super().get(key.lower(), default)


class FakeRequest:
    def __init__(self, *, session=None, headers=None, query_params=None):
        default_session = {"user": {"sub": "viewer", "email": "viewer@feedmob.com"}}
        self.session = session if session is not None else default_session
        self.headers = FakeHeaders({k.lower(): v for k, v in (headers or {}).items()})
        self.query_params = query_params or {}
        self.client = None


def seed_page(
    db,
    owner: str,
    slug: str,
    title: str,
    description: str,
    *,
    submitter: Optional[str] = None,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
) -> None:
    return publish_html_page(
        db,
        PublishHtmlPageInput(
            html=f"<html><body><h1>{title}</h1></body></html>",
            owner=owner,
            slug=slug,
            title=title,
            submitter=submitter or f"{owner}@feedmob.com",
            description=description,
        ),
        SubmissionContext(
            submit_ip="127.0.0.1",
            submit_user_agent="pytest",
            user_id=user_id,
            user_email=user_email,
        ),
    )


def test_list_pages_returns_pagination_metadata() -> None:
    with make_session() as db:
        seed_page(db, "leo", "alpha", "Alpha", "First page")
        seed_page(db, "ken", "beta", "Beta", "Second page")
        seed_page(db, "esther", "gamma", "Gamma", "Third page")

        response = list_pages(request=FakeRequest(), db=db, page=1, page_size=2, q=None)

    assert response.code == 0
    assert len(response.data.items) == 2
    assert response.data.pagination.page == 1
    assert response.data.pagination.page_size == 2
    assert response.data.pagination.total == 3
    assert response.data.pagination.total_pages == 2
    assert response.data.pagination.has_next is True
    assert response.data.pagination.has_prev is False


def test_list_pages_supports_keyword_search() -> None:
    with make_session() as db:
        seed_page(db, "leo", "campaign-preview", "Campaign Preview", "Marketing review")
        seed_page(db, "ken", "weekly-report", "Weekly Report", "Engineering summary")
        seed_page(db, "ops", "runbook", "Ops Runbook", "Deployment checklist")

        response = list_pages(
            request=FakeRequest(),
            db=db,
            page=1,
            page_size=10,
            q="weekly",
        )

    assert response.data.pagination.total == 1
    assert response.data.items[0].owner == "ken"
    assert response.data.items[0].slug == "weekly-report"


def test_list_pages_filters_by_created_range() -> None:
    with make_session() as db:
        recent = seed_page(db, "leo", "recent", "Recent", "Recent page")
        old = seed_page(db, "ken", "old", "Old", "Old page")
        old.created_at = datetime.now(timezone.utc) - timedelta(days=8)
        db.commit()

        response = list_pages(
            request=FakeRequest(),
            db=db,
            page=1,
            page_size=10,
            q=None,
            created_range="7d",
        )

    assert [item.slug for item in response.data.items] == [recent.slug]


def test_list_pages_marks_unassigned_pages_from_allowlist(monkeypatch) -> None:
    monkeypatch.setattr(
        settings,
        "submitter_allowlist",
        "alice@feedmob.com,bob@feedmob.com",
    )
    with make_session() as db:
        seed_page(
            db,
            "legacy",
            "unknown",
            "Unknown",
            "Legacy bad submitter",
            submitter="random-agent",
        )
        seed_page(
            db,
            "owned",
            "alice",
            "Alice",
            "Known submitter",
            submitter="alice@feedmob.com",
            user_email="alice@feedmob.com",
        )

        response = list_pages(
            request=FakeRequest(),
            db=db,
            page=1,
            page_size=10,
            q=None,
        )

    by_slug = {item.slug: item for item in response.data.items}
    assert by_slug["unknown"].is_unassigned is True
    assert by_slug["alice"].is_unassigned is False


def test_list_pages_unassigned_scope_returns_only_unassigned(monkeypatch) -> None:
    monkeypatch.setattr(settings, "submitter_allowlist", "alice@feedmob.com")
    with make_session() as db:
        seed_page(
            db,
            "legacy",
            "unknown",
            "Unknown",
            "Legacy bad submitter",
            submitter="random-agent",
        )
        seed_page(
            db,
            "owned",
            "alice",
            "Alice",
            "Known submitter",
            submitter="alice@feedmob.com",
            user_email="alice@feedmob.com",
        )
        seed_page(
            db,
            "new",
            "carol",
            "Carol",
            "New user-owned page",
            submitter="carol@feedmob.com",
            user_id="carol-sub",
            user_email="carol@feedmob.com",
        )

        response = list_pages(
            request=FakeRequest(),
            db=db,
            page=1,
            page_size=10,
            q=None,
            scope="unassigned",
        )

    assert [item.slug for item in response.data.items] == ["unknown"]
    assert response.data.items[0].is_unassigned is True


def test_user_identity_keeps_new_pages_out_of_unassigned_scope(monkeypatch) -> None:
    monkeypatch.setattr(settings, "submitter_allowlist", "alice@feedmob.com")
    with make_session() as db:
        seed_page(
            db,
            "new",
            "carol",
            "Carol",
            "New user-owned page",
            submitter="carol@feedmob.com",
            user_id="carol-sub",
            user_email="carol@feedmob.com",
        )

        response = list_pages(
            request=FakeRequest(),
            db=db,
            page=1,
            page_size=10,
            q=None,
            scope="unassigned",
        )

    assert response.data.items == []
    assert response.data.pagination.total == 0


def test_internal_or_user_id_only_identity_is_unassigned(monkeypatch) -> None:
    monkeypatch.setattr(settings, "submitter_allowlist", "")
    with make_session() as db:
        seed_page(
            db,
            "mcp",
            "static",
            "Static MCP",
            "Historical internal identity",
            submitter="robot",
            user_id="static",
            user_email="static@mcp.internal",
        )
        seed_page(
            db,
            "legacy",
            "user-id-only",
            "User ID Only",
            "Missing owner email",
            submitter="leo@feedmob.com",
            user_id="leo-sub",
        )
        seed_page(
            db,
            "admin",
            "token",
            "Admin Token",
            "Admin token system page",
            submitter="admin-token@service-deployer.internal",
            user_email="admin-token@service-deployer.internal",
        )

        response = list_pages(
            request=FakeRequest(),
            db=db,
            page=1,
            page_size=10,
            q=None,
            scope="unassigned",
        )

    by_slug = {item.slug: item for item in response.data.items}
    assert set(by_slug) == {"static", "user-id-only", "token"}
    assert by_slug["static"].is_unassigned is True
    assert by_slug["user-id-only"].is_unassigned is True
    assert by_slug["token"].is_unassigned is True


def test_list_pages_returns_bound_identity_filters(monkeypatch) -> None:
    monkeypatch.setattr(settings, "submitter_allowlist", "alice@feedmob.com")
    with make_session() as db:
        seed_page(
            db,
            "new",
            "carol",
            "Carol",
            "New user-owned page",
            submitter="legacy-carol",
            user_id="carol-sub",
            user_email="carol@feedmob.com",
        )
        seed_page(
            db,
            "new",
            "dave",
            "Dave",
            "New user-owned page",
            submitter="legacy-dave",
            user_id="dave-sub",
            user_email="dave@feedmob.com",
        )
        seed_page(
            db,
            "legacy",
            "static",
            "Static",
            "Legacy internal page",
            submitter="robot",
            user_id="static",
            user_email="static@mcp.internal",
        )
        seed_page(
            db,
            "legacy",
            "admin-token",
            "Admin token",
            "Admin-token page",
            submitter="admin-token@service-deployer.internal",
            user_email="admin-token@service-deployer.internal",
        )
        seed_page(
            db,
            "legacy",
            "user-id-only",
            "User ID only",
            "Legacy user-id-only page",
            submitter="legacy",
            user_id="legacy-sub",
        )

        response = list_pages(
            request=FakeRequest(),
            db=db,
            page=1,
            page_size=10,
            q=None,
        )

    filters = {
        (item.user_id, item.user_email): item.count
        for item in response.data.identity_filters
    }
    assert filters == {
        ("carol-sub", "carol@feedmob.com"): 1,
        ("dave-sub", "dave@feedmob.com"): 1,
    }
    by_slug = {item.slug: item for item in response.data.items}
    assert by_slug["carol"].user_id == "carol-sub"
    assert by_slug["carol"].user_email == "carol@feedmob.com"


def test_list_pages_filters_by_bound_user_email(monkeypatch) -> None:
    monkeypatch.setattr(settings, "submitter_allowlist", "alice@feedmob.com")
    with make_session() as db:
        seed_page(
            db,
            "new",
            "carol",
            "Carol",
            "Carol page",
            submitter="not-email",
            user_id="carol-sub",
            user_email="carol@feedmob.com",
        )
        seed_page(
            db,
            "new",
            "dave",
            "Dave",
            "Dave page",
            submitter="dave@feedmob.com",
            user_id="dave-sub",
            user_email="dave@feedmob.com",
        )

        response = list_pages(
            request=FakeRequest(),
            db=db,
            page=1,
            page_size=10,
            q=None,
            user_email="carol@feedmob.com",
        )

    assert [item.slug for item in response.data.items] == ["carol"]
    assert response.data.items[0].submitter == "not-email"


def test_list_pages_filters_by_bound_user_id(monkeypatch) -> None:
    monkeypatch.setattr(settings, "submitter_allowlist", "alice@feedmob.com")
    with make_session() as db:
        seed_page(
            db,
            "new",
            "carol",
            "Carol",
            "Carol page",
            submitter="carol@feedmob.com",
            user_id="carol-sub",
            user_email="old-carol@feedmob.com",
        )
        seed_page(
            db,
            "new",
            "dave",
            "Dave",
            "Dave page",
            submitter="dave@feedmob.com",
            user_id="dave-sub",
            user_email="dave@feedmob.com",
        )

        response = list_pages(
            request=FakeRequest(),
            db=db,
            page=1,
            page_size=10,
            q=None,
            user_id="carol-sub",
        )

    assert [item.slug for item in response.data.items] == ["carol"]
    assert response.data.items[0].user_email == "old-carol@feedmob.com"


def test_list_pages_returns_legacy_submitter_filters(monkeypatch) -> None:
    monkeypatch.setattr(settings, "submitter_allowlist", "alice@feedmob.com")
    with make_session() as db:
        seed_page(
            db,
            "legacy",
            "unknown",
            "Unknown",
            "Unassigned legacy",
            submitter="random-agent",
        )
        seed_page(
            db,
            "owned",
            "alice",
            "Alice",
            "Known submitter",
            submitter="alice@feedmob.com",
            user_id="alice-sub",
            user_email="alice@feedmob.com",
        )
        seed_page(
            db,
            "new",
            "carol",
            "Carol",
            "Non-allowlisted but assigned",
            submitter="carol@feedmob.com",
            user_id="carol-sub",
            user_email="carol@feedmob.com",
        )
        seed_page(
            db,
            "new",
            "dave",
            "Dave",
            "Non-allowlisted but assigned by user id",
            submitter="dave@feedmob.com",
            user_id="dave-sub",
        )

        response = list_pages(
            request=FakeRequest(),
            db=db,
            page=1,
            page_size=10,
            q=None,
        )

    assert response.data.legacy_submitters == ["dave@feedmob.com", "random-agent"]


def test_list_pages_filters_by_legacy_submitter(monkeypatch) -> None:
    monkeypatch.setattr(settings, "submitter_allowlist", "alice@feedmob.com")
    with make_session() as db:
        seed_page(
            db,
            "new",
            "carol",
            "Carol",
            "Assigned carol page",
            submitter="carol@feedmob.com",
            user_id="carol-sub",
            user_email="carol@feedmob.com",
        )
        seed_page(
            db,
            "new",
            "dave",
            "Dave",
            "Assigned dave page",
            submitter="dave@feedmob.com",
            user_id="dave-sub",
            user_email="dave@feedmob.com",
        )
        seed_page(
            db,
            "legacy",
            "unknown",
            "Unknown",
            "Unassigned legacy",
            submitter="carol@feedmob.com",
        )

        response = list_pages(
            request=FakeRequest(),
            db=db,
            page=1,
            page_size=10,
            q=None,
            submitter="carol@feedmob.com",
        )

    assert [item.slug for item in response.data.items] == ["unknown"]
    assert response.data.pagination.total == 1
    assert response.data.legacy_submitters == ["carol@feedmob.com"]


def test_list_pages_mine_scope_returns_only_current_users_assigned_pages(monkeypatch) -> None:
    monkeypatch.setattr(settings, "submitter_allowlist", "alice@feedmob.com")
    with make_session() as db:
        seed_page(
            db,
            "legacy",
            "unknown",
            "Unknown",
            "Legacy bad submitter",
            submitter="random-agent",
        )
        seed_page(
            db,
            "owned",
            "by-email",
            "By Email",
            "Owned by user email",
            submitter="alice@feedmob.com",
            user_email="alice@feedmob.com",
        )
        seed_page(
            db,
            "owned",
            "by-user-id",
            "By User Id",
            "Owned by user id",
            submitter="legacy-name",
            user_id="alice-sub",
            user_email="old-alice@feedmob.com",
        )
        seed_page(
            db,
            "other",
            "bob",
            "Bob",
            "Other user",
            submitter="bob@feedmob.com",
            user_id="bob-sub",
            user_email="bob@feedmob.com",
        )

        response = list_pages(
            request=FakeRequest(
                session={
                    "user": {
                        "sub": "alice-sub",
                        "email": "alice@feedmob.com",
                        "name": "Alice",
                    }
                }
            ),
            db=db,
            page=1,
            page_size=10,
            q=None,
            scope="mine",
        )

    slugs = {item.slug for item in response.data.items}
    assert slugs == {"by-email", "by-user-id"}
    assert all(not item.is_unassigned for item in response.data.items)
