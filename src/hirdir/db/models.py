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
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column, relationship

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

    Money, weights and percentages are kept in hundredths, so a sum is exact and a
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
WEIGHT_PLACES = 2
PERCENT_PLACES = 2
DEGREE_PLACES = 6
# The fields of an address. A shipping address is the same six with `ship_` before them.
ADDRESS_FIELDS = ("address1", "address2", "city", "state", "postal_code", "country")
SHIP_FIELDS = tuple(f"ship_{name}" for name in ADDRESS_FIELDS)


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

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:
        # Every UPDATE of a row names the version it was read at, so of two changes
        # made against one version the database lets only the first through. The new
        # version is set by `records.touch`, not generated here.
        return {"version_id_col": cls.row_version, "version_id_generator": False}


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
    __table_args__ = (UniqueConstraint("name_key", name="vendors_name"),)

    hid: Mapped[str] = _hid()
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200))
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    review_status: Mapped[str] = mapped_column(
        String(12), default="reviewed", server_default="reviewed"
    )


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


class StreetAddress:
    """Where a site or a location is."""

    address1: Mapped[str | None] = mapped_column(String(200), default=None)
    address2: Mapped[str | None] = mapped_column(String(200), default=None)
    city: Mapped[str | None] = mapped_column(String(200), default=None)
    state: Mapped[str | None] = mapped_column(String(200), default=None)
    postal_code: Mapped[str | None] = mapped_column(String(200), default=None)
    country: Mapped[str | None] = mapped_column(String(200), default=None)


class ShippingAddress:
    """Where deliveries for a place go, and what a carrier is to know."""

    ship_address1: Mapped[str | None] = mapped_column(String(200), default=None)
    ship_address2: Mapped[str | None] = mapped_column(String(200), default=None)
    ship_city: Mapped[str | None] = mapped_column(String(200), default=None)
    ship_state: Mapped[str | None] = mapped_column(String(200), default=None)
    ship_postal_code: Mapped[str | None] = mapped_column(String(200), default=None)
    ship_country: Mapped[str | None] = mapped_column(String(200), default=None)
    ship_instructions: Mapped[str | None] = mapped_column(Text, default=None)


