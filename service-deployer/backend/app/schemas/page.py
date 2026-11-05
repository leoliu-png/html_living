from __future__ import annotations

from datetime import datetime
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.sharing import SharingState, SharingUpdate

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    msg: str = "ok"
    data: T


class PagePublishRequest(SharingUpdate):
    html: str = Field(min_length=1)
    owner: str = Field(min_length=1, max_length=96)
    submitter: Optional[str] = Field(default=None, max_length=200)
    description: str = Field(min_length=1)
    slug: Optional[str] = Field(default=None, max_length=96)
    title: Optional[str] = Field(default=None, max_length=200)
    data_sources: Optional[dict[str, str]] = Field(default=None)

    @field_validator("html", "owner", "description")
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Field cannot be blank.")
        return value

    @field_validator("submitter", "slug", "title")
    @classmethod
    def empty_string_to_none(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None


class PageUpdateRequest(SharingUpdate):
    html: Optional[str] = Field(default=None, min_length=1)
    title: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, min_length=1)
    data_sources: Optional[dict[str, str]] = Field(default=None)

    @field_validator("html", "description")
    @classmethod
    def require_non_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("Field cannot be blank.")
        return value

    @field_validator("title")
    @classmethod
    def empty_string_to_none(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None


class PagePublishResponse(SharingState):
    id: str
    owner: str
    slug: str
    url: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PageAssetResponse(SharingState):
    id: str
    owner: str
    slug: str
    url: str
    title: Optional[str]
    submitter: str
    description: str
    submit_ip: Optional[str]
    submit_device: Optional[str]
    submit_user_agent: Optional[str]
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    data_sources: Optional[dict[str, str]] = None
    is_unassigned: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PageDetailResponse(PageAssetResponse):
    html: str


class PaginationResponse(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool
    has_prev: bool


class PageIdentityFilterResponse(BaseModel):
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    count: int


class PageListResponse(BaseModel):
    items: list[PageAssetResponse]
    pagination: PaginationResponse
    legacy_submitters: list[str] = Field(default_factory=list)
    identity_filters: list[PageIdentityFilterResponse] = Field(default_factory=list)


class CountByOwnerResponse(BaseModel):
    owner: str
    count: int


class CountBySubmitterResponse(BaseModel):
    submitter: str
    count: int


class PageStatsResponse(BaseModel):
    total_pages: int
    total_owners: int
    total_submitters: int
    latest_created_at: Optional[datetime]
    top_owners: list[CountByOwnerResponse]
    top_submitters: list[CountBySubmitterResponse]
