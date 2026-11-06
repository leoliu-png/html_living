import os

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings
from app.database import create_tables
from app.routers.admin import router as admin_router
from app.routers.api_keys import router as api_keys_router
from app.routers.assets import router as assets_router
from app.routers.auth import router as auth_router
from app.routers.datasets import router as datasets_router
from app.routers.docs import router as docs_router
from app.routers.health import router as health_router
from app.routers.pages import router as pages_router
from app.routers.sharing import router as sharing_router

STATIC_DIR = os.environ.get(
    "STATIC_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"),
)

PUBLIC_PATHS = (
    "/health",
    "/api-docs",
    "/api-docs.json",
    "/api-docs.md",
    "/favicon.ico",
)

PUBLIC_PREFIXES = (
    "/assets/",
    "/auth/",
    "/uploads/",
)


def _extract_token(scope: Scope) -> str | None:
    # From query string
    qs = scope.get("query_string", b"").decode()
    for param in qs.split("&"):
        if param.startswith("token="):
            return param[6:]

    # From Authorization header
    for header_name, header_value in scope.get("headers", []):
        if header_name == b"authorization":
            auth = header_value.decode()
            if auth.startswith("Bearer "):
                return auth[7:]
    return None


def _token_matches_scope(scope: Scope) -> bool:
    if not settings.api_token:
        return False
    token = _extract_token(scope)
    return token == settings.api_token


def _api_key_matches_scope(scope: Scope) -> bool:
    token = _extract_token(scope)
    if not token:
        return False
    try:
        from app.database import SessionLocal
        from app.services.api_keys import authenticate_api_key

        with SessionLocal() as db:
            return authenticate_api_key(db, token) is not None
    except Exception:
        return False


def _has_session_scope(scope: Scope) -> bool:
    session = scope.get("session", {})
    return bool(session.get("user"))


def _is_page_dataset_path(path: str) -> bool:
    """`/p/{owner}/{slug}/data/{name}` authenticates itself with the page data
    token, because sandboxed page scripts cannot send the session cookie."""

    parts = path.strip("/").split("/")
    return len(parts) == 5 and parts[0] == "p" and parts[3] == "data"