class Contact(Bookkeeping, Base):
    """A person or a shared mailbox, to be assigned to places and to owners."""

    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("email_key", name="contacts_email"),)

    hid: Mapped[str] = _hid()
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200), index=True)
    organization: Mapped[str | None] = mapped_column(String(200), default=None)
    email: Mapped[str | None] = mapped_column(String(254), default=None)
    email_key: Mapped[str | None] = mapped_column(String(254), default=None)
    phone: Mapped[str | None] = mapped_column(String(50), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    record_status: Mapped[str] = mapped_column(String(10), default="active")


class Operator(Bookkeeping, Base):
    """A short label that stands for the member of the team who looks after what it is on.

    Items, groups and places hold the label and never the person, so the person behind
    it is changed in one place. With no contact it is an open assignment; retired, it
    stands for nothing.
    """

    __tablename__ = "operators"
    __table_args__ = (UniqueConstraint("label_key", name="operators_label"),)

    hid: Mapped[str] = _hid()
    label: Mapped[str] = mapped_column(String(40))
    label_key: Mapped[str] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    colour: Mapped[str | None] = mapped_column(String(20), default=None)
    contact_hid: Mapped[str | None] = mapped_column(
        ForeignKey("contacts.hid"), default=None, index=True
    )
    record_status: Mapped[str] = mapped_column(String(10), default="active")


class Region(Bookkeeping, ShippingAddress, Base):
    """A part of the world that sites are in. Regions nest to any depth."""

    __tablename__ = "regions"
    __table_args__ = (UniqueConstraint("code_key", name="regions_code"),)

    hid: Mapped[str] = _hid()
    code: Mapped[str | None] = mapped_column(String(40), default=None)
    code_key: Mapped[str | None] = mapped_column(String(40), default=None)
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200))
    parent_region_hid: Mapped[str | None] = mapped_column(
        ForeignKey("regions.hid"), default=None, index=True
    )
    operator_hid: Mapped[str | None] = mapped_column(
        ForeignKey("operators.hid"), default=None, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    record_status: Mapped[str] = mapped_column(String(10), default="active")


class Site(Bookkeeping, StreetAddress, ShippingAddress, Base):
    """A place the team works at: a campus, a building of its own, a colocation hall."""

    __tablename__ = "sites"
    __table_args__ = (
        UniqueConstraint("code_key", name="sites_code"),
        UniqueConstraint("region_hid", "name_key", name="sites_region_name"),
    )

    hid: Mapped[str] = _hid()
    code: Mapped[str | None] = mapped_column(String(40), default=None)
    code_key: Mapped[str | None] = mapped_column(String(40), default=None)
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200))
    region_hid: Mapped[str] = mapped_column(ForeignKey("regions.hid"), index=True)
    # Deliveries go to the street address: the shipping address is read from it.
    ship_same_as_address: Mapped[bool] = mapped_column(Boolean, default=False)
    operator_hid: Mapped[str | None] = mapped_column(
        ForeignKey("operators.hid"), default=None, index=True
    )
    latitude: Mapped[Decimal | None] = mapped_column(Scaled(DEGREE_PLACES), default=None)
    longitude: Mapped[Decimal | None] = mapped_column(Scaled(DEGREE_PLACES), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    record_status: Mapped[str] = mapped_column(String(10), default="active")


class Location(Bookkeeping, StreetAddress, ShippingAddress, Base):
    """A place within a site: a building, a floor, a room, a rack. Locations nest."""

    __tablename__ = "locations"
    __table_args__ = (UniqueConstraint("site_hid", "code_key", name="locations_site_code"),)

    hid: Mapped[str] = _hid()
    code: Mapped[str | None] = mapped_column(String(40), default=None)
    code_key: Mapped[str | None] = mapped_column(String(40), default=None)
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200))
    site_hid: Mapped[str] = mapped_column(ForeignKey("sites.hid"), index=True)
    parent_location_hid: Mapped[str | None] = mapped_column(
        ForeignKey("locations.hid"), default=None, index=True
    )
    kind: Mapped[str | None] = mapped_column(String(40), default=None)
    ship_same_as_address: Mapped[bool] = mapped_column(Boolean, default=False)
    operator_hid: Mapped[str | None] = mapped_column(
        ForeignKey("operators.hid"), default=None, index=True
    )
    latitude: Mapped[Decimal | None] = mapped_column(Scaled(DEGREE_PLACES), default=None)
    longitude: Mapped[Decimal | None] = mapped_column(Scaled(DEGREE_PLACES), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    record_status: Mapped[str] = mapped_column(String(10), default="active")


class ContactAssignment(Bookkeeping, Base):
    """A contact of one region, site or location, in one role.

    With no contact and `stop_inheritance` set it says: none here, and do not look
    further up.
    """

    __tablename__ = "contact_assignments"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN region_hid IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN site_hid IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN location_hid IS NULL THEN 0 ELSE 1 END) = 1",
            name="contact_assignments_one_place",
        ),
    )

    hid: Mapped[str] = _hid()
    contact_hid: Mapped[str | None] = mapped_column(
        ForeignKey("contacts.hid"), default=None, index=True
    )
    region_hid: Mapped[str | None] = mapped_column(
        ForeignKey("regions.hid"), default=None, index=True
    )
    site_hid: Mapped[str | None] = mapped_column(ForeignKey("sites.hid"), default=None, index=True)
    location_hid: Mapped[str | None] = mapped_column(
        ForeignKey("locations.hid"), default=None, index=True
    )
    role: Mapped[str] = mapped_column(String(40))
    priority: Mapped[int] = mapped_column(Integer, default=1)
    stop_inheritance: Mapped[bool] = mapped_column(Boolean, default=False)


class Owner(Bookkeeping, Base):
    """Who answers for an item."""

    __tablename__ = "owners"
    __table_args__ = (UniqueConstraint("label_key", name="owners_label"),)

    hid: Mapped[str] = _hid()
    label: Mapped[str] = mapped_column(String(200))
    label_key: Mapped[str] = mapped_column(String(200))
    organization: Mapped[str | None] = mapped_column(String(200), default=None)
    is_external: Mapped[bool] = mapped_column(Boolean, default=False)
    exception_reason: Mapped[str | None] = mapped_column(Text, default=None)
    record_status: Mapped[str] = mapped_column(String(10), default="active")


class OwnerMember(Bookkeeping, Base):
    """One of the people of an owner: its primary, or an alternate."""

    __tablename__ = "owner_members"
    __table_args__ = (UniqueConstraint("owner_hid", "contact_hid", name="owner_members_once"),)

    hid: Mapped[str] = _hid()
    owner_hid: Mapped[str] = mapped_column(ForeignKey("owners.hid"), index=True)
    contact_hid: Mapped[str] = mapped_column(ForeignKey("contacts.hid"), index=True)
    role: Mapped[str] = mapped_column(String(10))
    priority: Mapped[int] = mapped_column(Integer, default=1)


