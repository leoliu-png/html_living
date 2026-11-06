import secrets
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth_context import get_request_actor
from app.database import get_db
from app.models import PageAsset
from app.models.sharing import (
    GroupMember,
    NamespaceSharingDefaults,
    PageGrant,
    SharingAuditLog,
    SharingGroup,
    UserSharingDefaults,
)
from app.schemas.page import ApiResponse
from app.schemas.sharing import (
    EffectiveSharingDefaults,
    GroupCreate,
    GroupMembers,
    GroupMembersPatch,
    GroupRename,
    NamespaceSharingDefaultsResponse,
    SharingDefaults,
    SharingState,
    SharingUpdate,
)
from app.services.pages import OWNER_PATTERN
from app.services.sharing import (
    audit,
    audit_admin_read,
    can_manage_namespace,
    effective_defaults,
    get_sharing,
    require_owner,
    set_sharing,
    validate_grants,
)

router = APIRouter(tags=["sharing"])
DbSession = Annotated[Session, Depends(get_db)]


def actor_for(request, db):
    actor = get_request_actor(request, db)
    if actor is None:
        raise HTTPException(401, "Not authenticated.")
    return actor


def owned_page(request, db, page_id):
    actor = actor_for(request, db)
    page = db.get(PageAsset, page_id)
    if page is None:
        raise HTTPException(404, "Page not found.")
    require_owner(db, actor, page)
    return actor, page


@router.get("/api/pages/{page_id}/sharing", response_model=ApiResponse[SharingState])
def get_page_sharing(page_id: str, request: Request, db: DbSession):
    actor, page = owned_page(request, db, page_id)
    audit_admin_read(db, actor, page.id)
    return ApiResponse(data=get_sharing(db, page))


@router.put("/api/pages/{page_id}/sharing", response_model=ApiResponse[SharingState])
def set_page_sharing(page_id: str, payload: SharingUpdate, request: Request, db: DbSession):
    actor, page = owned_page(request, db, page_id)
    state = set_sharing(db, actor, page, payload)
    db.commit()
    return ApiResponse(data=state)


def group_state(db, group, actor):
    members = db.scalars(select(GroupMember).where(GroupMember.group_id == group.slug)).all()
    managers = [m.user_email for m in members if m.role == "manager"]
    can_manage = actor.is_admin or actor.email.lower() in managers
    return {
        "slug": group.slug,
        "name": group.name,
        "managers": managers,
        "members": sorted(m.user_email for m in members) if can_manage else [],
        "can_manage": can_manage,
    }


@router.get("/api/groups")
def list_groups(request: Request, db: DbSession):
    actor = actor_for(request, db)
    return ApiResponse(
        data={
            "items": [
                group_state(db, g, actor)
                for g in db.scalars(select(SharingGroup).order_by(SharingGroup.name))
            ]
        }
    )


def replace_members(db, slug, payload):
    db.execute(delete(GroupMember).where(GroupMember.group_id == slug))
    for email in sorted(set(payload.members + payload.managers)):
        db.add(
            GroupMember(
                group_id=slug,
                user_email=email,
                role="manager" if email in payload.managers else "member",
            )
        )
    db.flush()


@router.post("/api/groups", status_code=201)
def create_group(payload: GroupCreate, request: Request, db: DbSession):
    actor = actor_for(request, db)
    if not actor.is_admin and actor.email.lower() not in payload.managers:
        raise HTTPException(403, "The creator must be a group manager.")
    if db.get(SharingGroup, payload.slug):
        raise HTTPException(409, "Group already exists.") from None
    group = SharingGroup(slug=payload.slug, name=payload.name)
    db.add(group)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Group already exists.") from None
    replace_members(db, group.slug, payload)
    audit(db, actor, None, "group_created", after=payload.model_dump())
    db.commit()
    return ApiResponse(data=group_state(db, group, actor))


@router.put("/api/groups/{slug}/members")
def update_members(slug: str, payload: GroupMembers, request: Request, db: DbSession):
    actor = actor_for(request, db)
    group = db.scalar(select(SharingGroup).where(SharingGroup.slug == slug).with_for_update())
    if not group:
        raise HTTPException(404, "Group not found.")
    before = group_state(db, group, actor)
    if not before["can_manage"]:
        raise HTTPException(403, "Only a group manager or administrator can edit membership.")
    replace_members(db, slug, payload)
    audit(db, actor, None, "group_members_changed", before=before, after=payload.model_dump())
    db.commit()
    return ApiResponse(data=group_state(db, group, actor))


def locked_group(db, slug):
    group = db.scalar(select(SharingGroup).where(SharingGroup.slug == slug).with_for_update())
    if not group:
        raise HTTPException(404, "Group not found.")
    return group


