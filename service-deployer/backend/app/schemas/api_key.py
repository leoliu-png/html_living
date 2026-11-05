from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(default="Default API key", min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Field cannot be blank.")
        return value


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    created_at: datetime
    last_used_at: Optional[datetime]
    revoked_at: Optional[datetime]
    active: bool


class ApiKeyCreateResponse(BaseModel):
    key: str
    item: ApiKeyResponse
