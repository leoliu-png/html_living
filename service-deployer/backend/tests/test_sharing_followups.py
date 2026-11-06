"""AI-2871 follow-ups: data credential secrecy, grant-list privacy, namespace
defaults, legacy SQL inventory/sandbox and legacy claim auditing."""

import base64
import json
import os
import zlib
from uuid import uuid4

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from test_page_datasets import make_client, upload_csv

from app.config import settings
from app.database import Base
from app.models import PageAsset
from app.models.sharing import SharingAuditLog
from app.services import templates
from app.services.sharing_migration import create_legacy_sql_views

ADMIN = {"Authorization": "Bearer admin-token"}


def user(email):
    return {**ADMIN, "X-User-Email": email, "X-User-Id": email.split("@")[0]}


def publish(client, who="alice@feedmob.com", slug="p1", owner="reports", **extra):
    response = client.post(
        "/api/pages",
        headers=user(who),
        json={"owner": owner, "slug": slug, "description": "d", "html": "<b>x</b>", **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def create_group(client, slug="team", manager="alice@feedmob.com", members=()):
    response = client.post(
        "/api/groups",
        headers=user(manager),
        json={"slug": slug, "name": slug, "managers": [manager], "members": list(members)},
    )
    assert response.status_code == 201, response.text


def manifest_token(html):
    manifest = BeautifulSoup(html, "html.parser").find(id="page-data-manifest").string
    return json.loads(manifest)["token"]


def decode_unverified(token):
    compressed = token.startswith(".")
    payload = token.lstrip(".").split(".")[0]
    raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    return json.loads(zlib.decompress(raw) if compressed else raw)


def audit_actions(factory, action):
    with factory() as db:
        return db.scalars(select(SharingAuditLog).where(SharingAuditLog.action == action)).all()


def test_viewer_credential_does_not_reveal_the_raw_page_data_token(monkeypatch):
    client, factory, _ = make_client(monkeypatch)
    page = publish(client)
    upload_csv(client, page["id"])
    token = manifest_token(client.get("/p/reports/p1", headers=user("bob@feedmob.com")).text)
    with factory() as db:
        raw = db.get(PageAsset, page["id"]).data_token
    claims = decode_unverified(token)
    assert raw not in json.dumps(claims)
    # Neither the readable revision nor anything else in the payload is a usable `k`.
    for value in (claims["revision"], token.split(".")[0]):
        assert client.get("/p/reports/p1/data/spend", params={"k": value}).status_code == 401
    assert client.get("/p/reports/p1/data/spend", params={"k": token}).status_code == 200
    # The owner's legacy raw token keeps working for org pages (compatibility).
    assert client.get("/p/reports/p1/data/spend", params={"k": raw}).status_code == 200


def test_grant_lists_are_only_returned_to_owners_and_admins(monkeypatch):
    client, _, _ = make_client(monkeypatch)
    monkeypatch.setattr(settings, "admin_emails", "admin@feedmob.com")
    shared = {"users": ["bob@feedmob.com", "carol@feedmob.com"], "groups": []}
    publish(client, visibility="restricted", share_with=shared)
    for email, expected in [
        ("alice@feedmob.com", shared["users"]),
        ("admin@feedmob.com", shared["users"]),
        ("bob@feedmob.com", []),
    ]:
        detail = client.get("/api/pages/reports/p1", headers=user(email)).json()["data"]
        assert detail["visibility"] == "restricted"
        assert detail["share_with"]["users"] == expected, email
        items = client.get("/api/pages", headers=user(email)).json()["data"]["items"]
        assert items[0]["share_with"]["users"] == expected, email


def test_namespace_defaults_take_precedence_and_need_a_group_manager(monkeypatch):
    client, factory, _ = make_client(monkeypatch)
    create_group(client, "ken-team", manager="ken@feedmob.com", members=["amy@feedmob.com"])
    client.put(
        "/api/me/sharing-defaults",
        headers=user("ken@feedmob.com"),
        json={"default_visibility": "private", "default_grants": {}},
    )
    body = {"default_visibility": "restricted", "default_grants": {"groups": ["ken-team"]}}
    path = "/api/namespaces/ken-team/sharing-defaults"
    assert client.put(path, headers=user("amy@feedmob.com"), json=body).status_code == 403
    assert client.put(path, headers=user("ken@feedmob.com"), json=body).status_code == 200
    assert (
        client.put(
            "/api/namespaces/other/sharing-defaults", headers=user("ken@feedmob.com"), json=body
        ).status_code
        == 403
    )
    effective = client.get(
        "/api/me/sharing-defaults", params={"owner": "ken-team"}, headers=user("ken@feedmob.com")
    ).json()["data"]
    assert (effective["source"], effective["default_visibility"]) == ("namespace", "restricted")

    under_team = publish(client, who="ken@feedmob.com", owner="ken-team")
    assert under_team["visibility"] == "restricted"
    assert under_team["share_with"]["groups"] == ["ken-team"]
    assert client.get("/p/ken-team/p1", headers=user("amy@feedmob.com")).status_code == 200
    elsewhere = publish(client, who="ken@feedmob.com", owner="ken")
    assert elsewhere["visibility"] == "private"
    # Explicit sharing still overrides any default.
    explicit = publish(client, who="ken@feedmob.com", owner="ken-team", slug="p2", visibility="org")
    assert explicit["visibility"] == "org"

    listed = client.get("/api/namespaces/sharing-defaults", headers=user("amy@feedmob.com"))
    assert [i["owner"] for i in listed.json()["data"]["items"]] == ["ken-team"]
    assert client.delete(path, headers=user("ken@feedmob.com")).status_code == 200
    after = client.get(
        "/api/me/sharing-defaults", params={"owner": "ken-team"}, headers=user("ken@feedmob.com")
    ).json()["data"]
    assert (after["source"], after["default_visibility"]) == ("account", "private")
    assert len(audit_actions(factory, "namespace_defaults_changed")) == 1
    assert len(audit_actions(factory, "namespace_defaults_deleted")) == 1


def test_namespace_defaults_reject_unknown_groups_and_bad_names(monkeypatch):
    client, _, _ = make_client(monkeypatch)
    bad_group = {"default_visibility": "restricted", "default_grants": {"groups": ["missing"]}}
    assert (
        client.put("/api/namespaces/ops/sharing-defaults", headers=ADMIN, json=bad_group)
    ).status_code == 422
    assert (
        client.put(
            "/api/namespaces/Bad_Name/sharing-defaults",
            headers=ADMIN,
            json={"default_visibility": "org", "default_grants": {}},
        )
    ).status_code == 422


def test_sql_data_sources_are_rejected_on_update_and_inventoried_for_admins(monkeypatch):
    client, factory, _ = make_client(monkeypatch)
    page = publish(client)
    sql = {"rows": "SELECT 1 AS n"}
    updated = client.put(
        f"/api/pages/{page['id']}", headers=user("alice@feedmob.com"), json={"data_sources": sql}
    )
    assert updated.status_code == 422
    with factory() as db:
        db.add(
            PageAsset(
                owner="legacy",
                slug="sql",
                html="{{ .rows.n }}",
                description="sql",
                submitter="admin-token@service-deployer.internal",
                data_sources=sql,
            )
        )
        db.commit()
    assert (
        client.get("/api/admin/legacy-sql-pages", headers=user("alice@feedmob.com")).status_code
        == 403
    )
    inventory = client.get("/api/admin/legacy-sql-pages", headers=ADMIN).json()["data"]
    assert inventory["mode"] == "disabled"
    assert [(i["owner"], i["slug"], i["data_source_names"]) for i in inventory["items"]] == [
        ("legacy", "sql", ["rows"])
    ]


def test_legacy_page_claims_are_audited_with_the_previous_identity(monkeypatch):
    client, factory, _ = make_client(monkeypatch)
    with factory() as db:
        for slug in ("a", "b"):
            db.add(
                PageAsset(
                    owner="legacy",
                    slug=slug,
                    html="old",
                    description="old",
                    submitter="admin-token@service-deployer.internal",
                )
            )
        db.commit()
        ids = {p.slug: p.id for p in db.scalars(select(PageAsset))}
    assert (
        client.post(f"/api/pages/{ids['a']}/claim", headers=user("bob@feedmob.com")).status_code
        == 200
    )
    assert (
        client.put(
            f"/api/pages/{ids['b']}", headers=user("carol@feedmob.com"), json={"title": "mine"}
        ).status_code
        == 200
    )
    rows = sorted(audit_actions(factory, "page_claimed"), key=lambda r: r.actor)
    assert [r.actor for r in rows] == ["bob@feedmob.com", "carol@feedmob.com"]
    assert all(r.before["submitter"] == "admin-token@service-deployer.internal" for r in rows)
    assert rows[1].after["user_email"] == "carol@feedmob.com"


@pytest.mark.skipif(
    not os.environ.get("SHARING_TEST_DATABASE_URL"), reason="Requires local PostgreSQL"
)
def test_postgres_legacy_sql_sandbox_only_sees_org_listed_pages(monkeypatch):
    """Needs a superuser URL: it creates a throwaway login role for the sandbox."""
    admin_url = os.environ["SHARING_TEST_DATABASE_URL"]
    engine = create_engine(admin_url)
    schema = "sandbox_test_" + uuid4().hex[:12]
    role = "legacy_sql_" + uuid4().hex[:8]
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = engine.execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(scoped)
        factory = sessionmaker(bind=scoped)
        with factory() as db:
            for slug, visibility, listed in [
                ("open", "org", True),
                ("hidden", "org", False),
                ("secret", "private", True),
            ]:
                db.add(
                    PageAsset(
                        owner="t",
                        slug=slug,
                        html=f"html-{slug}",
                        description="d",
                        submitter="a@feedmob.com",
                        visibility=visibility,
                        listed=listed,
                        data_token="raw-token-" + slug,
                    )
                )
            db.commit()
        with engine.begin() as connection:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            create_legacy_sql_views(connection)
            connection.execute(text(f"CREATE ROLE {role} LOGIN PASSWORD 'sandbox'"))
            connection.execute(text(f"GRANT USAGE ON SCHEMA legacy_sql TO {role}"))
            connection.execute(text(f"GRANT SELECT ON legacy_sql.page_assets TO {role}"))
        sandbox_url = make_url(admin_url).set(username=role, password="sandbox")
        monkeypatch.setattr(settings, "allow_legacy_sql_data_sources", False)
        monkeypatch.setattr(
            settings, "legacy_sql_database_url", sandbox_url.render_as_string(False)
        )
        assert templates.legacy_sql_mode() == "sandbox"

        rendered = templates.render_template(
            "{% for p in pages %}[{{ .p.html }}]{% endfor %}",
            {"pages": "SELECT html FROM page_assets ORDER BY slug"},
            db=None,
        )
        assert rendered == "[html-open]"
        attacks = [
            f'SELECT html FROM "{schema}".page_assets',
            "SELECT data_token FROM page_assets",
            f'SELECT key_hash FROM "{schema}".api_keys',
            # Try to climb back to the application role inside one statement.
            f"SELECT set_config('role', '{make_url(admin_url).username}', true), "
            f"query_to_xml('select html from \"{schema}\".page_assets', true, true, '')",
            "SELECT 1 AS n LIMIT 1; DELETE FROM page_assets",
            "SELECT pg_sleep(10)",
        ]
        monkeypatch.setattr(settings, "legacy_sql_statement_timeout_ms", 300)
        for query in attacks:
            with pytest.raises(templates.DataSourceError):
                templates.render_template("{{ .q }}", {"q": query}, db=None)
    finally:
        templates._sandbox_engine.cache_clear()
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            connection.execute(text("DROP SCHEMA IF EXISTS legacy_sql CASCADE"))
            connection.execute(text(f"DROP ROLE IF EXISTS {role}"))
        engine.dispose()
