from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response

from app.api_docs_catalog import api_docs_markdown, load_api_docs_catalog

router = APIRouter(tags=["docs"])

STATIC_DIR = os.environ.get(
    "STATIC_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "dist"),
)


def _accept_values(accept_header: str) -> list[str]:
    values: list[str] = []
    for part in accept_header.split(","):
        media = part.split(";", 1)[0].strip().lower()
        if media:
            values.append(media)
    return values


def _wants_html(accept_header: str) -> bool:
    accepts = _accept_values(accept_header)
    if not accepts:
        return False
    # Browsers send text/html. curl defaults to */* and should get machine-readable docs.
    if any(value == "text/html" or value.startswith("text/html") for value in accepts):
        return True
    if any(value == "application/xhtml+xml" for value in accepts):
        return True
    return False


def _wants_json(accept_header: str, format_param: Optional[str]) -> bool:
    if format_param and format_param.lower() in {"json", "application/json"}:
        return True
    accepts = _accept_values(accept_header)
    if "application/json" in accepts:
        # Prefer JSON when explicitly listed, even alongside text/html if format not html-only.
        # Browsers usually put text/html first; only force JSON when application/json is first
        # or text/html is absent.
        if not _wants_html(accept_header):
            return True
        if accepts and accepts[0] == "application/json":
            return True
    return False


def _serve_spa() -> Response:
    static_dir = os.path.abspath(STATIC_DIR)
    index_path = os.path.join(static_dir, "index.html")
    assets_dir = os.path.join(static_dir, "assets")
    if os.path.isdir(assets_dir) and os.path.isfile(index_path):
        return FileResponse(index_path)
    return JSONResponse(
        {
            "message": "Frontend not built. Run: cd frontend && npm run build",
            "hint": "Use /api-docs.json or curl /api-docs without Accept: text/html for machine-readable docs.",
            "endpoints": load_api_docs_catalog()["endpoints"],
            "version": load_api_docs_catalog()["version"],
        }
    )


@router.get("/api-docs.json")
def api_docs_json() -> JSONResponse:
    return JSONResponse(content=load_api_docs_catalog())


@router.get("/api-docs.md", response_class=PlainTextResponse)
def api_docs_md() -> PlainTextResponse:
    return PlainTextResponse(content=api_docs_markdown(), media_type="text/markdown; charset=utf-8")


@router.get("/api-docs")
def api_docs(
    request: Request,
    format: Optional[str] = Query(default=None, description="json | md | html"),
) -> Response:
    """
    Human SPA for browsers; machine-readable body for agents/curl by default.

    - Browser (Accept: text/html) -> SPA shell
    - curl / agents (Accept: */* or application/json) -> markdown or JSON
    - ?format=json|md|html to force a representation
    """
    accept = request.headers.get("accept", "*/*")
    fmt = (format or "").strip().lower()

    if fmt in {"html", "spa"}:
        return _serve_spa()
    if fmt in {"json", "application/json"} or _wants_json(accept, fmt):
        return JSONResponse(content=load_api_docs_catalog())
    if fmt in {"md", "markdown", "text"}:
        return PlainTextResponse(content=api_docs_markdown(), media_type="text/markdown; charset=utf-8")
    if _wants_html(accept):
        return _serve_spa()

    # Default for curl/agents: readable markdown with full endpoint catalog.
    return PlainTextResponse(content=api_docs_markdown(), media_type="text/markdown; charset=utf-8")
