from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ApiKey
from app.schemas import ApiKeyCreateRequest, ApiKeyCreateResponse, ApiKeyResponse, ApiResponse
from app.services.api_keys import (
    ApiKeyRevealError,
    create_api_key,
    list_api_keys,
    reveal_api_key,
    revoke_api_key,
)

router = APIRouter(tags=["api-keys"])
DbSession = Annotated[Session, Depends(get_db)]


def _session_user(request: Request) -> dict:
    user = request.session.get("user") if hasattr(request, "session") else None
    if not user or not user.get("email"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login session is required to manage API keys.",
        )
    return user


def _to_response(api_key: ApiKey) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        created_at=api_key.created_at,
        last_used_at=api_key.last_used_at,
        revoked_at=api_key.revoked_at,
        active=api_key.active,
    )


@router.get("/api/keys", response_model=ApiResponse[list[ApiKeyResponse]])
def list_keys(request: Request, db: DbSession) -> ApiResponse[list[ApiKeyResponse]]:
    user = _session_user(request)
    items = list_api_keys(db, user_email=user["email"])
    return ApiResponse(data=[_to_response(item) for item in items])


@router.post(
    "/api/keys",
    response_model=ApiResponse[ApiKeyCreateResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_key(
    payload: ApiKeyCreateRequest,
    request: Request,
    db: DbSession,
) -> ApiResponse[ApiKeyCreateResponse]:
    user = _session_user(request)
    api_key, key = create_api_key(
        db,
        user_email=user["email"],
        user_id=user.get("sub") or None,
        name=payload.name,
    )
    return ApiResponse(
        msg="api key created",
        data=ApiKeyCreateResponse(key=key, item=_to_response(api_key)),
    )


@router.get(
    "/api/keys/{key_id}/reveal",
    response_model=ApiResponse[ApiKeyCreateResponse],
)
def reveal_key(key_id: str, request: Request, db: DbSession) -> ApiResponse[ApiKeyCreateResponse]:
    user = _session_user(request)
    try:
        api_key, key = reveal_api_key(db, key_id=key_id, user_email=user["email"])
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ApiKeyRevealError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(
        msg="api key revealed",
        data=ApiKeyCreateResponse(key=key, item=_to_response(api_key)),
    )


@router.delete("/api/keys/{key_id}", response_model=ApiResponse[ApiKeyResponse])
def revoke_key(key_id: str, request: Request, db: DbSession) -> ApiResponse[ApiKeyResponse]:
    user = _session_user(request)
    try:
        api_key = revoke_api_key(db, key_id=key_id, user_email=user["email"])
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ApiResponse(msg="api key revoked", data=_to_response(api_key))
