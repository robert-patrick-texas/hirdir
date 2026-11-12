"""The tables. Field names here are the names used in the API, JSON and CSV."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
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


class Scaled(TypeDecorator):
    """A decimal kept as a whole number of its smallest step.

    Money is kept in hundredths and weights in thousandths, so a sum is exact and a
    comparison means the same on SQLite and on PostgreSQL.
    """

    impl = BigInteger
    cache_ok = True

    def __init__(self, places: int) -> None:
        super().__init__()
        self.places = places

    def process_bind_param(self, value: Decimal | None, dialect: Any) -> int | None:
        if value is None:
            return None
        steps = Decimal(value).scaleb(self.places)
        if steps != steps.to_integral_value():
            raise ValueError(f"at most {self.places} decimal places are kept")
        return int(steps)

    def process_result_value(self, value: int | None, dialect: Any) -> Decimal | None:
        return None if value is None else Decimal(value).scaleb(-self.places)


MONEY_PLACES = 2
WEIGHT_PLACES = 3
PERCENT_PLACES = 2


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


# --- the inventory -----------------------------------------------------------------


class Vendor(Bookkeeping, Base):
    """A manufacturer, a support provider, or both."""

    __tablename__ = "vendors"

    hid: Mapped[str] = _hid()
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200), unique=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text, default=None)


class CatalogEntry(Bookkeeping, Base):
    """What is true of every item of one model: one vendor and product ID."""

    __tablename__ = "catalog_entries"
    __table_args__ = (UniqueConstraint("vendor_hid", "pid_key", name="catalog_entries_vendor_pid"),)

    hid: Mapped[str] = _hid()
    vendor_hid: Mapped[str] = mapped_column(ForeignKey("vendors.hid"), index=True)
    pid: Mapped[str] = mapped_column(String(100))
    pid_key: Mapped[str] = mapped_column(String(100))
    model_name: Mapped[str | None] = mapped_column(String(200), default=None)
    kind: Mapped[str] = mapped_column(String(20), default="hardware")
    type: Mapped[str | None] = mapped_column(String(40), default=None)
    function: Mapped[str | None] = mapped_column(String(40), default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    end_of_sale: Mapped[date | None] = mapped_column(Date, default=None)
    end_of_sw_support: Mapped[date | None] = mapped_column(Date, default=None)
    end_of_hw_support: Mapped[date | None] = mapped_column(Date, default=None)
    ldos: Mapped[date | None] = mapped_column(Date, default=None)
    est_value: Mapped[Decimal | None] = mapped_column(Scaled(MONEY_PLACES), default=None)
    support_weight: Mapped[Decimal | None] = mapped_column(Scaled(WEIGHT_PLACES), default=None)
    annual_support_cost: Mapped[Decimal | None] = mapped_column(Scaled(MONEY_PLACES), default=None)
    stack_discount_pct: Mapped[Decimal | None] = mapped_column(Scaled(PERCENT_PLACES), default=None)
    successor_hid: Mapped[str | None] = mapped_column(
        ForeignKey("catalog_entries.hid"), default=None
    )
    review_status: Mapped[str] = mapped_column(String(12), default="reviewed")
    record_status: Mapped[str] = mapped_column(String(10), default="active")


class Owner(Bookkeeping, Base):
    """Who answers for an item. Its people arrive with contacts, in a later release."""

    __tablename__ = "owners"

    hid: Mapped[str] = _hid()
    label: Mapped[str] = mapped_column(String(200))
    label_key: Mapped[str] = mapped_column(String(200), unique=True)
    organization: Mapped[str | None] = mapped_column(String(200), default=None)
    is_external: Mapped[bool] = mapped_column(Boolean, default=False)
    exception_reason: Mapped[str | None] = mapped_column(Text, default=None)
    record_status: Mapped[str] = mapped_column(String(10), default="active")


class Item(Bookkeeping, Base):
    """One tracked thing: hardware, a virtual machine, a software application or a service."""

    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("catalog_entry_hid", "serial_key", name="items_catalog_serial"),
        Index("items_updated_at", "updated_at"),
    )

    hid: Mapped[str] = _hid()
    catalog_entry_hid: Mapped[str | None] = mapped_column(
        ForeignKey("catalog_entries.hid"), default=None, index=True
    )
    serial_number: Mapped[str | None] = mapped_column(String(100), default=None)
    serial_key: Mapped[str | None] = mapped_column(String(100), default=None, index=True)
    mac_address: Mapped[str | None] = mapped_column(String(12), default=None, index=True)
    asset_tag: Mapped[str | None] = mapped_column(String(100), default=None)
    asset_tag_key: Mapped[str | None] = mapped_column(String(100), default=None, unique=True)
    name: Mapped[str | None] = mapped_column(String(200), default=None, index=True)
    hostname: Mapped[str | None] = mapped_column(String(255), default=None, index=True)
    fqdn: Mapped[str | None] = mapped_column(String(255), default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    comments: Mapped[str | None] = mapped_column(Text, default=None)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    lifecycle_state: Mapped[str | None] = mapped_column(String(20), default=None, index=True)
    disposition: Mapped[str | None] = mapped_column(String(12), default=None, index=True)
    expected_online: Mapped[bool | None] = mapped_column(Boolean, default=None)
    state_reason: Mapped[str | None] = mapped_column(String(40), default=None)
    state_changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    owner_hid: Mapped[str | None] = mapped_column(
        ForeignKey("owners.hid"), default=None, index=True
    )
    procured_on: Mapped[date | None] = mapped_column(Date, default=None)
    delivered_on: Mapped[date | None] = mapped_column(Date, default=None)
    in_service_on: Mapped[date | None] = mapped_column(Date, default=None)
    warranty_start: Mapped[date | None] = mapped_column(Date, default=None)
    warranty_end: Mapped[date | None] = mapped_column(Date, default=None)
    est_value: Mapped[Decimal | None] = mapped_column(Scaled(MONEY_PLACES), default=None)
    support_weight: Mapped[Decimal | None] = mapped_column(Scaled(WEIGHT_PLACES), default=None)
    annual_support_cost: Mapped[Decimal | None] = mapped_column(Scaled(MONEY_PLACES), default=None)
    end_of_sale: Mapped[date | None] = mapped_column(Date, default=None, index=True)
    end_of_sw_support: Mapped[date | None] = mapped_column(Date, default=None, index=True)
    end_of_hw_support: Mapped[date | None] = mapped_column(Date, default=None, index=True)
    ldos: Mapped[date | None] = mapped_column(Date, default=None, index=True)
    record_status: Mapped[str] = mapped_column(String(10), default="active")


class Tag(Bookkeeping, Base):
    """A label that may be put on most records."""

    __tablename__ = "tags"

    hid: Mapped[str] = _hid()
    label: Mapped[str] = mapped_column(String(100))
    label_key: Mapped[str] = mapped_column(String(100), unique=True)
    colour: Mapped[str | None] = mapped_column(String(20), default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)


class TagLink(Base):
    """One tag on one record."""

    __tablename__ = "tag_links"
    __table_args__ = (Index("tag_links_record", "record_type", "record_hid"),)

    tag_hid: Mapped[str] = mapped_column(ForeignKey("tags.hid"), primary_key=True)
    record_type: Mapped[str] = mapped_column(String(40), primary_key=True)
    record_hid: Mapped[str] = mapped_column(String(36), primary_key=True)


class Choice(Bookkeeping, Base):
    """One value of one editable list."""

    __tablename__ = "choices"
    __table_args__ = (UniqueConstraint("list", "value_key", name="choices_list_value"),)

    hid: Mapped[str] = _hid()
    list_name: Mapped[str] = mapped_column("list", String(40))
    value: Mapped[str] = mapped_column(String(40))
    value_key: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(100))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Setting(Bookkeeping, Base):
    """An installation-wide value that differs from its default."""

    __tablename__ = "settings"

    hid: Mapped[str] = _hid()
    key: Mapped[str] = mapped_column(String(60), unique=True)
    value: Mapped[Any] = mapped_column(JSON, default=None)


class LifecycleRule(Bookkeeping, Base):
    """What one lifecycle state allows, and where an item may move from it."""

    __tablename__ = "lifecycle_rules"

    hid: Mapped[str] = _hid()
    state: Mapped[str] = mapped_column(String(20), unique=True)
    sort: Mapped[int] = mapped_column(Integer)
    dispositions: Mapped[list[str]] = mapped_column(JSON, default=list)
    keeps_disposition: Mapped[bool] = mapped_column(Boolean, default=False)
    may_be_online: Mapped[list[str]] = mapped_column(JSON, default=list)
    must_be_online: Mapped[list[str]] = mapped_column(JSON, default=list)
    entry_disposition: Mapped[str | None] = mapped_column(String(12), default=None)
    entry_online: Mapped[bool | None] = mapped_column(Boolean, default=None)
    next_states: Mapped[list[str]] = mapped_column(JSON, default=list)
