import base64
import json

import pytest
from bs4 import BeautifulSoup
from itsdangerous import TimestampSigner
from sqlalchemy import func, select
from test_page_datasets import make_client, upload_csv

from app.config import settings
from app.models import PageAsset
from app.models.sharing import SharingAuditLog
from app.services.api_keys import create_api_key

ADMIN = {"Authorization": "Bearer admin-token"}


def user(email):
    return {**ADMIN, "X-User-Email": email, "X-User-Id": email.split("@")[0]}


def publish(client, visibility="org", **extra):
    response = client.post(
        "/api/pages",
        headers=user("alice@feedmob.com"),
        json={
            "owner": "reports",
            "slug": "secret",
            "description": "Confidential",
            "title": "Secret",
            "html": "<html><body>Secret report</body></html>",
            "visibility": visibility,
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def group(client):
    response = client.post(
        "/api/groups",
        headers=user("alice@feedmob.com"),
        json={
            "slug": "team",
            "name": "Team",
            "managers": ["alice@feedmob.com"],
            "members": ["carol@feedmob.com"],
        },
    )
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("visibility", ["private", "restricted", "org"])
@pytest.mark.parametrize("principal", ["alice", "bob", "carol", "dave", "admin", "admin-token"])
def test_access_matrix_for_html_detail_list_search_stats_and_data(
    monkeypatch, visibility, principal
):
    client, factory, _ = make_client(monkeypatch)
    monkeypatch.setattr(settings, "admin_emails", "admin@feedmob.com")
    group(client)
    page = publish(
        client, visibility, share_with={"users": ["bob@feedmob.com"], "groups": ["team"]}
    )
    assert upload_csv(client, page["id"]).status_code == 201
    if principal == "admin-token":
        headers = ADMIN
    else:
        # Real user API keys must have the same access as their associated user.
        with factory() as db:
            _, key = create_api_key(
                db, user_email=f"{principal}@feedmob.com", user_id=principal, name="Test"
            )
        headers = {"Authorization": f"Bearer {key}"}
    allowed = (
        principal in ("alice", "admin", "admin-token")
        or visibility == "org"
        or (visibility == "restricted" and principal in ("bob", "carol"))
    )
    for path in ("/p/reports/secret", "/api/pages/reports/secret", "/p/reports/secret/data/spend"):
        response = client.get(path, headers=headers)
        assert response.status_code == (200 if allowed else 404), (path, response.text)
        assert response.headers["cache-control"] == "private, no-store"
    for query in ("", "?q=Secret"):
        result = client.get(f"/api/pages{query}", headers=headers).json()["data"]
        assert result["pagination"]["total"] == int(allowed)
        if not allowed:
            assert (
                result["items"] == result["identity_filters"] == result["legacy_submitters"] == []
            )
    assert client.get("/api/pages/stats", headers=headers).json()["data"]["total_pages"] == int(
        allowed
    )
    if allowed and principal in ("admin", "admin-token"):
        with factory() as db:
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(SharingAuditLog)
                    .where(SharingAuditLog.action == "admin_read")
                )
                >= 6
            )


def test_session_access_and_unauthorized_user_cannot_change_sharing(monkeypatch):
    client, factory, _ = make_client(monkeypatch)
    page = publish(client, "private")
    for email, expected in [("alice@feedmob.com", 200), ("bob@feedmob.com", 404)]:
        payload = base64.b64encode(
            json.dumps({"user": {"email": email, "sub": email.split("@")[0]}}).encode()
        )
        client.cookies.set(
            "session", TimestampSigner(settings.session_secret).sign(payload).decode()
        )
        assert client.get("/p/reports/secret").status_code == expected
    assert (
        client.put(f"/api/pages/{page['id']}/sharing", json={"visibility": "org"}).status_code
        == 404
    )
    assert client.put(f"/api/pages/{page['id']}", json={"html": "leak"}).status_code == 404
    assert client.post(f"/api/pages/{page['id']}/claim").status_code == 404
    client.cookies.clear()
    # A spoofed identity header without the trusted MCP credential gives no access.
    assert (
        client.get(
            "/api/pages/reports/secret", headers={"X-User-Email": "alice@feedmob.com"}
        ).status_code
        == 401
    )


def test_signed_data_credentials_recheck_group_membership_and_revision(monkeypatch):
    client, factory, _ = make_client(monkeypatch)
    group(client)
    page = publish(client, "restricted", share_with={"groups": ["team"]})
    upload_csv(client, page["id"])
    rendered = client.get("/p/reports/secret", headers=user("carol@feedmob.com"))
    token = json.loads(
        BeautifulSoup(rendered.text, "html.parser").find(id="page-data-manifest").string
    )["token"]
    data_path = "/p/reports/secret/data/spend"
    assert client.get(data_path, params={"k": token}).status_code == 200
    assert client.get(data_path, params={"k": token + "x"}).status_code == 401
    with factory() as db:
        raw = db.get(PageAsset, page["id"]).data_token
    assert client.get(data_path, params={"k": raw}).status_code == 401
    assert (
        client.put(
            "/api/groups/team/members",
            headers=user("alice@feedmob.com"),
            json={
                "managers": ["alice@feedmob.com"],
                "members": [],
            },
        ).status_code
        == 200
    )
    assert client.get(data_path, params={"k": token}).status_code == 401
    assert client.get("/p/reports/secret", headers=user("carol@feedmob.com")).status_code == 404
    assert (
        client.put(
            f"/api/pages/{page['id']}/sharing",
            headers=user("alice@feedmob.com"),
            json={"visibility": "org"},
        ).status_code
        == 200
    )
    assert client.get(data_path, params={"k": token}).status_code == 401


