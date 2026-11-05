from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth_context import get_request_actor, parse_email_list
from app.database import get_db
from app.schemas import AdminSettingsResponse, AdminSettingsUpdateRequest, ApiResponse
from app.services.settings import (
    SUBMITTER_ALLOWLIST_KEY,
    get_submitter_allowlist_value,
    set_setting,
)

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
