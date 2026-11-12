"""The shapes of requests and responses. These, as OpenAPI, are the contract."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    """The base of every schema: built from records, unknown fields refused."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class Page[T](Model):
    """One page of a list."""

    items: list[T]
    total: int
    limit: int
    offset: int


class ProblemField(Model):
    """What is wrong with one field of a request."""

    field: str
    message: str


class Problem(Model):
    """An error, as an RFC 9457 problem document."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str = ""
    errors: list[ProblemField] = []


class GroupRef(Model):
    """A user group, as named on a user."""

    hid: str
    name: str


class UserOut(Model):
    """A user."""

    hid: str
    username: str
    display_name: str
    email: str
    is_service_account: bool
    disabled: bool
    role: str | None = Field(description="The highest role held directly or through a group.")
    groups: list[GroupRef]
    last_sign_in_at: datetime | None
    row_version: int
    created_at: datetime
    updated_at: datetime


class UserCreate(Model):
    """A new user."""

    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=254)
    is_service_account: bool = False
    access_code: str | None = Field(
        default=None, max_length=200, description="Left out, a code is generated."
    )
    role: str | None = Field(default=None, description="A role to grant at once.")


class UserCreated(Model):
    """A user just created, with the access code that is shown this once."""

    user: UserOut
    access_code: str | None


class UserPatch(Model):
    """Fields of a user to change, and the version they were read at."""

    row_version: int
    display_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=254)
    disabled: bool | None = None


class AccessCodeSet(Model):
    """A new access code for a user. Left out, a code is generated."""

    access_code: str | None = Field(default=None, max_length=200)


class AccessCodeOut(Model):
    """The access code just set, shown this once."""

    access_code: str


class SignIn(Model):
    """A username and access code."""

    username: str = Field(min_length=1, max_length=64)
    access_code: str = Field(min_length=1, max_length=200)


class SessionOut(Model):
    """A session: the token to send as `Authorization: Bearer`, and when it ends."""

    token: str
    expires_at: datetime
    user: UserOut


class GroupOut(Model):
    """A user group."""

    hid: str
    name: str
    description: str
    member_count: int
    roles: list[str]
    row_version: int
    created_at: datetime
    updated_at: datetime


class GroupDetail(GroupOut):
    """A user group with its members."""

    members: list[UserOut]


class GroupCreate(Model):
    """A new user group."""

    name: str = Field(min_length=1, max_length=100)
    description: str = ""


class GroupPatch(Model):
    """Fields of a user group to change, and the version they were read at."""

    row_version: int
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None


class GrantOut(Model):
    """A role granted to a user or to a group."""

    hid: str
    role: str
    user_hid: str | None
    group_hid: str | None
    target_name: str
    created_at: datetime


class GrantCreate(Model):
    """A role to grant to exactly one user or one group."""

    role: str
    user_hid: str | None = None
    group_hid: str | None = None


class ServiceTokenOut(Model):
    """A service token. The secret is not kept and cannot be shown again."""

    hid: str
    user_hid: str
    name: str
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None


class ServiceTokenCreate(Model):
    """A new service token."""

    name: str = Field(min_length=1, max_length=100)
    expires_at: datetime | None = None


class ServiceTokenCreated(Model):
    """A service token just created, with the secret that is shown this once."""

    token: ServiceTokenOut
    secret: str


class AuditEventOut(Model):
    """One event of the audit trail."""

    hid: str
    at: datetime
    actor_hid: str | None
    actor_name: str | None
    via: str
    request_id: str
    action: str
    record_type: str
    record_hid: str | None
    changes: list[dict[str, Any]]


class About(Model):
    """What is running."""

    name: str
    version: str
    python: str
    sqlite: str
    schema_revision: str | None


class Health(Model):
    """The answer of a health probe."""

    status: str
    detail: str = ""
