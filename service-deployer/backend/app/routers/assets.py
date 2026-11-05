from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.auth_context import get_request_actor
from app.database import get_db
from app.services import storage

router = APIRouter(tags=["assets"])
DbSession = Annotated[Session, Depends(get_db)]

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp"}


def _safe_user_dir(value: str) -> str:
    safe = "".join(c for c in value if c.isalnum() or c in "-_")
    return safe[:64] if safe else "anonymous"


def _get_user_dir(request: Request, db: Session) -> str:
    actor = get_request_actor(request, db)
    if actor and actor.email:
        return _safe_user_dir(actor.email.replace("@", "_"))
    user_id = request.headers.get("X-User-Id")
    if user_id:
        return _safe_user_dir(user_id)
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if token:
        import hashlib

        return hashlib.sha256(token.encode()).hexdigest()[:16]
    return "anonymous"


@router.post("/api/assets/upload", status_code=status.HTTP_201_CREATED)
async def upload_asset(request: Request, file: UploadFile, db: DbSession):
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No file selected")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file type: {ext}. "
                f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            ),
        )

    user_dir = _get_user_dir(request, db)
    unique_name = f"{uuid.uuid4().hex}{ext}"
    key = f"uploads/{user_dir}/{unique_name}"

    contents = await file.read()

    if len(contents) > 50 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large (max 50 MB)",
        )

    content_type = file.content_type or "application/octet-stream"
    storage.put_object(key, contents, content_type)

    url = f"/uploads/{user_dir}/{unique_name}"

    return {
        "url": url,
        "full_url": storage.public_url(key),
        "filename": file.filename,
        "size": len(contents),
    }
