from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth_context import get_request_actor, parse_email_list
from app.config import settings
from app.database import get_db
from app.models import PageAsset
from app.models.sharing import SharingAuditLog
from app.schemas import AdminSettingsResponse, AdminSettingsUpdateRequest, ApiResponse
from app.services.pages import build_public_page_url
from app.services.settings import (
    SUBMITTER_ALLOWLIST_KEY,
    get_submitter_allowlist_value,
    set_setting,
)
from app.services.templates import legacy_sql_mode

router = APIRouter(tags=["admin"])
DbSession = Annotated[Session, Depends(get_db)]


def require_admin_actor(request: Request, db: Session) -> None:
    actor = get_request_actor(request, db)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
    if not actor.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required.")


@router.get("/api/admin/settings", response_model=ApiResponse[AdminSettingsResponse])
def get_admin_settings(request: Request, db: DbSession) -> ApiResponse[AdminSettingsResponse]:
    require_admin_actor(request, db)
    allowlist = sorted(parse_email_list(get_submitter_allowlist_value(db)))
    return ApiResponse(data=AdminSettingsResponse(submitter_allowlist=allowlist))


@router.put("/api/admin/settings", response_model=ApiResponse[AdminSettingsResponse])
def update_admin_settings(
    payload: AdminSettingsUpdateRequest,
    request: Request,
    db: DbSession,
) -> ApiResponse[AdminSettingsResponse]:
    require_admin_actor(request, db)
    serialized = ",".join(payload.submitter_allowlist)
    set_setting(db, SUBMITTER_ALLOWLIST_KEY, serialized)
    return ApiResponse(
        msg="admin settings updated",
        data=AdminSettingsResponse(submitter_allowlist=payload.submitter_allowlist),
    )


@router.get("/api/admin/legacy-sql-pages", response_model=ApiResponse[dict])
def list_legacy_sql_pages(request: Request, db: DbSession) -> ApiResponse[dict]:
    """Inventory of pages that still render legacy SQL `data_sources` templates.

    Run before rollout: in `disabled` mode these pages answer 500 until they are
    migrated to page datasets or the sandboxed legacy SQL role is configured.
    """
    require_admin_actor(request, db)
    pages = db.scalars(
        select(PageAsset).where(PageAsset.data_sources.is_not(None)).order_by(PageAsset.owner)
    ).all()
    items = [
        {
            "id": page.id,
            "owner": page.owner,
            "slug": page.slug,
            "title": page.title,
            "url": build_public_page_url(settings.public_base_url, page.owner, page.slug),
            "visibility": page.visibility,
            "user_email": page.user_email,
            "data_source_names": sorted(page.data_sources),
            "updated_at": page.updated_at.isoformat() if page.updated_at else None,
        }
        for page in pages
        if page.data_sources
    ]
    return ApiResponse(data={"mode": legacy_sql_mode(), "total": len(items), "items": items})


@router.get("/api/admin/sharing-audit", response_model=ApiResponse[dict])
def list_sharing_audit(
    request: Request,
    db: DbSession,
    page_id: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None, max_length=40),
    actor: Optional[str] = Query(default=None, max_length=256),
    limit: int = Query(default=100, ge=1, le=500),
) -> ApiResponse[dict]:
    """Admin view of `sharing_audit_log`, newest first, with optional filters."""
    require_admin_actor(request, db)
    query = select(SharingAuditLog).order_by(SharingAuditLog.at.desc()).limit(limit)
    if page_id:
        query = query.where(SharingAuditLog.page_id == page_id)
    if action:
        query = query.where(SharingAuditLog.action == action)
    if actor:
        query = query.where(SharingAuditLog.actor == actor.strip().lower())
    rows = db.scalars(query).all()
    names = {
        page.id: f"{page.owner}/{page.slug}"
        for page in db.scalars(
            select(PageAsset).where(PageAsset.id.in_({r.page_id for r in rows if r.page_id}))
        )
    }
    from app.routers.sharing import audit_items

    return ApiResponse(data={"items": audit_items(rows, names)})
