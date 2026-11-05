from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PageAsset(Base):
    __tablename__ = "page_assets"
    __table_args__ = (UniqueConstraint("owner", "slug", name="uq_page_assets_owner_slug"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(200))
    submitter: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    html: Mapped[str] = mapped_column(Text, nullable=False)
    submit_ip: Mapped[Optional[str]] = mapped_column(String(64))
    submit_device: Mapped[Optional[str]] = mapped_column(String(200))
    submit_user_agent: Mapped[Optional[str]] = mapped_column(Text)
    data_sources: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # Page-scoped read token for the dataset endpoint. Published HTML runs in a
    # CSP sandbox (opaque origin), so it cannot rely on the session cookie when
    # fetching its own data files.
    data_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    visibility: Mapped[str] = mapped_column(String(16), default="org", server_default="org")
    listed: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    user_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    user_email: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
