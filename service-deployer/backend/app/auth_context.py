from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.config import settings

ADMIN_TOKEN_EMAIL = "admin-token@service-deployer.internal"
REAL_USER_EMAIL_DOMAIN = "feedmob.com"


@dataclass(frozen=True)
class RequestActor:
    email: str
    user_id: Optional[str]
    name: Optional[str]
    source: str
    is_admin: bool = False


def _admin_emails() -> set[str]:
    return {email.strip().lower() for email in settings.admin_emails.split(",") if email.strip()}


def parse_email_list(value: str) -> set[str]:
    return {email.strip().lower() for email in value.split(",") if email.strip()}


def _is_admin_email(email: str) -> bool:
    return email.lower() in _admin_emails()


def _extract_token(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    token = request.query_params.get("token")
    return token or None


def _has_admin_token(request: Request) -> bool:
    token = _extract_token(request)
    return bool(settings.api_token and token == settings.api_token)


def _email_allowed(email: str) -> bool:
    if not settings.allowed_domain:
        return True
    return email.lower().endswith(f"@{settings.allowed_domain.lower()}")


def is_real_user_email(email: Optional[str]) -> bool:
    value = (email or "").strip().lower()
    return bool(
        value
        and value.endswith(f"@{REAL_USER_EMAIL_DOMAIN}")
        and not value.endswith(".internal")
    )


def is_assigned_page_identity(page_user_email: Optional[str]) -> bool:
    return is_real_user_email(page_user_email)


def is_unassigned_page(
    page_submitter: str,
    page_user_id: Optional[str],
    page_user_email: Optional[str],
    *,
    allowlist: set[str],
) -> bool:
    return not is_assigned_page_identity(page_user_email)


def _actor_from_user_api_key(request: Request, db: Optional[Session]) -> Optional[RequestActor]:
    if db is None:
        return None
    token = _extract_token(request)
    if not token or _has_admin_token(request):
        return None
    from app.services.api_keys import authenticate_api_key

    principal = authenticate_api_key(db, token)
    if principal is None:
        return None
    return RequestActor(
        email=principal.user_email,
        user_id=principal.user_id,
        name="API Key",
        source="api_key",
        is_admin=_is_admin_email(principal.user_email),
    )


def get_request_actor(request: Request, db: Optional[Session] = None) -> Optional[RequestActor]:
    session_user = request.session.get("user") if hasattr(request, "session") else None
    if session_user:
        email = str(session_user.get("email") or "").strip()
        if email:
            return RequestActor(
                email=email,
                user_id=str(session_user.get("sub") or "") or None,
                name=str(session_user.get("name") or "") or None,
                source="session",
                is_admin=_is_admin_email(email),
            )

    api_key_actor = _actor_from_user_api_key(request, db)
    if api_key_actor is not None:
        return api_key_actor

    if not _has_admin_token(request):
        return None

    # MCP is trusted to forward the OAuth user only when it authenticates to the
    # backend with the shared admin token. External callers cannot rely on these
    # headers without that token.
    forwarded_email = request.headers.get("X-User-Email", "").strip()
    if forwarded_email:
        if not _email_allowed(forwarded_email):
            return None
        return RequestActor(
            email=forwarded_email,
            user_id=request.headers.get("X-User-Id") or None,
            name=request.headers.get("X-User-Name") or None,
            source="forwarded",
            is_admin=_is_admin_email(forwarded_email),
        )

    return RequestActor(
        email=ADMIN_TOKEN_EMAIL,
        user_id=None,
        name="Admin Token",
        source="admin_token",
        is_admin=True,
    )


def actor_owns_page(
    actor: RequestActor,
    page_submitter: str,
    page_user_id: Optional[str],
    page_user_email: Optional[str],
) -> bool:
    actor_email = actor.email.lower()
    return bool(
        is_assigned_page_identity(page_user_email)
        and (
            (actor.user_id and page_user_id and actor.user_id == page_user_id)
            or (page_user_email and actor_email == page_user_email.lower())
        )
    )


def actor_can_manage_page(
    actor: RequestActor,
    page_submitter: str,
    page_user_id: Optional[str],
    page_user_email: Optional[str],
    *,
    allowlist: set[str],
) -> bool:
    return bool(
        actor.is_admin
        or is_unassigned_page(
            page_submitter,
            page_user_id,
            page_user_email,
            allowlist=allowlist,
        )
        or actor_owns_page(actor, page_submitter, page_user_id, page_user_email)
    )