def test_direct_grant_revocation_and_sharing_only_update_are_audited(monkeypatch):
    client, factory, _ = make_client(monkeypatch)
    page = publish(client, "restricted", share_with={"users": ["BOB@FEEDMOB.COM"]})
    assert client.get("/p/reports/secret", headers=user("bob@feedmob.com")).status_code == 200
    response = client.put(
        f"/api/pages/{page['id']}",
        headers=user("alice@feedmob.com"),
        json={"share_with": {"users": []}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["share_with"]["users"] == []
    assert client.get("/p/reports/secret", headers=user("bob@feedmob.com")).status_code == 404
    with factory() as db:
        rows = db.scalars(
            select(SharingAuditLog).where(SharingAuditLog.action == "sharing_changed")
        ).all()
        assert len(rows) == 1
        assert rows[0].before["share_with"]["users"] == ["bob@feedmob.com"]
        assert rows[0].after["share_with"]["users"] == []


def test_unlisted_url_works_but_discovery_is_hidden_and_owner_can_manage(monkeypatch):
    client, _, _ = make_client(monkeypatch)
    publish(client, "org", listed=False)
    for headers in (user("bob@feedmob.com"), user("alice@feedmob.com"), ADMIN):
        assert client.get("/p/reports/secret", headers=headers).status_code == 200
        assert client.get("/api/pages?q=Secret", headers=headers).json()["data"]["items"] == []
        assert client.get("/api/pages/stats", headers=headers).json()["data"]["total_pages"] == 0
    assert (
        len(
            client.get("/api/pages?scope=mine", headers=user("alice@feedmob.com")).json()["data"][
                "items"
            ]
        )
        == 1
    )


def test_defaults_are_per_account_and_explicit_visibility_overrides(monkeypatch):
    client, _, _ = make_client(monkeypatch)
    assert (
        client.put(
            "/api/me/sharing-defaults",
            headers=user("alice@feedmob.com"),
            json={
                "default_visibility": "restricted",
                "default_grants": {"users": ["bob@feedmob.com"]},
            },
        ).status_code
        == 200
    )
    assert (
        client.get("/api/me/sharing-defaults", headers=user("bob@feedmob.com")).json()["data"][
            "default_visibility"
        ]
        == "org"
    )
    data = {"owner": "reports", "description": "defaults", "html": "default page"}
    saved = client.post("/api/pages", headers=user("alice@feedmob.com"), json=data).json()["data"]
    assert saved["visibility"] == "restricted"
    assert saved["share_with"]["users"] == ["bob@feedmob.com"]
    override = client.post(
        "/api/pages", headers=user("alice@feedmob.com"), json={**data, "visibility": "private"}
    ).json()["data"]
    assert override["visibility"] == "private"
    assert override["share_with"]["users"] == []


def test_invalid_grants_are_rejected_atomically_and_group_edits_require_manager(monkeypatch):
    client, factory, _ = make_client(monkeypatch)
    group(client)
    assert (
        client.put(
            "/api/groups/team/members",
            headers=user("bob@feedmob.com"),
            json={
                "managers": ["bob@feedmob.com"],
                "members": [],
            },
        ).status_code
        == 403
    )
    for sharing in ({"groups": ["missing"]}, {"users": ["external@example.com"]}):
        result = client.post(
            "/api/pages",
            headers=user("alice@feedmob.com"),
            json={
                "owner": "reports",
                "html": "hello",
                "description": "invalid",
                "share_with": sharing,
            },
        )
        assert result.status_code == 422
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PageAsset)) == 0
    page = publish(client)
    invalid = client.put(
        f"/api/pages/{page['id']}",
        headers=user("alice@feedmob.com"),
        json={
            "title": "MUST ROLL BACK",
            "share_with": {"groups": ["missing"]},
        },
    )
    assert invalid.status_code == 422
    assert (
        client.get("/api/pages/reports/secret", headers=ADMIN).json()["data"]["title"] == "Secret"
    )


def test_legacy_pages_keep_org_access_but_private_legacy_pages_cannot_be_claimed(monkeypatch):
    client, factory, _ = make_client(monkeypatch)
    with factory() as db:
        page = PageAsset(
            owner="legacy",
            slug="old",
            html="old",
            submitter="admin-token@service-deployer.internal",
            description="old",
        )
        db.add(page)
        db.commit()
        page_id = page.id
    assert client.get("/p/legacy/old", headers=user("bob@feedmob.com")).status_code == 200
    assert (
        client.put(
            f"/api/pages/{page_id}/sharing",
            headers=user("bob@feedmob.com"),
            json={"visibility": "private"},
        ).status_code
        == 404
    )
    assert (
        client.put(
            f"/api/pages/{page_id}/sharing", headers=ADMIN, json={"visibility": "private"}
        ).status_code
        == 200
    )
    assert (
        client.post(f"/api/pages/{page_id}/claim", headers=user("bob@feedmob.com")).status_code
        == 404
    )


def test_legacy_sql_template_cannot_read_private_page_content(monkeypatch):
    client, _, _ = make_client(monkeypatch)
    publish(client, "private")
    other = client.post(
        "/api/pages",
        headers=user("bob@feedmob.com"),
        json={
            "owner": "bob",
            "slug": "query",
            "html": "{{ .leak.html }}",
            "description": "query",
            "data_sources": {"leak": "SELECT html FROM page_assets"},
        },
    )
    assert other.status_code == 201
    response = client.get("/p/bob/query", headers=user("bob@feedmob.com"))
    assert response.status_code == 500
    assert "Secret report" not in response.text