@router.patch("/api/groups/{slug}/members")
def patch_members(slug: str, payload: GroupMembersPatch, request: Request, db: DbSession):
    """Add or remove people without resending the whole list (no lost updates)."""
    actor = actor_for(request, db)
    group = locked_group(db, slug)
    before = group_state(db, group, actor)
    if not before["can_manage"]:
        raise HTTPException(403, "Only a group manager or administrator can edit membership.")
    rows = {
        m.user_email: m for m in db.scalars(select(GroupMember).where(GroupMember.group_id == slug))
    }
    for email in payload.remove:
        if email in rows:
            db.delete(rows.pop(email))
    for email in payload.add_members:
        if email not in rows:
            rows[email] = GroupMember(group_id=slug, user_email=email, role="member")
            db.add(rows[email])
    for email in payload.add_managers:
        if email in rows:
            rows[email].role = "manager"
        else:
            rows[email] = GroupMember(group_id=slug, user_email=email, role="manager")
            db.add(rows[email])
    if not any(m.role == "manager" for m in rows.values()):
        db.rollback()
        raise HTTPException(422, "A group must keep at least one manager.")
    db.flush()
    after = group_state(db, group, actor)
    audit(db, actor, None, "group_members_changed", before=before, after=payload.model_dump())
    db.commit()
    return ApiResponse(data=after)


@router.put("/api/groups/{slug}")
def rename_group(slug: str, payload: GroupRename, request: Request, db: DbSession):
    actor = actor_for(request, db)
    group = locked_group(db, slug)
    before = group_state(db, group, actor)
    if not before["can_manage"]:
        raise HTTPException(403, "Only a group manager or administrator can rename the group.")
    group.name = payload.name.strip()
    audit(
        db,
        actor,
        None,
        "group_renamed",
        before={"name": before["name"]},
        after=payload.model_dump(),
    )
    db.commit()
    return ApiResponse(data=group_state(db, group, actor))


def group_references(db, slug):
    """Everything that would silently lose or keep access if this slug disappeared."""
    grants = db.scalars(
        select(PageGrant).where(PageGrant.principal_type == "group", PageGrant.principal == slug)
    ).all()
    user_defaults = [
        row
        for row in db.scalars(select(UserSharingDefaults))
        if slug in ((row.default_grants or {}).get("groups") or [])
    ]
    namespace_defaults = [
        row
        for row in db.scalars(select(NamespaceSharingDefaults))
        if slug in ((row.default_grants or {}).get("groups") or [])
    ]
    return grants, user_defaults, namespace_defaults


@router.delete("/api/groups/{slug}")
def delete_group(slug: str, request: Request, db: DbSession, force: bool = Query(default=False)):
    """Delete a group.

    A deleted slug could be re-registered by someone else and would then inherit
    every grant that still named it, so grants and defaults that reference the
    group are either refused (409) or purged together with it (`force=true`).
    """
    actor = actor_for(request, db)
    group = locked_group(db, slug)
    before = group_state(db, group, actor)
    if not before["can_manage"]:
        raise HTTPException(403, "Only a group manager or administrator can delete the group.")
    grants, user_defaults, namespace_defaults = group_references(db, slug)
    summary = {
        "page_grants": len(grants),
        "account_defaults": len(user_defaults),
        "namespace_defaults": len(namespace_defaults),
    }
    if any(summary.values()) and not force:
        raise HTTPException(
            409,
            f"Group is still used by {summary['page_grants']} page(s), "
            f"{summary['account_defaults']} account default(s) and "
            f"{summary['namespace_defaults']} namespace default(s). "
            "Retry with force=true to remove those grants too.",
        )
    affected_pages = []
    for grant in grants:
        page = db.get(PageAsset, grant.page_id)
        if page is not None:
            page.data_token = secrets.token_urlsafe(32)  # revoke viewer credentials now
            affected_pages.append(page.id)
            audit(db, actor, page.id, "group_grant_removed", before={"group": slug}, after=None)
        db.delete(grant)
    for row in [*user_defaults, *namespace_defaults]:
        grants_json = dict(row.default_grants or {})
        grants_json["groups"] = [g for g in grants_json.get("groups", []) if g != slug]
        row.default_grants = grants_json
    db.execute(delete(GroupMember).where(GroupMember.group_id == slug))
    db.delete(group)
    audit(
        db,
        actor,
        None,
        "group_deleted",
        before=before,
        after={**summary, "pages": affected_pages},
    )
    db.commit()
    return ApiResponse(msg="group deleted", data={"slug": slug, **summary})


def audit_items(rows, names):
    return [
        {
            "at": row.at.isoformat() if row.at else None,
            "actor": row.actor,
            "action": row.action,
            "page_id": row.page_id,
            "page": names.get(row.page_id),
            "before": row.before,
            "after": row.after,
        }
        for row in rows
    ]


@router.get("/api/pages/{page_id}/audit")
def get_page_audit(
    page_id: str,
    request: Request,
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
):
    """Sharing history of one page: who changed access and which admins read it."""
    actor, page = owned_page(request, db, page_id)
    audit_admin_read(db, actor, page.id)
    rows = db.scalars(
        select(SharingAuditLog)
        .where(SharingAuditLog.page_id == page.id)
        .order_by(SharingAuditLog.at.desc())
        .limit(limit)
    ).all()
    return ApiResponse(data={"items": audit_items(rows, {page.id: f"{page.owner}/{page.slug}"})})


