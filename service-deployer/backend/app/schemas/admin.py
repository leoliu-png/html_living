from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class AdminSettingsResponse(BaseModel):
    submitter_allowlist: list[str]


class AdminSettingsUpdateRequest(BaseModel):
    submitter_allowlist: list[str] = Field(default_factory=list)

    @field_validator("submitter_allowlist")
    @classmethod
    def normalize_allowlist(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        normalized: list[str] = []
        for email in value:
            item = email.strip().lower()
            if not item or item in seen:
                continue
            seen.add(item)
            normalized.append(item)
        return normalized