class UnifiedAuthMiddleware:
    """Pure ASGI middleware — avoids BaseHTTPMiddleware's session compatibility issues."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        original_send = send

        async def private_send(message):
            if message["type"] == "http.response.start" and (
                path.startswith("/api/") or path.startswith("/p/")
            ):
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() not in (b"cache-control", b"vary")
                ]
                headers.extend(
                    [(b"cache-control", b"private, no-store"), (b"vary", b"Cookie, Authorization")]
                )
                message = {**message, "headers": headers}
            await original_send(message)

        send = private_send

        # Public paths — no auth required
        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            await self.app(scope, receive, send)
            return

        # API paths — accept API token OR session
        if path.startswith("/api/"):
            has_api_auth = (
                _token_matches_scope(scope)
                or _has_session_scope(scope)
                or _api_key_matches_scope(scope)
            )
            if has_api_auth:
                await self.app(scope, receive, send)
                return
            response = Response(
                "Unauthorized — provide token or login via /auth/login",
                status_code=401,
            )
            await response(scope, receive, send)
            return

        # Protected console routes — require Google session.
        if path in ("/", "/console", "/registry"):
            if _has_session_scope(scope):
                await self.app(scope, receive, send)
                return
            # Redirect to login
            login_url = f"/auth/login?next={path}"
            response = RedirectResponse(login_url, status_code=302)
            await response(scope, receive, send)
            return

        # Published pages — accept login session, admin token, or any active user API key.
        if path.startswith("/p/"):
            if _is_page_dataset_path(path):
                await self.app(scope, receive, send)
                return
            if (
                _has_session_scope(scope)
                or _token_matches_scope(scope)
                or _api_key_matches_scope(scope)
            ):
                await self.app(scope, receive, send)
                return
            login_url = f"/auth/login?next={path}"
            response = RedirectResponse(login_url, status_code=302)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def create_app() -> FastAPI:
    app = FastAPI(title="Service Deployer API")
    app.add_middleware(UnifiedAuthMiddleware)
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)
    app.include_router(health_router)
    app.include_router(docs_router)
    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(api_keys_router)
    app.include_router(sharing_router)
    # Registered before pages: `/api/pages/{page_id}/datasets` would otherwise be
    # swallowed by the two-segment `/api/pages/{owner}/{slug}` route.
    app.include_router(datasets_router)
    app.include_router(pages_router)
    app.include_router(assets_router)

    static_dir = os.path.abspath(STATIC_DIR)
    assets_dir = os.path.join(static_dir, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.on_event("startup")
    def on_startup() -> None:
        create_tables()
        from sqlalchemy import text as sa_text

        from app.database import engine as db_engine
        from app.services.sharing_migration import create_legacy_sql_views, migrate_page_sharing

        with db_engine.connect() as conn:
            migrate_page_sharing(conn)
            conn.execute(
                sa_text(
                    "ALTER TABLE page_assets ADD COLUMN IF NOT EXISTS "
                    "user_id VARCHAR(128) DEFAULT NULL"
                )
            )
            conn.execute(
                sa_text(
                    "ALTER TABLE page_assets ADD COLUMN IF NOT EXISTS "
                    "user_email VARCHAR(256) DEFAULT NULL"
                )
            )
            conn.execute(
                sa_text(
                    "ALTER TABLE page_assets ADD COLUMN IF NOT EXISTS "
                    "data_sources JSON DEFAULT NULL"
                )
            )
            conn.execute(
                sa_text(
                    "ALTER TABLE page_assets ADD COLUMN IF NOT EXISTS "
                    "data_token VARCHAR(64) DEFAULT NULL"
                )
            )
            conn.execute(
                sa_text(
                    "CREATE TABLE IF NOT EXISTS page_datasets ("
                    "id VARCHAR(36) PRIMARY KEY, "
                    "page_id VARCHAR(36) NOT NULL, "
                    "name VARCHAR(64) NOT NULL, "
                    "filename VARCHAR(255) NOT NULL, "
                    "format VARCHAR(16) NOT NULL, "
                    "content_type VARCHAR(128) NOT NULL, "
                    "storage_key VARCHAR(512) NOT NULL, "
                    "size_bytes INTEGER NOT NULL DEFAULT 0, "
                    "row_count INTEGER NOT NULL DEFAULT 0, "
                    "columns JSON DEFAULT NULL, "
                    "created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(), "
                    "updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(), "
                    "CONSTRAINT uq_page_datasets_page_name UNIQUE (page_id, name)"
                    ")"
                )
            )
            conn.execute(
                sa_text(
                    "CREATE INDEX IF NOT EXISTS ix_page_datasets_page_id ON page_datasets (page_id)"
                )
            )
            conn.execute(
                sa_text(
                    "CREATE TABLE IF NOT EXISTS api_keys ("
                    "id VARCHAR(36) PRIMARY KEY, "
                    "user_email VARCHAR(256) NOT NULL, "
                    "user_id VARCHAR(128) DEFAULT NULL, "
                    "name VARCHAR(120) NOT NULL, "
                    "key_hash VARCHAR(64) NOT NULL UNIQUE, "
                    "key_prefix VARCHAR(16) NOT NULL, "
                    "key_ciphertext TEXT DEFAULT NULL, "
                    "active BOOLEAN NOT NULL DEFAULT TRUE, "
                    "last_used_at TIMESTAMP WITH TIME ZONE DEFAULT NULL, "
                    "created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(), "
                    "revoked_at TIMESTAMP WITH TIME ZONE DEFAULT NULL"
                    ")"
                )
            )
            conn.execute(
                sa_text(
                    "ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS key_ciphertext TEXT DEFAULT NULL"
                )
            )
            conn.execute(
                sa_text(
                    "CREATE INDEX IF NOT EXISTS ix_api_keys_user_email ON api_keys (user_email)"
                )
            )
            conn.execute(
                sa_text("CREATE INDEX IF NOT EXISTS ix_api_keys_key_hash ON api_keys (key_hash)")
            )
            conn.execute(
                sa_text(
                    "CREATE TABLE IF NOT EXISTS app_settings ("
                    "key VARCHAR(80) PRIMARY KEY, "
                    "value TEXT NOT NULL DEFAULT '', "
                    "updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()"
                    ")"
                )
            )
            # After every page_assets column above exists.
            create_legacy_sql_views(conn)
            conn.commit()

    @app.get("/")
    @app.get("/console")
    @app.get("/registry")
    async def serve_spa(request: Request):
        index_path = os.path.join(static_dir, "index.html")
        if os.path.isdir(assets_dir) and os.path.isfile(index_path):
            return FileResponse(index_path)
        return {"message": "Frontend not built. Run: cd frontend && npm run build"}

    return app


app = create_app()
