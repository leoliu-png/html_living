from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import PageAsset

SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,94}[a-z0-9])?$")
OWNER_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,94}[a-z0-9])?$")
AUTO_SLUG_LENGTH = 10


class SlugConflictError(ValueError):
    pass


class InvalidSlugError(ValueError):
    pass


class InvalidOwnerError(ValueError):
    pass


@dataclass(frozen=True)
class SubmissionContext:
    submit_ip: Optional[str] = None
    submit_user_agent: Optional[str] = None
    submit_device: Optional[str] = None
    user_id: Optional[str] = None
    user_email: Optional[str] = None


@dataclass(frozen=True)
class PublishHtmlPageInput:
    html: str
    owner: str
    submitter: str
    description: str
    slug: Optional[str] = None
    title: Optional[str] = None
    data_sources: Optional[dict[str, str]] = None


def normalize_slug(slug: str) -> str:
    normalized = slug.strip().lower()
    if not SLUG_PATTERN.fullmatch(normalized):
        raise InvalidSlugError(
            "Slug must use lowercase letters, numbers, and hyphens. "
            "It cannot start or end with a hyphen."
        )
    return normalized


def normalize_owner(owner: str) -> str:
    normalized = owner.strip().lower()
    if not OWNER_PATTERN.fullmatch(normalized):
        raise InvalidOwnerError(
            "Owner must use lowercase letters, numbers, and hyphens. "
            "It cannot start or end with a hyphen."
        )
    return normalized


def slug_exists(db: Session, owner: str, slug: str) -> bool:
    return (
        db.scalar(select(PageAsset.id).where(PageAsset.owner == owner, PageAsset.slug == slug))
        is not None
    )


def generate_unique_slug(db: Session, owner: str) -> str:
    while True:
        slug = secrets.token_urlsafe(8).lower().replace("_", "-")[:AUTO_SLUG_LENGTH]
        slug = slug.strip("-")
        if len(slug) < AUTO_SLUG_LENGTH:
            continue
        if not slug_exists(db, owner, slug):
            return slug


def resolve_slug(db: Session, owner: str, requested_slug: Optional[str]) -> str:
    if requested_slug:
        slug = normalize_slug(requested_slug)
        if slug_exists(db, owner, slug):
            raise SlugConflictError("Slug already exists for this owner.")
        return slug

    return generate_unique_slug(db, owner)


def detect_device(user_agent: Optional[str]) -> Optional[str]:
    if not user_agent:
        return None

    ua = user_agent.lower()
    if "iphone" in ua:
        return "iPhone"
    if "ipad" in ua:
        return "iPad"
    if "android" in ua and "mobile" in ua:
        return "Android Phone"
    if "android" in ua:
        return "Android Tablet"
    if "macintosh" in ua or "mac os x" in ua:
        return "macOS"
    if "windows" in ua:
        return "Windows"
    if "linux" in ua:
        return "Linux"
    return "Unknown"


class PageNotFoundError(ValueError):
    pass


class NoFieldsToUpdateError(ValueError):
    pass


def build_public_page_url(public_base_url: str, owner: str, slug: str) -> str:
    return f"{public_base_url.rstrip('/')}/p/{owner}/{slug}"


def delete_page(db: Session, page_id: str) -> PageAsset:
    page = db.scalar(select(PageAsset).where(PageAsset.id == page_id))
    if page is None:
        raise PageNotFoundError("Page not found.")
    from app.models.sharing import PageGrant

    db.execute(delete(PageGrant).where(PageGrant.page_id == page.id))
    db.delete(page)
    db.commit()
    return page


def update_html_page(
    db: Session,
    page_id: str,
    *,
    html: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    data_sources: Optional[dict[str, Any]] = None,
    submitter: Optional[str] = None,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    commit: bool = True,
) -> PageAsset:
    page = db.scalar(select(PageAsset).where(PageAsset.id == page_id))
    if page is None:
        raise PageNotFoundError("Page not found.")
    if all(v is None for v in (html, title, description, data_sources)):
        raise NoFieldsToUpdateError("At least one field must be provided.")
    if html is not None:
        page.html = html
    if title is not None:
        page.title = title.strip() or None
    if description is not None:
        page.description = description.strip()
    if data_sources is not None:
        page.data_sources = data_sources
    if submitter is not None:
        page.submitter = submitter.strip()
    if user_id is not None:
        page.user_id = user_id
    if user_email is not None:
        page.user_email = user_email.strip()
    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(page)
    return page


def claim_page(
    db: Session,
    page_id: str,
    *,
    submitter: str,
    user_id: Optional[str],
    user_email: str,
) -> PageAsset:
    page = db.scalar(select(PageAsset).where(PageAsset.id == page_id))
    if page is None:
        raise PageNotFoundError("Page not found.")
    page.submitter = submitter.strip()
    page.user_id = user_id
    page.user_email = user_email.strip()
    db.commit()
    db.refresh(page)
    return page


def publish_html_page(
    db: Session,
    payload: PublishHtmlPageInput,
    context: SubmissionContext,
    *,
    commit: bool = True,
) -> PageAsset:
    owner = normalize_owner(payload.owner)
    slug = resolve_slug(db, owner, payload.slug)
    page = PageAsset(
        owner=owner,
        slug=slug,
        title=payload.title,
        submitter=payload.submitter.strip(),
        description=payload.description.strip(),
        html=payload.html,
        data_sources=payload.data_sources,
        submit_ip=context.submit_ip,
        submit_device=context.submit_device or detect_device(context.submit_user_agent),
        submit_user_agent=context.submit_user_agent,
        user_id=context.user_id,
        user_email=context.user_email,
    )
    try:
        db.add(page)
        if commit:
            db.commit()
        else:
            db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise SlugConflictError("Slug already exists.") from exc
    db.refresh(page)
    return page
