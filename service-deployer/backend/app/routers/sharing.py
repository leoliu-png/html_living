from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth_context import get_request_actor
from app.database import get_db
from app.models import PageAsset
from app.models.sharing import GroupMember, SharingGroup, UserSharingDefaults
from app.schemas.page import ApiResponse
from app.schemas.sharing import (
    GroupCreate,
    GroupMembers,
    SharingDefaults,
    SharingState,
    SharingUpdate,
)
from app.services.sharing import (
    audit,
    audit_admin_read,
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


@router.get("/api/me/sharing-defaults", response_model=ApiResponse[SharingDefaults])
def get_defaults(request: Request, db: DbSession):
    actor = actor_for(request, db)
    row = db.get(UserSharingDefaults, actor.email.lower())
    return ApiResponse(
        data=SharingDefaults(
            default_visibility=row.default_visibility, default_grants=row.default_grants
        )
        if row
        else SharingDefaults()
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
