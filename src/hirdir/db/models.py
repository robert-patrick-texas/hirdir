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
    """A person who signs in, a service account or an agent, which hold tokens.

    A user is a part that a person plays: the person is a contact, whose name, email
    and numbers the user shows, read when it is read. A service account is no person
    and has no contact (P-172), and nor has an agent, which is answerable to a person
    (P-316).
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("contact_hid", name="users_contact"),)

    hid: Mapped[str] = _hid()
    username: Mapped[str] = mapped_column(String(64))
    username_key: Mapped[str] = mapped_column(String(64), unique=True)
    contact_hid: Mapped[str | None] = mapped_column(ForeignKey("contacts.hid"), default=None)
    # `person`, `service` or `agent`, set when the account is made and not changed
    # after (P-316).
    kind: Mapped[str] = mapped_column(String(10), default="person")
    # An agent's alone, and required of it: the person answerable for it (P-316).
    answerable_hid: Mapped[str | None] = mapped_column(
        ForeignKey("users.hid"), default=None, index=True
    )
    access_code_hash: Mapped[str | None] = mapped_column(Text, default=None)
    tokens_valid_after: Mapped[int] = mapped_column(BigInteger, default=0)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_sign_in_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    # What the account is for, who asked for it, when it is to end (P-281). The notes
    # of the person are the contact's.
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    # `active` or `retired` (P-296): a retired account is that of somebody who has
    # left. `disabled`, beside it, is one that may not sign in for now.
    record_status: Mapped[str] = mapped_column(String(10), default="active")

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
        # The events of one account, and of the accounts of one kind, and those made for
        # one person by agents (P-316).
        Index("audit_events_actor", "actor_hid"),
        Index("audit_events_for", "for_hid"),
    )

    hid: Mapped[str] = _hid()
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=clock.now)
    actor_hid: Mapped[str | None] = mapped_column(String(36), default=None)
    # Where the actor is an agent, the person it was answerable to when the event was
    # made (P-316).
    for_hid: Mapped[str | None] = mapped_column(String(36), default=None)
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
    # Its support is not renewed: what came with its purchase is not bought again.
    do_not_renew: Mapped[bool] = mapped_column(Boolean, default=False)
    # Addresses to reach about the model, each with its text, in the order given.
    links: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
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
    """A person or a shared mailbox: the one list of people.

    It is assigned to places and to owners, and a user and an operator are each a part
    that a contact plays, holding only what belongs to that part (P-172).
    """

    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("email_key", name="contacts_email"),)

    hid: Mapped[str] = _hid()
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200), index=True)
    organization: Mapped[str | None] = mapped_column(String(200), default=None)
    email: Mapped[str | None] = mapped_column(String(254), default=None)
    email_key: Mapped[str | None] = mapped_column(String(254), default=None)
    phone: Mapped[str | None] = mapped_column(String(50), default=None)
    phone2: Mapped[str | None] = mapped_column(String(50), default=None)
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
    # The work supporting the network there adds by itself, beside its devices. Not
    # passed down to the places beneath (P-139).
    support_weight: Mapped[Decimal | None] = mapped_column(Scaled(WEIGHT_PLACES), default=None)
    # Addresses to reach about the place, each with its text. Not passed down.
    links: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
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
    # The work supporting the network there adds by itself, beside its devices. Not
    # passed down to the places beneath (P-139).
    support_weight: Mapped[Decimal | None] = mapped_column(Scaled(WEIGHT_PLACES), default=None)
    # Addresses to reach about the place, each with its text. Not passed down.
    links: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
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
    # The work supporting the network there adds by itself, beside its devices. Not
    # passed down to the places beneath (P-139).
    support_weight: Mapped[Decimal | None] = mapped_column(Scaled(WEIGHT_PLACES), default=None)
    # Addresses to reach about the place, each with its text. Not passed down.
    links: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
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
        CheckConstraint("host_item_hid IS NULL OR host_group_hid IS NULL", name="items_one_host"),
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
    # Where it is going, when that place is not in use yet.
    planned_location_hid: Mapped[str | None] = mapped_column(
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
    # What it runs on, for a virtual machine, a virtual context and a container (P-246):
    # the host a person names, an item or a stack or a cluster, and the item it was seen on.
    host_item_hid: Mapped[str | None] = mapped_column(
        ForeignKey("items.hid", name="fk_items_host_item_hid"), default=None, index=True
    )
    host_group_hid: Mapped[str | None] = mapped_column(
        # A group names items too, the master that was seen: this key is made after both
        # tables are, so that they are made in an order.
        ForeignKey("device_groups.hid", name="fk_items_host_group_hid", use_alter=True),
        default=None,
        index=True,
    )
    observed_host_hid: Mapped[str | None] = mapped_column(
        ForeignKey("items.hid", name="fk_items_observed_host_hid"), default=None, index=True
    )
    host_observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    # The line of a purchase request it arrived on.
    purchase_line_hid: Mapped[str | None] = mapped_column(
        ForeignKey("purchase_lines.hid"), default=None, index=True
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
    # Its support is not renewed, or is, against what its model says. Blank: the model's.
    do_not_renew: Mapped[bool | None] = mapped_column(Boolean, default=None)
    record_status: Mapped[str] = mapped_column(String(10), default="active")


class ItemReplacement(Bookkeeping, Base):
    """One item that took the place of another. Both records remain."""

    __tablename__ = "item_replacements"
    # An item is replaced, and takes a place, as often as that happens (P-241): what is
    # unique is the two items with the day.
    __table_args__ = (
        UniqueConstraint(
            "old_item_hid", "new_item_hid", "replaced_on", name="item_replacements_pair_day"
        ),
    )

    hid: Mapped[str] = _hid()
    old_item_hid: Mapped[str] = mapped_column(ForeignKey("items.hid"), index=True)
    new_item_hid: Mapped[str] = mapped_column(ForeignKey("items.hid"), index=True)
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
    # Where the group is going, when that place is not in use yet.
    planned_location_hid: Mapped[str | None] = mapped_column(
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


class Agreement(Bookkeeping, Base):
    """A support agreement with a vendor, such as an enterprise agreement, that groups
    contracts. What it says of whom to ask, and of its period, is had by each contract
    in it that says nothing of its own."""

    __tablename__ = "agreements"
    __table_args__ = (UniqueConstraint("name_key", name="agreements_name"),)

    hid: Mapped[str] = _hid()
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200))
    number: Mapped[str | None] = mapped_column(String(100), default=None)
    vendor_hid: Mapped[str] = mapped_column(ForeignKey("vendors.hid"), index=True)
    reseller_hid: Mapped[str | None] = mapped_column(
        ForeignKey("vendors.hid"), default=None, index=True
    )
    starts_on: Mapped[date | None] = mapped_column(Date, default=None)
    ends_on: Mapped[date | None] = mapped_column(Date, default=None)
    status: Mapped[str] = mapped_column(String(20), default="active")
    support_level: Mapped[str | None] = mapped_column(String(200), default=None)
    purchase_reference: Mapped[str | None] = mapped_column(String(200), default=None)
    account_manager: Mapped[str | None] = mapped_column(Text, default=None)
    support_contact: Mapped[str | None] = mapped_column(Text, default=None)
    support_url: Mapped[str | None] = mapped_column(String(2000), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    annual_cost: Mapped[Decimal | None] = mapped_column(Scaled(MONEY_PLACES), default=None)
    # The term that follows, where a renewal was entered before its period began. From
    # the day it starts it is the term in force, worked out when the record is read.
    next_number: Mapped[str | None] = mapped_column(String(100), default=None)
    next_starts_on: Mapped[date | None] = mapped_column(Date, default=None)
    next_ends_on: Mapped[date | None] = mapped_column(Date, default=None)
    next_annual_cost: Mapped[Decimal | None] = mapped_column(Scaled(MONEY_PLACES), default=None)
    next_purchase_reference: Mapped[str | None] = mapped_column(String(200), default=None)
    record_status: Mapped[str] = mapped_column(String(10), default="active")


class Contract(Bookkeeping, Base):
    """A support contract with a vendor, which covers items for a range of days."""

    __tablename__ = "contracts"
    __table_args__ = (UniqueConstraint("vendor_hid", "number_key", name="contracts_vendor_number"),)

    hid: Mapped[str] = _hid()
    number: Mapped[str] = mapped_column(String(100))
    number_key: Mapped[str] = mapped_column(String(100), index=True)
    vendor_hid: Mapped[str] = mapped_column(ForeignKey("vendors.hid"), index=True)
    # The agreement it is grouped into. What the contract leaves blank it has from there.
    agreement_hid: Mapped[str | None] = mapped_column(
        ForeignKey("agreements.hid"), default=None, index=True
    )
    # Whom it was bought through, where that is not the vendor itself.
    reseller_hid: Mapped[str | None] = mapped_column(
        ForeignKey("vendors.hid"), default=None, index=True
    )
    starts_on: Mapped[date | None] = mapped_column(Date, default=None)
    ends_on: Mapped[date | None] = mapped_column(Date, default=None)
    # What a person says of the contract. The clock never changes it.
    status: Mapped[str] = mapped_column(String(20), default="active")
    support_level: Mapped[str | None] = mapped_column(String(200), default=None)
    # The request or the tracking number this term was bought under.
    purchase_reference: Mapped[str | None] = mapped_column(String(200), default=None)
    # Who to ask, as free text: nobody keeps a contact record for a vendor's desk.
    account_manager: Mapped[str | None] = mapped_column(Text, default=None)
    support_contact: Mapped[str | None] = mapped_column(Text, default=None)
    support_url: Mapped[str | None] = mapped_column(String(2000), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    annual_cost: Mapped[Decimal | None] = mapped_column(Scaled(MONEY_PLACES), default=None)
    # The term that follows, where a renewal was entered before its period began. From
    # the day it starts it is the term in force, worked out when the record is read.
    next_number: Mapped[str | None] = mapped_column(String(100), default=None)
    next_starts_on: Mapped[date | None] = mapped_column(Date, default=None)
    next_ends_on: Mapped[date | None] = mapped_column(Date, default=None)
    next_annual_cost: Mapped[Decimal | None] = mapped_column(Scaled(MONEY_PLACES), default=None)
    next_purchase_reference: Mapped[str | None] = mapped_column(String(200), default=None)
    # The next term is a new number that waits on the agreement's next term, and has no
    # dates of its own: it is in force from the day the agreement's is.
    next_with_agreement: Mapped[bool] = mapped_column(Boolean, default=False)
    # Not to be renewed: it ends with its present term, and is expired from the next day.
    ends_with_term: Mapped[bool] = mapped_column(Boolean, default=False)
    record_status: Mapped[str] = mapped_column(String(10), default="active")


class ContractContact(Bookkeeping, Base):
    """A contact record named for an agreement or a contract, in one of two roles."""

    __tablename__ = "contract_contacts"
    __table_args__ = (
        CheckConstraint(
            "(agreement_hid IS NULL) <> (contract_hid IS NULL)", name="contract_contacts_one_holder"
        ),
        UniqueConstraint(
            "agreement_hid", "role", "contact_hid", name="contract_contacts_agreement_once"
        ),
        UniqueConstraint(
            "contract_hid", "role", "contact_hid", name="contract_contacts_contract_once"
        ),
    )

    hid: Mapped[str] = _hid()
    agreement_hid: Mapped[str | None] = mapped_column(
        ForeignKey("agreements.hid"), default=None, index=True
    )
    contract_hid: Mapped[str | None] = mapped_column(
        ForeignKey("contracts.hid"), default=None, index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    contact_hid: Mapped[str] = mapped_column(ForeignKey("contacts.hid"), index=True)
    priority: Mapped[int] = mapped_column(Integer)


class ContractCoverage(Bookkeeping, Base):
    """One item under one contract for a range of days. A blank date is the contract's."""

    __tablename__ = "contract_coverage"

    hid: Mapped[str] = _hid()
    contract_hid: Mapped[str] = mapped_column(ForeignKey("contracts.hid"), index=True)
    item_hid: Mapped[str] = mapped_column(ForeignKey("items.hid"), index=True)
    starts_on: Mapped[date | None] = mapped_column(Date, default=None)
    ends_on: Mapped[date | None] = mapped_column(Date, default=None)
    # Ended by hirdir on the day its item left service. The vendor still counts the
    # item until somebody says so, and a person clears this once the vendor is told.
    left_service: Mapped[bool] = mapped_column(Boolean, default=False)