@router.get("/api/me/sharing-defaults", response_model=ApiResponse[EffectiveSharingDefaults])
def get_defaults(
    request: Request,
    db: DbSession,
    owner: Optional[str] = Query(default=None, max_length=96),
):
    """Account defaults, or with `owner` the defaults a new page there would get."""
    actor = actor_for(request, db)
    namespace = normalize_namespace(owner) if owner else None
    defaults, source = effective_defaults(db, actor, namespace)
    return ApiResponse(
        data=EffectiveSharingDefaults(
            default_visibility=defaults.visibility,
            default_grants=defaults.share_with,
            source=source,
            owner=namespace,
        )
    )


@router.put("/api/me/sharing-defaults", response_model=ApiResponse[SharingDefaults])
def set_defaults(payload: SharingDefaults, request: Request, db: DbSession):
    actor = actor_for(request, db)
    validate_grants(db, payload.default_grants)
    row = db.get(UserSharingDefaults, actor.email.lower())
    before = (
        {"default_visibility": row.default_visibility, "default_grants": row.default_grants}
        if row
        else None
    )
    if row is None:
        row = UserSharingDefaults(user_id=actor.email.lower())
        db.add(row)
    row.default_visibility = payload.default_visibility
    row.default_grants = payload.default_grants.model_dump()
    audit(db, actor, None, "defaults_changed", before=before, after=payload.model_dump())
    db.commit()
    return ApiResponse(data=payload)


def normalize_namespace(owner):
    value = (owner or "").strip().lower()
    if not OWNER_PATTERN.fullmatch(value):
        raise HTTPException(422, "Owner must use lowercase letters, numbers, and hyphens.")
    return value


def namespace_state(db, actor, owner, row):
    return NamespaceSharingDefaultsResponse(
        owner=owner,
        default_visibility=row.default_visibility if row else "org",
        default_grants=row.default_grants if row else {},
        updated_by=row.updated_by if row else None,
        can_manage=can_manage_namespace(db, actor, owner),
    )


def require_namespace_manager(db, actor, owner):
    if not can_manage_namespace(db, actor, owner):
        raise HTTPException(
            403,
            "Only administrators or managers of the group with the same slug "
            "can set namespace defaults.",
        )


@router.get("/api/namespaces/sharing-defaults")
def list_namespace_defaults(request: Request, db: DbSession):
    actor = actor_for(request, db)
    rows = db.scalars(select(NamespaceSharingDefaults).order_by(NamespaceSharingDefaults.owner))
    return ApiResponse(data={"items": [namespace_state(db, actor, r.owner, r) for r in rows]})


@router.get(
    "/api/namespaces/{owner}/sharing-defaults",
    response_model=ApiResponse[NamespaceSharingDefaultsResponse],
)
def get_namespace_defaults(owner: str, request: Request, db: DbSession):
    actor = actor_for(request, db)
    owner = normalize_namespace(owner)
    row = db.get(NamespaceSharingDefaults, owner)
    if row is None:
        raise HTTPException(404, "No namespace default is set.")
    return ApiResponse(data=namespace_state(db, actor, owner, row))


@router.put(
    "/api/namespaces/{owner}/sharing-defaults",
    response_model=ApiResponse[NamespaceSharingDefaultsResponse],
)
def set_namespace_defaults(owner: str, payload: SharingDefaults, request: Request, db: DbSession):
    actor = actor_for(request, db)
    owner = normalize_namespace(owner)
    require_namespace_manager(db, actor, owner)
    validate_grants(db, payload.default_grants)
    row = db.get(NamespaceSharingDefaults, owner)
    before = (
        {"default_visibility": row.default_visibility, "default_grants": row.default_grants}
        if row
        else None
    )
    if row is None:
        row = NamespaceSharingDefaults(owner=owner)
        db.add(row)
    row.default_visibility = payload.default_visibility
    row.default_grants = payload.default_grants.model_dump()
    row.updated_by = actor.email
    audit(
        db,
        actor,
        None,
        "namespace_defaults_changed",
        before=before,
        after={"owner": owner, **payload.model_dump()},
    )
    db.commit()
    return ApiResponse(data=namespace_state(db, actor, owner, row))


@router.delete(
    "/api/namespaces/{owner}/sharing-defaults",
    response_model=ApiResponse[dict],
)
def delete_namespace_defaults(owner: str, request: Request, db: DbSession):
    actor = actor_for(request, db)
    owner = normalize_namespace(owner)
    require_namespace_manager(db, actor, owner)
    row = db.get(NamespaceSharingDefaults, owner)
    if row is None:
        raise HTTPException(404, "No namespace default is set.")
    before = {
        "owner": owner,
        "default_visibility": row.default_visibility,
        "default_grants": row.default_grants,
    }
    db.delete(row)
    audit(db, actor, None, "namespace_defaults_deleted", before=before)
    db.commit()
    return ApiResponse(msg="namespace default removed", data={"owner": owner})
