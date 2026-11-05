# Backend

Python backend for the service deployer control plane.

Current scope:

- Provide the core HTTP API.
- Own persistence and future registration/authentication concerns.
- Keep Coolify integration behind an adapter boundary.

## Current Scope

The first backend slice supports publishing raw HTML into one shared service:

- `POST /api/pages`: publish an HTML page asset.
- `GET /api/pages`: list submitted page assets.
- `GET /api/pages/{slug}`: fetch submission metadata.
- `GET /p/{slug}`: render the submitted HTML page.

The service is designed to be deployed once on Coolify. Individual pages are served behind route
paths instead of creating one Coolify application per page.

## Publish API

```http
POST /api/pages
Content-Type: application/json
```

```json
{
  "html": "<!doctype html><html><body>Hello</body></html>",
  "owner": "leo",
  "description": "Demo page for internal review",
  "slug": "demo-page",
  "title": "Demo Page"
}
```

Rules:

- `description` is required.
- `owner` is required and is used as the route group.
- `submitter` is set by the authenticated user email. Request bodies cannot override it.
- `slug` is optional.
- If `slug` is omitted, the system generates a unique 10-character suffix.
- If `slug` is provided, it must use lowercase letters, numbers, and hyphens.
- Duplicate slugs return `409 Conflict`.
- The backend records submit time, submit IP, and User-Agent automatically.

Response:

```json
{
  "code": 0,
  "msg": "page published",
  "data": {
    "id": "page uuid",
    "owner": "leo",
    "slug": "demo-page",
    "url": "http://127.0.0.1:8000/p/leo/demo-page",
    "created_at": "2026-05-14T12:00:00Z"
  }
}
```

Console list endpoint:

```http
GET /api/pages
```

All API JSON responses use the same envelope:

```json
{
  "code": 0,
  "msg": "ok",
  "data": {}
}
```

## Local Configuration

The backend can run directly on the local machine. Docker is not required for Python development.
Docker is only a convenience option if you want to start PostgreSQL locally, and it is also useful
later when packaging the service for Coolify.

Copy `.env.example` to `.env` and adjust values if needed.

```env
DATABASE_URL=postgresql+psycopg://service_deployer:service_deployer@localhost:5432/service_deployer
PUBLIC_BASE_URL=http://127.0.0.1:8000
```

The current environment must provide PostgreSQL in some form: a local install, a remote database, or
the optional `docker-compose.yml`.

### Local PostgreSQL With Postgres.app

This project has been verified locally with Postgres.app `18.4`.

```bash
/Applications/Postgres.app/Contents/Versions/latest/bin/initdb -D data/postgres --encoding=UTF8 --locale=C
/Applications/Postgres.app/Contents/Versions/latest/bin/pg_ctl -D data/postgres -l data/postgres.log start
/Applications/Postgres.app/Contents/Versions/latest/bin/psql -h localhost -p 5432 -d postgres -c "CREATE USER service_deployer WITH PASSWORD 'service_deployer';"
/Applications/Postgres.app/Contents/Versions/latest/bin/createdb -h localhost -p 5432 -O service_deployer service_deployer
```

Stop the local database:

```bash
/Applications/Postgres.app/Contents/Versions/latest/bin/pg_ctl -D data/postgres stop
```

Seed local console data:

```bash
PYTHONPATH=backend .venv/bin/python backend/scripts/seed_pages.py
```