class PurchaseRequest(Bookkeeping, Base):
    """An internal request to buy, with lines of model and quantity."""

    __tablename__ = "purchase_requests"
    __table_args__ = (UniqueConstraint("reference_key", name="purchase_requests_reference"),)

    hid: Mapped[str] = _hid()
    reference: Mapped[str] = mapped_column(String(100))
    reference_key: Mapped[str] = mapped_column(String(100))
    requested_on: Mapped[date | None] = mapped_column(Date, default=None)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    notes: Mapped[str | None] = mapped_column(Text, default=None)


class PurchaseLine(Bookkeeping, Base):
    """One line of a purchase request: a model and how many, before any serial number."""

    __tablename__ = "purchase_lines"
    __table_args__ = (UniqueConstraint("request_hid", "line", name="purchase_lines_request_line"),)

    hid: Mapped[str] = _hid()
    request_hid: Mapped[str] = mapped_column(ForeignKey("purchase_requests.hid"), index=True)
    line: Mapped[int] = mapped_column(Integer)
    # The model. A line with none is not tracked: cable ties, a monitor, a printer.
    catalog_entry_hid: Mapped[str | None] = mapped_column(
        ForeignKey("catalog_entries.hid"), default=None, index=True
    )
    # As the procurement system gave them.
    part_number: Mapped[str | None] = mapped_column(String(100), default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    quantity: Mapped[int] = mapped_column(Integer)
    destination_site_hid: Mapped[str | None] = mapped_column(
        ForeignKey("sites.hid"), default=None, index=True
    )
    expected_on: Mapped[date | None] = mapped_column(Date, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)


class ExternalSystem(Bookkeeping, Base):
    """Another system that knows items or groups: a monitoring tool, an SDN controller."""

    __tablename__ = "external_systems"
    __table_args__ = (UniqueConstraint("name_key", name="external_systems_name"),)

    hid: Mapped[str] = _hid()
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40), default="other")
    url: Mapped[str | None] = mapped_column(String(2000), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    record_status: Mapped[str] = mapped_column(String(10), default="active")


class Registration(Bookkeeping, Base):
    """An item or a device group as one external system knows it."""

    __tablename__ = "registrations"
    __table_args__ = (
        CheckConstraint(
            "(item_hid IS NULL) <> (group_hid IS NULL)",
            name="registrations_one_holder",
        ),
        UniqueConstraint("system_hid", "item_hid", name="registrations_system_item"),
        UniqueConstraint("system_hid", "group_hid", name="registrations_system_group"),
    )

    hid: Mapped[str] = _hid()
    system_hid: Mapped[str] = mapped_column(ForeignKey("external_systems.hid"), index=True)
    item_hid: Mapped[str | None] = mapped_column(ForeignKey("items.hid"), default=None, index=True)
    group_hid: Mapped[str | None] = mapped_column(
        ForeignKey("device_groups.hid"), default=None, index=True
    )
    external_id: Mapped[str | None] = mapped_column(String(200), default=None)
    status: Mapped[str] = mapped_column(String(12), default="registered")
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class CapacityLine(Bookkeeping, Base):
    """A source of resource units, or a call on them other than the infrastructure."""

    __tablename__ = "capacity_lines"
    __table_args__ = (
        UniqueConstraint("side", "name_key", name="capacity_lines_side_name"),
        CheckConstraint("region_hid IS NULL OR site_hid IS NULL", name="capacity_lines_one_place"),
    )

    hid: Mapped[str] = _hid()
    side: Mapped[str] = mapped_column(String(10))
    category: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200))
    # `add` a fixed amount, or `multiply` the staff lines it applies to.
    effect: Mapped[str] = mapped_column(String(10), default="add")
    quantity: Mapped[Decimal | None] = mapped_column(Scaled(WEIGHT_PLACES), default=Decimal(1))
    units_each: Mapped[Decimal | None] = mapped_column(Scaled(WEIGHT_PLACES), default=Decimal(0))
    factor: Mapped[Decimal | None] = mapped_column(Scaled(WEIGHT_PLACES), default=None)
    share: Mapped[Decimal | None] = mapped_column(Scaled(WEIGHT_PLACES), default=None)
    annual_cost: Mapped[Decimal | None] = mapped_column(Scaled(MONEY_PLACES), default=None)
    vendor_hid: Mapped[str | None] = mapped_column(
        ForeignKey("vendors.hid"), default=None, index=True
    )
    region_hid: Mapped[str | None] = mapped_column(
        ForeignKey("regions.hid"), default=None, index=True
    )
    site_hid: Mapped[str | None] = mapped_column(ForeignKey("sites.hid"), default=None, index=True)
    starts_on: Mapped[date | None] = mapped_column(Date, default=None)
    ends_on: Mapped[date | None] = mapped_column(Date, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    record_status: Mapped[str] = mapped_column(String(10), default="active")


class CapacityLineTarget(Base):
    """A staff line that a line which multiplies works on."""

    __tablename__ = "capacity_line_targets"

    line_hid: Mapped[str] = mapped_column(ForeignKey("capacity_lines.hid"), primary_key=True)
    target_hid: Mapped[str] = mapped_column(
        ForeignKey("capacity_lines.hid"), primary_key=True, index=True
    )


class CapacityRecord(Bookkeeping, Base):
    """The capacity balance as it was in a week, kept to show the trend."""

    __tablename__ = "capacity_records"
    __table_args__ = (UniqueConstraint("week_of", name="capacity_records_week"),)

    hid: Mapped[str] = _hid()
    # The Monday that begins the week, in the application's time zone.
    week_of: Mapped[date] = mapped_column(Date)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime, default=clock.now)
    weight_per_resource_unit: Mapped[Decimal] = mapped_column(Scaled(WEIGHT_PLACES))
    active: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    with_drafts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # A person has corrected the figures, and the note says why.
    adjusted: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text, default=None)


