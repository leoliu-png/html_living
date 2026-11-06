import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

Visibility = Literal["private", "restricted", "org"]


class ShareWith(BaseModel):
    users: list[str] = Field(default_factory=list, max_length=500)
    groups: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("users")
    @classmethod
    def validate_emails(cls, values):
        emails = sorted({value.strip().lower() for value in values})
        if any(
            len(value) > 256 or not re.fullmatch(r"[^\s@]+@feedmob\.com", value) for value in emails
        ):
            raise ValueError("Use FeedMob account emails (@feedmob.com).")
        return emails

    @field_validator("groups")
    @classmethod
    def validate_groups(cls, values):
        slugs = sorted({value.strip().lower() for value in values})
        if any(not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,95}", value) for value in slugs):
            raise ValueError("Invalid group slug.")
        return slugs


class SharingUpdate(BaseModel):
    visibility: Optional[Visibility] = None
    share_with: Optional[ShareWith] = None
    listed: Optional[bool] = None


class SharingState(BaseModel):
    visibility: Visibility = "org"
    share_with: ShareWith = Field(default_factory=ShareWith)
    listed: bool = True


class SharingDefaults(BaseModel):
    default_visibility: Visibility = "org"
    default_grants: ShareWith = Field(default_factory=ShareWith)


class EffectiveSharingDefaults(SharingDefaults):
    """Defaults a new page would get; `source` is namespace, account or system."""

    source: Literal["namespace", "account", "system"] = "system"
    owner: Optional[str] = None


class NamespaceSharingDefaultsResponse(SharingDefaults):
    owner: str
    updated_by: Optional[str] = None
    can_manage: bool = False


class GroupMembers(BaseModel):
    members: list[str] = Field(default_factory=list, max_length=500)
    managers: list[str] = Field(min_length=1, max_length=100)

    @field_validator("members", "managers")
    @classmethod
    def validate_emails(cls, values):
        return ShareWith.validate_emails(values)


class GroupCreate(GroupMembers):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,95}$")
    name: str = Field(min_length=1, max_length=200)


class GroupMembersPatch(BaseModel):
    """Incremental membership change, applied atomically under a group lock.

    Order inside one request: `remove` first, then the additions, so a manager can
    be demoted with `remove` + `add_members` in a single call.
    """

    add_members: list[str] = Field(default_factory=list, max_length=500)
    add_managers: list[str] = Field(default_factory=list, max_length=100)
    remove: list[str] = Field(default_factory=list, max_length=500)

    @field_validator("add_members", "add_managers", "remove")
    @classmethod
    def validate_emails(cls, values):
        return ShareWith.validate_emails(values)

    @model_validator(mode="after")
    def require_a_change(self):
        if not (self.add_members or self.add_managers or self.remove):
            raise ValueError("Provide at least one of add_members, add_managers or remove.")
        return self


class GroupRename(BaseModel):
    name: str = Field(min_length=1, max_length=200)
