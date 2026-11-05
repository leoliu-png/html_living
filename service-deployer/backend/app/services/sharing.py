"""One SQL access predicate for page reads, discovery, counts and data credentials."""

import secrets

from fastapi import HTTPException
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import and_, delete, false, func, or_, select, true

from app.auth_context import RequestActor
from app.config import settings
from app.models import PageAsset
from app.models.sharing import (
    GroupMember,
    PageGrant,
    SharingAuditLog,
    SharingGroup,
    UserSharingDefaults,
)
from app.schemas.sharing import ShareWith, SharingState, SharingUpdate


def owner_filter(actor):
    if actor is None:
        return false()
    filters = [func.lower(PageAsset.user_email) == actor.email.lower()]
    if actor.user_id:
        filters.append(PageAsset.user_id == actor.user_id)
    return or_(*filters)


def view_filter(actor):
    if actor is None:
        return false()
    if actor.is_admin:
        return true()
    grants = select(PageGrant.page_id).where(
        or_(
            and_(PageGrant.principal_type == "user", PageGrant.principal == actor.email.lower()),
            and_(
                PageGrant.principal_type == "group",
                PageGrant.principal.in_(
                    select(GroupMember.group_id).where(
                        GroupMember.user_email == actor.email.lower()
                    )
                ),
            ),
        )
    )
    return or_(
        owner_filter(actor),
        and_(
            PageAsset.visibility == "org",
            true() if actor.email.lower().endswith("@feedmob.com") else false(),
        ),
        and_(PageAsset.visibility == "restricted", PageAsset.id.in_(grants)),
    )


def discovery_filter(actor, *, mine=False):
    # Unlisted org pages remain available to their owner under My Pages.
    return and_(
        view_filter(actor),
        or_(
            PageAsset.visibility != "org",
            PageAsset.listed.is_(True),
            owner_filter(actor) if mine else false(),
        ),
    )


def can_view(db, actor, page):
    return bool(db.scalar(select(PageAsset.id).where(PageAsset.id == page.id, view_filter(actor))))


def audit(db, actor, page_id, action, before=None, after=None):
    db.add(
        SharingAuditLog(
            actor=actor.email, page_id=page_id, action=action, before=before, after=after
        )
    )


def audit_admin_read(db, actor, page_id=None):
    if actor and actor.is_admin:
        audit(db, actor, page_id, "admin_read")
        db.commit()


def require_view(db, actor, page):
    if not can_view(db, actor, page):
        raise HTTPException(404, "Page not found.")
    audit_admin_read(db, actor, page.id)


def require_owner(db, actor, page):
    if not actor or not (
        actor.is_admin
        or db.scalar(select(PageAsset.id).where(PageAsset.id == page.id, owner_filter(actor)))
    ):
        raise HTTPException(404, "Page not found or not owned by you.")


def get_sharing(db, page):
    grants = db.scalars(select(PageGrant).where(PageGrant.page_id == page.id)).all()
    return SharingState(
        visibility=page.visibility,
        listed=page.listed,
        share_with=ShareWith(
            users=[g.principal for g in grants if g.principal_type == "user"],
            groups=[g.principal for g in grants if g.principal_type == "group"],
        ),
    )


def validate_grants(db, grants):
    if grants.groups:
        found = set(
            db.scalars(select(SharingGroup.slug).where(SharingGroup.slug.in_(grants.groups)))
        )
        if found != set(grants.groups):
            raise HTTPException(422, "Unknown sharing group.")


def set_sharing(db, actor, page, update, *, initial=False):
    if not initial:
        # Serialize concurrent changes before reading the previous grants. Without
        # the page lock, two replacements can accidentally union their grants.
        db.refresh(page, with_for_update=True)
    before = get_sharing(db, page)
    effective = SharingState(
        visibility=update.visibility if update.visibility is not None else before.visibility,
        listed=update.listed if update.listed is not None else before.listed,
        share_with=update.share_with if update.share_with is not None else before.share_with,
    )
    validate_grants(db, effective.share_with)
    if not initial and effective == before:
        return before
    page.visibility = effective.visibility
    page.listed = effective.listed
    page.data_token = secrets.token_urlsafe(32)
    db.execute(delete(PageGrant).where(PageGrant.page_id == page.id))
    for kind, principals in [
        ("user", effective.share_with.users),
        ("group", effective.share_with.groups),
    ]:
        for principal in principals:
            db.add(
                PageGrant(
                    page_id=page.id,
                    principal_type=kind,
                    principal=principal,
                    granted_by=actor.email,
                )
            )
    audit(
        db,
        actor,
        page.id,
        "publish_sharing" if initial else "sharing_changed",
        None if initial else before.model_dump(),
        effective.model_dump(),
    )
    db.flush()
    return effective


def defaults_for(db, actor):
    row = db.get(UserSharingDefaults, actor.email.lower())
    if row is None:
        return SharingUpdate(visibility="org", share_with=ShareWith(), listed=True)
    return SharingUpdate(
        visibility=row.default_visibility, share_with=ShareWith(**row.default_grants), listed=True
    )


def publish_sharing(db, actor, payload):
    defaults = defaults_for(db, actor)
    # Account defaults only apply when no sharing fields were supplied.
    if all(getattr(payload, name) is None for name in ("visibility", "share_with", "listed")):
        return defaults
    return SharingUpdate(
        visibility=payload.visibility or defaults.visibility,
        share_with=payload.share_with or ShareWith(),
        listed=payload.listed if payload.listed is not None else True,
    )


def _serializer():
    return URLSafeTimedSerializer(settings.session_secret, salt="page-data-viewer-v1")


def viewer_data_token(db, actor, page):
    from app.services.datasets import ensure_page_data_token

    revision = ensure_page_data_token(db, page)
    return _serializer().dumps(
        {
            "page": page.id,
            "revision": revision,
            "email": actor.email,
            "sub": actor.user_id,
            "admin_token": actor.source == "admin_token",
        }
    )


def data_token_actor(db, token, page):
    if not token:
        return None
    try:
        value = _serializer().loads(token, max_age=3600)
        if value["page"] != page.id or value["revision"] != page.data_token:
            return None
        email = value["email"]
        admins = {email.strip().lower() for email in settings.admin_emails.split(",")}
        actor = RequestActor(
            email=email,
            user_id=value["sub"],
            name=None,
            source="page_data",
            is_admin=bool(value.get("admin_token") or email.lower() in admins),
        )
        return actor if can_view(db, actor, page) else None
    except (BadSignature, SignatureExpired, KeyError, TypeError):
        return None
