"""One SQL access predicate for page reads, discovery, counts and data credentials."""

import hashlib
import hmac
import secrets

from fastapi import HTTPException
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import and_, delete, false, func, or_, select, true

from app.auth_context import RequestActor
from app.config import settings
from app.models import PageAsset
from app.models.sharing import (
    GroupMember,
    NamespaceSharingDefaults,
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


def is_page_owner(actor, page):
    """Python twin of `owner_filter` for objects already loaded in memory."""
    if actor is None:
        return False
    email = (page.user_email or "").lower()
    return bool(
        (email and email == actor.email.lower())
        or (actor.user_id and page.user_id and actor.user_id == page.user_id)
    )


def can_manage_sharing(actor, page):
    return bool(actor and (actor.is_admin or is_page_owner(actor, page)))


def require_owner(db, actor, page):
    if not actor or not (
        actor.is_admin
        or db.scalar(select(PageAsset.id).where(PageAsset.id == page.id, owner_filter(actor)))
    ):
        raise HTTPException(404, "Page not found or not owned by you.")


def visible_sharing(db, actor, page):
    """Sharing state as shown to `actor`: grant lists only go to owners and admins."""
    state = get_sharing(db, page)
    if can_manage_sharing(actor, page):
        return state
    return SharingState(visibility=state.visibility, listed=state.listed)


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


def effective_defaults(db, actor, owner=None):
    """Return `(defaults, source)` for a new page in the `owner` namespace.

    Precedence: namespace default (e.g. everything under `ken-team` goes to the
    `ken-team` group) > the account's own default > the system default `org`.
    """
    if owner:
        row = db.get(NamespaceSharingDefaults, owner)
        if row is not None:
            return (
                SharingUpdate(
                    visibility=row.default_visibility,
                    share_with=ShareWith(**(row.default_grants or {})),
                    listed=True,
                ),
                "namespace",
            )
    row = db.get(UserSharingDefaults, actor.email.lower())
    if row is not None:
        return (
            SharingUpdate(
                visibility=row.default_visibility,
                share_with=ShareWith(**(row.default_grants or {})),
                listed=True,
            ),
            "account",
        )
    return SharingUpdate(visibility="org", share_with=ShareWith(), listed=True), "system"


def defaults_for(db, actor, owner=None):
    return effective_defaults(db, actor, owner)[0]


def can_manage_namespace(db, actor, owner):
    """Admins, or managers of the sharing group whose slug equals the namespace."""
    if actor is None:
        return False
    if actor.is_admin:
        return True
    return bool(
        db.scalar(
            select(GroupMember.user_email).where(
                GroupMember.group_id == owner,
                GroupMember.user_email == actor.email.lower(),
                GroupMember.role == "manager",
            )
        )
    )


def page_identity(page):
    return {"submitter": page.submitter, "user_email": page.user_email, "user_id": page.user_id}


def audit_claim(db, actor, page):
    """Record a legacy-page claim before it is applied, so admins can restore it."""
    audit(
        db,
        actor,
        page.id,
        "page_claimed",
        page_identity(page),
        {"submitter": actor.email, "user_email": actor.email, "user_id": actor.user_id},
    )


def publish_sharing(db, actor, payload):
    owner = (getattr(payload, "owner", None) or "").strip().lower() or None
    defaults = defaults_for(db, actor, owner)
    # Account defaults only apply when no sharing fields were supplied.
    if all(getattr(payload, name) is None for name in ("visibility", "share_with", "listed")):
        return defaults
    return SharingUpdate(
        visibility=payload.visibility or defaults.visibility,
        share_with=payload.share_with or ShareWith(),
        listed=payload.listed if payload.listed is not None else True,
    )


def _serializer():
    return URLSafeTimedSerializer(settings.session_secret, salt="page-data-viewer-v2")


def _revision_digest(revision):
    # Signed payloads are readable base64, so never embed the raw page data token:
    # that raw value still unlocks org page data anonymously as a legacy `k`.
    return hmac.new(
        settings.session_secret.encode(), f"page-data-revision:{revision}".encode(), hashlib.sha256
    ).hexdigest()


def viewer_data_token(db, actor, page):
    from app.services.datasets import ensure_page_data_token

    revision = ensure_page_data_token(db, page)
    return _serializer().dumps(
        {
            "page": page.id,
            "revision": _revision_digest(revision),
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
        if value["page"] != page.id or not page.data_token:
            return None
        if not hmac.compare_digest(str(value["revision"]), _revision_digest(page.data_token)):
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
