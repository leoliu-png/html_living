from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PageGrant(Base):
    __tablename__ = "page_grants"
    __table_args__ = (UniqueConstraint("page_id", "principal_type", "principal"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    page_id: Mapped[str] = mapped_column(
        ForeignKey("page_assets.id", ondelete="CASCADE"), index=True
    )
    principal_type: Mapped[str] = mapped_column(String(10))
    principal: Mapped[str] = mapped_column(String(256), index=True)
    role: Mapped[str] = mapped_column(String(10), default="viewer")
    granted_by: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SharingGroup(Base):
    __tablename__ = "sharing_groups"
    slug: Mapped[str] = mapped_column(String(96), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))


class GroupMember(Base):
    __tablename__ = "group_members"
    group_id: Mapped[str] = mapped_column(ForeignKey("sharing_groups.slug"), primary_key=True)
    user_email: Mapped[str] = mapped_column(String(256), primary_key=True)
    role: Mapped[str] = mapped_column(String(10), default="member")


class UserSharingDefaults(Base):
    __tablename__ = "user_sharing_defaults"
    # Normalized verified account email works for sessions and user API keys alike.
    user_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    default_visibility: Mapped[str] = mapped_column(String(16), default="org")
    default_grants: Mapped[dict] = mapped_column(JSON, default=dict)


class NamespaceSharingDefaults(Base):
    """Default sharing for new pages published under one `owner` URL namespace."""

    __tablename__ = "namespace_sharing_defaults"
    owner: Mapped[str] = mapped_column(String(96), primary_key=True)
    default_visibility: Mapped[str] = mapped_column(String(16), default="org")
    default_grants: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_by: Mapped[str] = mapped_column(String(256))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SharingAuditLog(Base):
    __tablename__ = "sharing_audit_log"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    actor: Mapped[str] = mapped_column(String(256))
    page_id: Mapped[Optional[str]] = mapped_column(String(96), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(40))
    before: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    after: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
