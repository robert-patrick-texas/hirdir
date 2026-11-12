"""The tables. Field names here are the names used in the API, JSON and CSV."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from hirdir import clock
from hirdir.ids import new_hid


class UTCDateTime(TypeDecorator):
    """A timestamp that is always UTC: stored without a zone, returned with one."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("a timestamp must carry a time zone")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    """The base of every table."""


def _hid() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=new_hid)


class Bookkeeping:
    """The columns every editable table carries."""

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=clock.now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=clock.now)
    created_by: Mapped[str | None] = mapped_column(String(36), default=None)
    updated_by: Mapped[str | None] = mapped_column(String(36), default=None)
    row_version: Mapped[int] = mapped_column(Integer, default=1)


class User(Bookkeeping, Base):
    """A person who signs in, or a service account that holds tokens."""

    __tablename__ = "users"

    hid: Mapped[str] = _hid()
    username: Mapped[str] = mapped_column(String(64))
    username_key: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(254), default="")
    is_service_account: Mapped[bool] = mapped_column(Boolean, default=False)
    access_code_hash: Mapped[str | None] = mapped_column(Text, default=None)
    tokens_valid_after: Mapped[int] = mapped_column(BigInteger, default=0)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_sign_in_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)

    memberships: Mapped[list[UserGroupMember]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserGroup(Bookkeeping, Base):
    """A label for a set of users. A role may be granted to it."""

    __tablename__ = "user_groups"

    hid: Mapped[str] = _hid()
    name: Mapped[str] = mapped_column(String(100))
    name_key: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")

    memberships: Mapped[list[UserGroupMember]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class UserGroupMember(Base):
    """One user's place in one group."""

    __tablename__ = "user_group_members"

    user_hid: Mapped[str] = mapped_column(ForeignKey("users.hid"), primary_key=True)
    group_hid: Mapped[str] = mapped_column(ForeignKey("user_groups.hid"), primary_key=True)

    user: Mapped[User] = relationship(back_populates="memberships")
    group: Mapped[UserGroup] = relationship(back_populates="memberships")


class RoleGrant(Base):
    """A role granted to exactly one user or one group."""

    __tablename__ = "role_grants"
    __table_args__ = (
        CheckConstraint(
            "(user_hid IS NOT NULL) + (group_hid IS NOT NULL) = 1",
            name="role_grants_one_target",
        ),
        UniqueConstraint("role", "user_hid", name="role_grants_user_once"),
        UniqueConstraint("role", "group_hid", name="role_grants_group_once"),
    )

    hid: Mapped[str] = _hid()
    role: Mapped[str] = mapped_column(String(20))
    user_hid: Mapped[str | None] = mapped_column(ForeignKey("users.hid"), default=None)
    group_hid: Mapped[str | None] = mapped_column(ForeignKey("user_groups.hid"), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=clock.now)
    created_by: Mapped[str | None] = mapped_column(String(36), default=None)


class ServiceToken(Base):
    """A named token of a service account. Only its hash is kept."""

    __tablename__ = "service_tokens"

    hid: Mapped[str] = _hid()
    user_hid: Mapped[str] = mapped_column(ForeignKey("users.hid"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=clock.now)
    created_by: Mapped[str | None] = mapped_column(String(36), default=None)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class AuditEvent(Base):
    """One thing that happened. Rows are only ever added."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("audit_events_record", "record_type", "record_hid"),
        Index("audit_events_at", "at"),
    )

    hid: Mapped[str] = _hid()
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=clock.now)
    actor_hid: Mapped[str | None] = mapped_column(String(36), default=None)
    via: Mapped[str] = mapped_column(String(10))
    request_id: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(40))
    record_type: Mapped[str] = mapped_column(String(40), default="")
    record_hid: Mapped[str | None] = mapped_column(String(36), default=None)
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