class Item(Bookkeeping, Base):
    """One tracked thing: hardware, a virtual machine, a software application or a service."""

    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("asset_tag_key", name="items_asset_tag"),
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
    asset_tag_key: Mapped[str | None] = mapped_column(String(100), default=None)
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
    condition: Mapped[str | None] = mapped_column(String(40), default=None, index=True)
    observed_status: Mapped[str | None] = mapped_column(String(12), default=None, index=True)
    observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    owner_hid: Mapped[str | None] = mapped_column(
        ForeignKey("owners.hid"), default=None, index=True
    )
    location_hid: Mapped[str | None] = mapped_column(
        ForeignKey("locations.hid"), default=None, index=True
    )
    # The label of the person of the team who looks after it.
    operator_hid: Mapped[str | None] = mapped_column(
        ForeignKey("operators.hid"), default=None, index=True
    )
    parent_item_hid: Mapped[str | None] = mapped_column(
        ForeignKey("items.hid"), default=None, index=True
    )
    position: Mapped[str | None] = mapped_column(String(100), default=None)
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


class ItemReplacement(Bookkeeping, Base):
    """One item that took the place of another. Both records remain."""

    __tablename__ = "item_replacements"
    __table_args__ = (
        UniqueConstraint("old_item_hid", name="item_replacements_old"),
        UniqueConstraint("new_item_hid", name="item_replacements_new"),
    )

    hid: Mapped[str] = _hid()
    old_item_hid: Mapped[str] = mapped_column(ForeignKey("items.hid"))
    new_item_hid: Mapped[str] = mapped_column(ForeignKey("items.hid"))
    reason: Mapped[str] = mapped_column(String(40))
    reference: Mapped[str | None] = mapped_column(String(200), default=None)
    replaced_on: Mapped[date] = mapped_column(Date)


class DeviceGroup(Bookkeeping, Base):
    """A labelled set of items with roles: a stack, a cluster, a controller with its endpoints."""

    __tablename__ = "device_groups"
    __table_args__ = (UniqueConstraint("name_key", name="device_groups_name"),)

    hid: Mapped[str] = _hid()
    type: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200))
    hostname: Mapped[str | None] = mapped_column(String(255), default=None)
    fqdn: Mapped[str | None] = mapped_column(String(255), default=None)
    parent_group_hid: Mapped[str | None] = mapped_column(
        ForeignKey("device_groups.hid"), default=None, index=True
    )
    owner_hid: Mapped[str | None] = mapped_column(
        ForeignKey("owners.hid"), default=None, index=True
    )
    location_hid: Mapped[str | None] = mapped_column(
        ForeignKey("locations.hid"), default=None, index=True
    )
    # Who looks after the group, and after its members that have none of their own.
    operator_hid: Mapped[str | None] = mapped_column(
        ForeignKey("operators.hid"), default=None, index=True
    )
    # How a cluster is managed: as one node, as its members, or as both.
    managed_as: Mapped[str | None] = mapped_column(String(20), default=None)
    expected_members: Mapped[int | None] = mapped_column(Integer, default=None)
    observed_status: Mapped[str | None] = mapped_column(String(12), default=None)
    observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    # The member of a stack that is seen to be master, which the stack decides itself.
    observed_master_hid: Mapped[str | None] = mapped_column(ForeignKey("items.hid"), default=None)
    master_observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    record_status: Mapped[str] = mapped_column(String(10), default="active")


class DeviceGroupMember(Bookkeeping, Base):
    """One item's time in one group. A blank `left_on` means it is a member now."""

    __tablename__ = "device_group_members"

    hid: Mapped[str] = _hid()
    group_hid: Mapped[str] = mapped_column(ForeignKey("device_groups.hid"), index=True)
    item_hid: Mapped[str] = mapped_column(ForeignKey("items.hid"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    position: Mapped[int | None] = mapped_column(Integer, default=None)
    joined_on: Mapped[date] = mapped_column(Date)
    left_on: Mapped[date | None] = mapped_column(Date, default=None)


class Network(Bookkeeping, Base):
    """A label for an address space: a VRF, a tenant, a coloured network."""

    __tablename__ = "networks"
    __table_args__ = (UniqueConstraint("label_key", name="networks_label"),)

    hid: Mapped[str] = _hid()
    label: Mapped[str] = mapped_column(String(100))
    label_key: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(10), default="network")


class Address(Bookkeeping, Base):
    """One IPv4 or IPv6 address of an item or of a device group."""

    __tablename__ = "addresses"
    __table_args__ = (
        CheckConstraint(
            "(item_hid IS NULL) <> (group_hid IS NULL)",
            name="addresses_one_holder",
        ),
    )

    hid: Mapped[str] = _hid()
    item_hid: Mapped[str | None] = mapped_column(ForeignKey("items.hid"), default=None, index=True)
    group_hid: Mapped[str | None] = mapped_column(
        ForeignKey("device_groups.hid"), default=None, index=True
    )
    address: Mapped[str] = mapped_column(String(45), index=True)
    network_hid: Mapped[str | None] = mapped_column(
        ForeignKey("networks.hid"), default=None, index=True
    )
    role: Mapped[str] = mapped_column(String(12), default="management")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)


