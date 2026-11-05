from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class PageDatasetResponse(BaseModel):
    id: str
    page_id: str
    name: str
    filename: str
    format: str
    size_bytes: int
    row_count: int
    columns: list[str]
    data_url: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PageDatasetListResponse(BaseModel):
    items: list[PageDatasetResponse]
    data_endpoint: str
    data_token: Optional[str] = None
    usage: str
