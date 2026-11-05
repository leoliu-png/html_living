"""Page Publisher MCP server — exposes publishing tools via HTTP/SSE.

Remote agents connect via SSE: http://<host>:30002/sse
Authentication: Authorization: Bearer <token> header required.

Environment:
  PUBLISHER_URL   — backend API base URL
  PUBLISHER_TOKEN — token to call backend API
  MCP_AUTH_TOKEN  — token that remote agents must provide (falls back to PUBLISHER_TOKEN)
"""

import os
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

PUBLISHER_URL = os.environ.get("PUBLISHER_URL", "http://127.0.0.1:30001")
PUBLISHER_TOKEN = os.environ.get("PUBLISHER_TOKEN", "")
MCP_AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "") or PUBLISHER_TOKEN

mcp = FastMCP("page-publisher", host="0.0.0.0", port=30002)


class McpAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not MCP_AUTH_TOKEN:
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != MCP_AUTH_TOKEN:
            return Response(status_code=401, content="Unauthorized")
        return await call_next(request)


def _auth_headers() -> dict:
    if not PUBLISHER_TOKEN:
        return {}
    return {"Authorization": f"Bearer {PUBLISHER_TOKEN}"}


# ── tools ────────────────────────────────────────────────────────────────────


@mcp.tool()
def publish_page(
    html: str,
    owner: str,
    submitter: str,
    description: str,
    slug: Optional[str] = None,
    title: Optional[str] = None,
) -> dict:
    """Publish an HTML page to the service deployer.

    Args:
        html: Full HTML content of the page
        owner: Owner/group name (lowercase letters, numbers, hyphens)
        submitter: Name or email of the person submitting
        description: Short description of the page
        slug: URL slug — auto-generated if omitted
        title: Page title
    """
    body = {
        "html": html,
        "owner": owner,
        "submitter": submitter,
        "description": description,
    }
    if slug:
        body["slug"] = slug
    if title:
        body["title"] = title

    with httpx.Client(timeout=30) as client:
        r = client.post(
            f"{PUBLISHER_URL}/api/pages",
            json=body,
            headers=_auth_headers(),
        )
        r.raise_for_status()
        return r.json()


@mcp.tool()
def list_pages(
    page: int = 1,
    page_size: int = 20,
    q: Optional[str] = None,
) -> dict:
    """List and search published pages.

    Args:
        page: Page number (1-based)
        page_size: Results per page (1-100)
        q: Search keyword (matches owner, slug, title, submitter, description)
    """
    params = {"page": page, "page_size": page_size}
    if q:
        params["q"] = q

    with httpx.Client(timeout=30) as client:
        r = client.get(
            f"{PUBLISHER_URL}/api/pages",
            params=params,
            headers=_auth_headers(),
        )
        r.raise_for_status()
        return r.json()


@mcp.tool()
def get_page_stats() -> dict:
    """Return page statistics: total pages, top owners, top submitters."""
    with httpx.Client(timeout=30) as client:
        r = client.get(
            f"{PUBLISHER_URL}/api/pages/stats",
            headers=_auth_headers(),
        )
        r.raise_for_status()
        return r.json()


@mcp.tool()
def get_page_detail(owner: str, slug: str) -> dict:
    """Get full metadata for a specific published page.

    Args:
        owner: Owner/group name
        slug: Page slug
    """

    with httpx.Client(timeout=30) as client:
        r = client.get(
            f"{PUBLISHER_URL}/api/pages/{owner}/{slug}",
            headers=_auth_headers(),
        )
        r.raise_for_status()
        return r.json()


@mcp.tool()
def delete_page(page_id: str) -> dict:
    """Delete a published page by its ID.

    Args:
        page_id: The UUID of the page to delete
    """
    with httpx.Client(timeout=30) as client:
        r = client.delete(
            f"{PUBLISHER_URL}/api/pages/{page_id}",
            headers=_auth_headers(),
        )
        r.raise_for_status()
        return r.json()


# ── entry ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    app = mcp.streamable_http_app()
    app.add_middleware(McpAuthMiddleware)
    uvicorn.run(app, host="0.0.0.0", port=30002)