class Tag(Bookkeeping, Base):
    """A label that may be put on most records."""

    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("label_key", name="tags_label"),)

    hid: Mapped[str] = _hid()
    label: Mapped[str] = mapped_column(String(100))
    label_key: Mapped[str] = mapped_column(String(100))
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
    __table_args__ = (UniqueConstraint("key", name="settings_key"),)

    hid: Mapped[str] = _hid()
    key: Mapped[str] = mapped_column(String(60))
    value: Mapped[Any] = mapped_column(JSON, default=None)


class LifecycleRule(Bookkeeping, Base):
    """What one lifecycle state allows, and where an item may move from it."""

    __tablename__ = "lifecycle_rules"
    __table_args__ = (UniqueConstraint("state", name="lifecycle_rules_state"),)

    hid: Mapped[str] = _hid()
    state: Mapped[str] = mapped_column(String(20))
    sort: Mapped[int] = mapped_column(Integer)
    dispositions: Mapped[list[str]] = mapped_column(JSON, default=list)
    keeps_disposition: Mapped[bool] = mapped_column(Boolean, default=False)
    may_be_online: Mapped[list[str]] = mapped_column(JSON, default=list)
    must_be_online: Mapped[list[str]] = mapped_column(JSON, default=list)
    entry_disposition: Mapped[str | None] = mapped_column(String(12), default=None)
    entry_online: Mapped[bool | None] = mapped_column(Boolean, default=None)
    next_states: Mapped[list[str]] = mapped_column(JSON, default=list)


# --- changes to many records ---------------------------------------------------------


class ImportJob(Base):
    """A preview of an import or a bulk edit, kept so that what is applied is what was shown."""

    __tablename__ = "import_jobs"
    __table_args__ = (Index("import_jobs_created_at", "created_at"),)

    hid: Mapped[str] = _hid()
    source: Mapped[str] = mapped_column(String(10))
    entity: Mapped[str] = mapped_column(String(40))
    mode: Mapped[str] = mapped_column(String(10))
    file_name: Mapped[str | None] = mapped_column(String(255), default=None)
    file_sha256: Mapped[str | None] = mapped_column(String(64), default=None)
    status: Mapped[str] = mapped_column(String(10), default="previewed")
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    unchanged: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    skip_rejected: Mapped[bool | None] = mapped_column(Boolean, default=None)
    failure: Mapped[str | None] = mapped_column(Text, default=None)
    applied_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    applied_by: Mapped[str | None] = mapped_column(String(36), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=clock.now)
    created_by: Mapped[str | None] = mapped_column(String(36), default=None)


class ImportRow(Base):
    """One row of a previewed import or bulk edit: what it holds and what it would do."""

    __tablename__ = "import_rows"

    job_hid: Mapped[str] = mapped_column(ForeignKey("import_jobs.hid"), primary_key=True)
    row: Mapped[int] = mapped_column(Integer, primary_key=True)
    outcome: Mapped[str] = mapped_column(String(10), index=True)
    record_hid: Mapped[str | None] = mapped_column(String(36), default=None)
    row_version: Mapped[int | None] = mapped_column(Integer, default=None)
    key: Mapped[str] = mapped_column(Text, default="")
    values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    notes: Mapped[list[str]] = mapped_column(JSON, default=list)


class IdempotencyKey(Base):
    """A key a caller sent with a request, and the answer it was given."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (Index("idempotency_keys_created_at", "created_at"),)

    user_hid: Mapped[str] = mapped_column(String(36), primary_key=True)
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    request_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[int | None] = mapped_column(Integer, default=None)
    body: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=clock.now)