class Circuit(Bookkeeping, Base):
    """A telecommunication circuit beside the inventory (D-157, D-158, P-145).

    Its ends are locations, its carriers vendors, its owner an owner: nothing that the
    inventory holds is typed again.
    """

    __tablename__ = "circuits"
    __table_args__ = (
        UniqueConstraint("enterprise_circuit_id_key", name="circuits_enterprise_circuit_id"),
        UniqueConstraint("carrier_hid", "carrier_number_key", name="circuits_carrier_number"),
        CheckConstraint(
            "a_location_hid IS NOT NULL OR z_location_hid IS NOT NULL", name="circuits_one_side"
        ),
        CheckConstraint(
            "z_location_hid IS NULL OR z_group_hid IS NULL", name="circuits_z_location_or_group"
        ),
    )

    hid: Mapped[str] = _hid()
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200), index=True)
    # The enterprise's own ID, assigned locally, as an asset tag is.
    enterprise_circuit_id: Mapped[str | None] = mapped_column(String(100), default=None)
    enterprise_circuit_id_key: Mapped[str | None] = mapped_column(String(100), default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    circuit_type: Mapped[str | None] = mapped_column(String(40), default=None)
    # The speed of the port, and the rates it is limited to; a blank rate is the port's.
    port_mbps: Mapped[Decimal | None] = mapped_column(Scaled(2), default=None)
    down_mbps: Mapped[Decimal | None] = mapped_column(Scaled(2), default=None)
    up_mbps: Mapped[Decimal | None] = mapped_column(Scaled(2), default=None)
    # The two sides: a location each, or a note of where an end outside is.
    a_location_hid: Mapped[str | None] = mapped_column(
        ForeignKey("locations.hid"), default=None, index=True
    )
    a_note: Mapped[str | None] = mapped_column(String(200), default=None)
    z_location_hid: Mapped[str | None] = mapped_column(
        ForeignKey("locations.hid"), default=None, index=True
    )
    z_note: Mapped[str | None] = mapped_column(String(200), default=None)
    # The network the Z side reaches: a circuit group of the kind `network` (P-319).
    z_group_hid: Mapped[str | None] = mapped_column(
        ForeignKey("circuit_groups.hid"), default=None, index=True
    )
    # The side whose site its cost and weight count at: given once, when it is made.
    cost_side: Mapped[str] = mapped_column(String(1), default="a")
    # The primary carrier, or the other party that provides it, and its number.
    carrier_hid: Mapped[str | None] = mapped_column(
        ForeignKey("vendors.hid"), default=None, index=True
    )
    carrier_circuit_number: Mapped[str | None] = mapped_column(String(100), default=None)
    carrier_number_key: Mapped[str | None] = mapped_column(String(100), default=None, index=True)
    billing_account: Mapped[str | None] = mapped_column(String(100), default=None)
    billing_contract: Mapped[str | None] = mapped_column(String(200), default=None)
    # The dates of each side (P-317): a blank one of the Z side is read as the A side's.
    a_installed_on: Mapped[date | None] = mapped_column(Date, default=None)
    a_activated_on: Mapped[date | None] = mapped_column(Date, default=None)
    a_disconnected_on: Mapped[date | None] = mapped_column(Date, default=None)
    z_installed_on: Mapped[date | None] = mapped_column(Date, default=None)
    z_activated_on: Mapped[date | None] = mapped_column(Date, default=None)
    z_disconnected_on: Mapped[date | None] = mapped_column(Date, default=None)
    production: Mapped[bool] = mapped_column(Boolean, default=True)
    support_weight: Mapped[Decimal | None] = mapped_column(Scaled(WEIGHT_PLACES), default=None)
    owner_hid: Mapped[str | None] = mapped_column(
        ForeignKey("owners.hid"), default=None, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    record_status: Mapped[str] = mapped_column(String(10), default="active")


class CircuitCarrier(Bookkeeping, Base):
    """A carrier of a circuit beside its primary one, in its part, with its number."""

    __tablename__ = "circuit_carriers"
    __table_args__ = (
        UniqueConstraint("circuit_hid", "vendor_hid", name="circuit_carriers_once"),
        UniqueConstraint("vendor_hid", "circuit_number_key", name="circuit_carriers_number"),
    )

    hid: Mapped[str] = _hid()
    circuit_hid: Mapped[str] = mapped_column(ForeignKey("circuits.hid"), index=True)
    vendor_hid: Mapped[str] = mapped_column(ForeignKey("vendors.hid"), index=True)
    role: Mapped[str] = mapped_column(String(40))
    circuit_number: Mapped[str | None] = mapped_column(String(100), default=None)
    circuit_number_key: Mapped[str | None] = mapped_column(String(100), default=None, index=True)
    priority: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text, default=None)


class CircuitCost(Bookkeeping, Base):
    """One line of what a carrier bills for a circuit each month."""

    __tablename__ = "circuit_costs"
    __table_args__ = (
        UniqueConstraint("circuit_hid", "description_key", name="circuit_costs_description"),
    )

    hid: Mapped[str] = _hid()
    circuit_hid: Mapped[str] = mapped_column(ForeignKey("circuits.hid"), index=True)
    description: Mapped[str] = mapped_column(String(200))
    description_key: Mapped[str] = mapped_column(String(200))
    monthly_cost: Mapped[Decimal] = mapped_column(Scaled(MONEY_PLACES))
    # The carrier that bills the line; blank is the circuit's primary carrier.
    vendor_hid: Mapped[str | None] = mapped_column(
        ForeignKey("vendors.hid"), default=None, index=True
    )
    starts_on: Mapped[date | None] = mapped_column(Date, default=None)
    ends_on: Mapped[date | None] = mapped_column(Date, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)


class CircuitDevice(Bookkeeping, Base):
    """An item or a device group that a circuit connects, on one of its sides."""

    __tablename__ = "circuit_devices"
    __table_args__ = (
        CheckConstraint("(item_hid IS NULL) <> (group_hid IS NULL)", name="circuit_devices_one"),
        UniqueConstraint("circuit_hid", "item_hid", name="circuit_devices_item_once"),
        UniqueConstraint("circuit_hid", "group_hid", name="circuit_devices_group_once"),
    )

    hid: Mapped[str] = _hid()
    circuit_hid: Mapped[str] = mapped_column(ForeignKey("circuits.hid"), index=True)
    item_hid: Mapped[str | None] = mapped_column(ForeignKey("items.hid"), default=None, index=True)
    group_hid: Mapped[str | None] = mapped_column(
        ForeignKey("device_groups.hid"), default=None, index=True
    )
    side: Mapped[str] = mapped_column(String(1))
    notes: Mapped[str | None] = mapped_column(Text, default=None)


class VendorContact(Bookkeeping, Base):
    """A contact record named for a vendor: its account team or its support desk."""

    __tablename__ = "vendor_contacts"
    __table_args__ = (
        UniqueConstraint("vendor_hid", "role", "contact_hid", name="vendor_contacts_once"),
    )

    hid: Mapped[str] = _hid()
    vendor_hid: Mapped[str] = mapped_column(ForeignKey("vendors.hid"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    contact_hid: Mapped[str] = mapped_column(ForeignKey("contacts.hid"), index=True)
    priority: Mapped[int] = mapped_column(Integer)


class CircuitContact(Bookkeeping, Base):
    """A contact a circuit names of its own: the carrier's, or a site contact of a side."""

    __tablename__ = "circuit_contacts"
    __table_args__ = (
        UniqueConstraint(
            "circuit_hid", "side", "role", "contact_hid", name="circuit_contacts_once"
        ),
    )

    hid: Mapped[str] = _hid()
    circuit_hid: Mapped[str] = mapped_column(ForeignKey("circuits.hid"), index=True)
    # Blank for one of the carrier's; `a` or `z` for a site contact of that side.
    side: Mapped[str | None] = mapped_column(String(1), default=None)
    role: Mapped[str] = mapped_column(String(40))
    contact_hid: Mapped[str] = mapped_column(ForeignKey("contacts.hid"), index=True)
    priority: Mapped[int] = mapped_column(Integer)


class CircuitGroup(Bookkeeping, Base):
    """Circuits looked at and costed together, which may land at different sites.

    A group is a `network`, a carrier's network or the internet that a circuit's Z side
    reaches, or a `collection` of circuits for the enterprise's own purpose (P-319).
    """

    __tablename__ = "circuit_groups"
    __table_args__ = (UniqueConstraint("name_key", name="circuit_groups_name"),)

    hid: Mapped[str] = _hid()
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="collection")
    # A network's carrier, a vendor; a collection has none.
    carrier_hid: Mapped[str | None] = mapped_column(
        ForeignKey("vendors.hid"), default=None, index=True
    )
    description: Mapped[str | None] = mapped_column(Text, default=None)
    owner_hid: Mapped[str | None] = mapped_column(
        ForeignKey("owners.hid"), default=None, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    record_status: Mapped[str] = mapped_column(String(10), default="active")


class CircuitGroupMember(Bookkeeping, Base):
    """One circuit in one group. A circuit may be in several groups."""

    __tablename__ = "circuit_group_members"
    __table_args__ = (
        UniqueConstraint("group_hid", "circuit_hid", name="circuit_group_members_once"),
    )

    hid: Mapped[str] = _hid()
    group_hid: Mapped[str] = mapped_column(ForeignKey("circuit_groups.hid"), index=True)
    circuit_hid: Mapped[str] = mapped_column(ForeignKey("circuits.hid"), index=True)


class ReferenceFile(Bookkeeping, Base):
    """A reference: a file kept by hirdir, or a link to one kept elsewhere (P-158).

    A file has its name, its type, its size and the checksum of its content, which is
    kept beside the database under that checksum and never in it (P-161); a link has
    its address. It is on one record or more, through its attachments.
    """

    __tablename__ = "reference_files"
    __table_args__ = (
        CheckConstraint("(url IS NULL) <> (sha256 IS NULL)", name="reference_files_file_or_link"),
        CheckConstraint(
            "(sha256 IS NULL) = (file_name IS NULL) AND (sha256 IS NULL) = (size_bytes IS NULL)"
            " AND (sha256 IS NULL) = (media_type IS NULL)",
            name="reference_files_whole_file",
        ),
    )

    hid: Mapped[str] = _hid()
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    url: Mapped[str | None] = mapped_column(String(2000), default=None)
    file_name: Mapped[str | None] = mapped_column(String(255), default=None)
    media_type: Mapped[str | None] = mapped_column(String(100), default=None)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, default=None)
    sha256: Mapped[str | None] = mapped_column(String(64), default=None, index=True)

    attachments: Mapped[list[ReferenceAttachment]] = relationship(
        back_populates="reference", cascade="all, delete-orphan"
    )


# The records a reference may be on, each a column of an attachment (P-158).
ATTACHABLE = (
    "catalog_entry_hid",
    "region_hid",
    "site_hid",
    "location_hid",
    "circuit_hid",
    "item_hid",
)


class ReferenceAttachment(Bookkeeping, Base):
    """A reference on one record: a catalog entry, a place, a circuit or an item."""

    __tablename__ = "reference_attachments"
    __table_args__ = (
        CheckConstraint(
            " + ".join(f"(CASE WHEN {column} IS NULL THEN 0 ELSE 1 END)" for column in ATTACHABLE)
            + " = 1",
            name="reference_attachments_one_record",
        ),
        *(
            UniqueConstraint(
                "reference_file_hid", column, name=f"reference_attachments_{column}_once"
            )
            for column in ATTACHABLE
        ),
    )

    hid: Mapped[str] = _hid()
    reference_file_hid: Mapped[str] = mapped_column(ForeignKey("reference_files.hid"), index=True)
    catalog_entry_hid: Mapped[str | None] = mapped_column(
        ForeignKey("catalog_entries.hid"), default=None, index=True
    )
    region_hid: Mapped[str | None] = mapped_column(
        ForeignKey("regions.hid"), default=None, index=True
    )
    site_hid: Mapped[str | None] = mapped_column(ForeignKey("sites.hid"), default=None, index=True)
    location_hid: Mapped[str | None] = mapped_column(
        ForeignKey("locations.hid"), default=None, index=True
    )
    circuit_hid: Mapped[str | None] = mapped_column(
        ForeignKey("circuits.hid"), default=None, index=True
    )
    item_hid: Mapped[str | None] = mapped_column(ForeignKey("items.hid"), default=None, index=True)

    reference: Mapped[ReferenceFile] = relationship(back_populates="attachments")


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


class Country(Bookkeeping, Base):
    """A country an address may be in: its ISO 3166-1 code and its name (P-318)."""

    __tablename__ = "countries"
    __table_args__ = (
        UniqueConstraint("code", name="countries_code"),
        UniqueConstraint("name_key", name="countries_name"),
    )

    hid: Mapped[str] = _hid()
    code: Mapped[str] = mapped_column(String(2))
    name: Mapped[str] = mapped_column(String(100))
    name_key: Mapped[str] = mapped_column(String(100))


class State(Bookkeeping, Base):
    """A subdivision of a country, as ISO 3166-2 has it: the part of its code after the
    hyphen, its name and its country (P-318)."""

    __tablename__ = "states"
    __table_args__ = (
        UniqueConstraint("country", "code", name="states_code"),
        UniqueConstraint("country", "name_key", name="states_name"),
    )

    hid: Mapped[str] = _hid()
    country: Mapped[str] = mapped_column(String(2), index=True)
    code: Mapped[str] = mapped_column(String(3))
    name: Mapped[str] = mapped_column(String(100))
    name_key: Mapped[str] = mapped_column(String(100))


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
    # How far a preview in the background has got (P-325).
    rows_previewed: Mapped[int] = mapped_column(Integer, default=0)
    # How far an apply in the background has got, and what it did.
    rows_done: Mapped[int] = mapped_column(Integer, default=0)
    applied: Mapped[int] = mapped_column(Integer, default=0)
    stale: Mapped[int] = mapped_column(Integer, default=0)
    skip_rejected: Mapped[bool | None] = mapped_column(Boolean, default=None)
    # An import of items that was read from an external system, and whether it is
    # everything that system reports (P-248).
    system_hid: Mapped[str | None] = mapped_column(
        ForeignKey("external_systems.hid", name="fk_import_jobs_system_hid"), default=None
    )
    complete: Mapped[bool | None] = mapped_column(Boolean, default=None)
    not_reported: Mapped[int] = mapped_column(Integer, default=0)
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
    # What the apply did with the row, and why where it did not apply it. Blank until then.
    applied_outcome: Mapped[str | None] = mapped_column(String(10), default=None)
    applied_reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class RenewalAlertView(Bookkeeping, Base):
    """What a person last saw of the renewal alert: the contracts on each of its lists."""

    __tablename__ = "renewal_alert_views"
    __table_args__ = (UniqueConstraint("user_hid", name="renewal_alert_views_user"),)

    hid: Mapped[str] = _hid()
    user_hid: Mapped[str] = mapped_column(ForeignKey("users.hid"))
    seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=clock.now)
    as_of: Mapped[date] = mapped_column(Date)
    lapsed: Mapped[list[str]] = mapped_column(JSON, default=list)
    renewal_pending: Mapped[list[str]] = mapped_column(JSON, default=list)
    ending: Mapped[list[str]] = mapped_column(JSON, default=list)


class KeptAnswer(Base):
    """A long report worked out ahead, for the view its page opens with (P-275).

    One row to a report. It is good for the request, the newest audit event of a change
    of the inventory or its settings, the day in the application's time zone and the
    version of `hirdir` that it names, and is given for no other: `hirdir.io.kept`
    writes it and reads it. It is no record, and what it holds is worked out again
    from the records.
    """

    __tablename__ = "kept_answers"

    report: Mapped[str] = mapped_column(String(40), primary_key=True)
    request: Mapped[str] = mapped_column(Text)
    newest_event_hid: Mapped[str | None] = mapped_column(String(36), default=None)
    day: Mapped[date] = mapped_column(Date)
    version: Mapped[str] = mapped_column(String(40))
    answer: Mapped[str] = mapped_column(Text)
    kept_at: Mapped[datetime] = mapped_column(UTCDateTime, default=clock.now)


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
