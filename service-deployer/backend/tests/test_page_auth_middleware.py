import os

os.environ.setdefault("R2_ACCOUNT_ID", "test-r2-account")
os.environ.setdefault("R2_ACCESS_KEY_ID", "test-r2-access-key")
os.environ.setdefault("R2_SECRET_ACCESS_KEY", "test-r2-secret-key")
os.environ.setdefault("R2_BUCKET_NAME", "test-r2-bucket")
os.environ.setdefault("R2_PUBLIC_URL", "https://assets.example.test")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from app.config import settings
from app.database import Base, get_db
from app.main import create_app
from app.models import PageAsset
from app.services.api_keys import create_api_key, revoke_api_key


def make_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)

    def override_db():
        with session_factory() as session:
            yield session

    monkeypatch.setattr("app.main.create_tables", lambda: None)
    monkeypatch.setattr("app.database.SessionLocal", session_factory)
    monkeypatch.setattr(settings, "api_token", "admin-token")
    monkeypatch.setattr(settings, "session_secret", "test-session-secret")

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    return TestClient(app), session_factory


def seed_page(session_factory) -> None:
    with session_factory() as db:
        db.add(
            PageAsset(
                owner="reports",
                slug="weekly",
                title="Weekly",
                submitter="alice@feedmob.com",
                description="Weekly report",
                html="<html><body><h1>Weekly report</h1></body></html>",
            )
        )
        db.commit()


def test_published_page_without_auth_redirects_to_login(monkeypatch) -> None:
    client, session_factory = make_client(monkeypatch)
    seed_page(session_factory)

    response = client.get("/p/reports/weekly", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login?next=/p/reports/weekly"


def test_published_page_accepts_admin_token(monkeypatch) -> None:
    client, session_factory = make_client(monkeypatch)
    seed_page(session_factory)

    response = client.get("/p/reports/weekly?token=admin-token")

    assert response.status_code == 200
    assert "Weekly report" in response.text
    assert "feedmob-source-toolbar" in response.text


def test_published_page_accepts_any_active_user_api_key(monkeypatch) -> None:
    client, session_factory = make_client(monkeypatch)
    seed_page(session_factory)
    with session_factory() as db:
        _, api_key = create_api_key(
            db,
            user_email="bob@feedmob.com",
            user_id="bob-sub",
            name="Viewer",
        )

    response = client.get("/p/reports/weekly", headers={"Authorization": f"Bearer {api_key}"})

    assert response.status_code == 200
    assert "Weekly report" in response.text
    with session_factory() as db:
        stored = db.scalar(select(PageAsset).where(PageAsset.owner == "reports"))
        assert stored is not None
        assert stored.submitter == "alice@feedmob.com"


def test_published_page_rejects_revoked_api_key(monkeypatch) -> None:
    client, session_factory = make_client(monkeypatch)
    seed_page(session_factory)
    with session_factory() as db:
        api_key_model, api_key = create_api_key(
            db,
            user_email="carol@feedmob.com",
            user_id="carol-sub",
            name="Revoked viewer",
        )
        revoke_api_key(db, key_id=api_key_model.id, user_email="carol@feedmob.com")

    response = client.get(
        "/p/reports/weekly",
        headers={"Authorization": f"Bearer {api_key}"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login?next=/p/reports/weekly"


def test_console_still_requires_login_session_even_with_token(monkeypatch) -> None:
    client, _ = make_client(monkeypatch)

    response = client.get("/console?token=admin-token", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login?next=/console"


def test_api_docs_is_public(monkeypatch) -> None:
    client, _ = make_client(monkeypatch)

    response = client.get("/api-docs", follow_redirects=False)

    assert response.status_code == 200


def test_api_docs_curl_default_returns_markdown_catalog(monkeypatch) -> None:
    client, _ = make_client(monkeypatch)

    # curl default Accept is */* — agents should get readable docs, not an empty SPA shell.
    response = client.get("/api-docs", headers={"Accept": "*/*"}, follow_redirects=False)

    assert response.status_code == 200
    assert "text/markdown" in response.headers["content-type"]
    assert "Service Deployer API" in response.text
    assert "POST /api/pages" in response.text or "/api/pages" in response.text
    assert "<div id=\"root\"></div>" not in response.text


def test_api_docs_browser_accept_still_serves_spa_or_fallback(monkeypatch) -> None:
    client, _ = make_client(monkeypatch)

    response = client.get(
        "/api-docs",
        headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    # Either built SPA HTML or JSON fallback with catalog when frontend is missing.
    body = response.text
    assert ("root" in body) or ("endpoints" in body) or ("Frontend not built" in body)


def test_api_docs_format_json_query_works(monkeypatch) -> None:
    client, _ = make_client(monkeypatch)

    response = client.get("/api-docs?format=json", follow_redirects=False)

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == 1
    assert len(payload["endpoints"]) >= 1


def test_api_docs_json_is_public_and_machine_readable(monkeypatch) -> None:
    client, _ = make_client(monkeypatch)

    response = client.get("/api-docs.json", follow_redirects=False)

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == 1
    assert isinstance(payload["endpoints"], list)
    assert len(payload["endpoints"]) >= 1
    assert {"id", "method", "path", "curlExample"} <= set(payload["endpoints"][0])


def test_api_docs_markdown_is_public(monkeypatch) -> None:
    client, _ = make_client(monkeypatch)

    response = client.get("/api-docs.md", follow_redirects=False)

    assert response.status_code == 200
    assert "text/markdown" in response.headers["content-type"]
    assert "Service Deployer API" in response.text
    assert "/api/pages" in response.text
