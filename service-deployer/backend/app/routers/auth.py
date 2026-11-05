from __future__ import annotations

import secrets
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse

from app.config import settings

router = APIRouter(tags=["auth"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def _admin_emails() -> set[str]:
    return {email.strip().lower() for email in settings.admin_emails.split(",") if email.strip()}


def _google_redirect_uri() -> str:
    return f"{settings.public_base_url.rstrip('/')}/auth/google/callback"


def _build_google_auth_url(state: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": _google_redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    if settings.allowed_domain:
        params["hd"] = settings.allowed_domain
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


@router.get("/auth/login")
async def login(request: Request, next: Optional[str] = Query(default=None, alias="next")):
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state
    request.session["oauth_next"] = next or "/"
    return RedirectResponse(_build_google_auth_url(state), status_code=302)


@router.get("/auth/google/callback")
async def google_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    error: Optional[str] = Query(default=None),
):
    if error:
        raise HTTPException(status_code=400, detail=f"Google OAuth error: {error}")

    saved_state = request.session.pop("oauth_state", None)
    if not saved_state or saved_state != state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    # Exchange code for tokens
    async with httpx.AsyncClient(timeout=15) as client:
        token_res = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": _google_redirect_uri(),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if token_res.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to exchange authorization code")

    token_data = token_res.json()
    id_token = token_data.get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="No id_token in response")

    # H5: 验签 Google id_token，不能裸信 token 直接 base64 解码。
    # 攻击者控制 /callback?code= 时可能注入伪造 token；深度防御层面必须验签。
    try:
        from google.auth.transport import requests as g_requests
        from google.oauth2 import id_token as g_id_token

        payload = g_id_token.verify_oauth2_token(
            id_token,
            g_requests.Request(),
            settings.google_client_id,
        )
        # 额外校验 issuer
        if payload.get("iss") not in ("https://accounts.google.com", "accounts.google.com"):
            raise ValueError(f"Invalid issuer: {payload.get('iss')}")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"id_token verification failed: {exc}",
        ) from exc

    # Check allowed domain
    if settings.allowed_domain and payload.get("hd") != settings.allowed_domain:
        raise HTTPException(
            status_code=403,
            detail=f"Email domain not allowed. Required: @{settings.allowed_domain}",
        )

    # Store user in session
    request.session["user"] = {
        "sub": payload["sub"],
        "email": payload.get("email", ""),
        "name": payload.get("name", ""),
        "picture": payload.get("picture", ""),
        "hd": payload.get("hd", ""),
    }

    next_url = request.session.pop("oauth_next", "/")
    return RedirectResponse(next_url, status_code=302)


@router.get("/auth/me")
async def me(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    email = str(user.get("email") or "").lower()
    return {"user": user, "is_admin": bool(email and email in _admin_emails())}


@router.get("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    next_url = request.query_params.get("next", "/")
    return RedirectResponse(next_url, status_code=302)
