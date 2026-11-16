"""The shapes of the requests and responses of circuits, their parts and circuit groups
(P-145 to P-154).

In a change, a field that is left out is left alone, and a field sent as null is
cleared, which for a rate means the full rate of the port again.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, PlainSerializer, WithJsonSchema

from hirdir.api.records import (
    CarrierContacts,
    CircuitContactOut,
    EffectiveValue,
    EffectiveWeight,
    Hid,
    LongText,
    Name,
    OwnerRef,
    RecordStatus,
    ShortText,
    SiteContacts,
    VendorRef,
    Weight,
)
from hirdir.api.schemas import Model
from hirdir.domain import settings


def _two_places(value: Decimal) -> str:
    return f"{value:.2f}"


# A speed in Mbps, more than zero, with two places: "1000.00".
Mbps = Annotated[
    Decimal,
    Field(gt=0, max_digits=15, decimal_places=2),
    PlainSerializer(_two_places, return_type=str, when_used="json"),
    WithJsonSchema(
        {"type": "string", "pattern": r"^\d{1,13}(\.\d{1,2})?$", "examples": ["1000.00"]}
    ),
]
# Money a month that may be below zero, for a credit.
SignedMoney = Annotated[
    Decimal,
    Field(max_digits=15, decimal_places=2),
    PlainSerializer(_two_places, return_type=str, when_used="json"),
    WithJsonSchema(
        {"type": "string", "pattern": r"^-?\d{1,13}(\.\d{1,2})?$", "examples": ["-50.00"]}
    ),
]
# A sum of such amounts, which may be larger than any one of them.
SignedMoneySum = Annotated[
    Decimal,
    Field(max_digits=60, decimal_places=2),
    PlainSerializer(_two_places, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": r"^-?\d+\.\d{2}$", "examples": ["1000.00"]}),
]
Side = Literal["a", "z"]
ChoiceValue = Annotated[str, Field(max_length=40)]
MOST_AT_ONCE = settings.MOST_ITEMS_PER_REQUEST


# --- the parts of a circuit ----------------------------------------------------------


class CircuitSide(Model):
    """A side of a circuit at a location: the location's path, its site and its region,
    read when it is asked for."""

    location_hid: str
    name: str = Field(description="The name of the location.")
    path: str = Field(description="The path of the location, from the top region down.")
    site_hid: str
    site_path: str = Field(description="The path of its site.")
    region_hid: str
    record_status: RecordStatus = Field(description="That of the location.")


class CircuitCarrierOut(Model):
    """A carrier of a circuit beside its primary one, in its part, with its number."""

    hid: str
    circuit_hid: str
    vendor_hid: str
    vendor: str = Field(description="The name of the vendor.")
    role: str = Field(description="Its part: a value of the carrier_role list.")
    circuit_number: str | None = Field(description="The number this carrier gives the circuit.")
    priority: int = Field(description="The order in which they are listed, from 1.")
    notes: str | None
    row_version: int
    created_at: datetime
    updated_at: datetime


class CircuitCarrierAdd(Model):
    """A carrier to name for a circuit. Left out, its priority puts it last."""

    vendor_hid: Hid
    role: ChoiceValue
    circuit_number: ShortText | None = None
    priority: int | None = Field(default=None, ge=1, le=1000)
    notes: LongText | None = None


class CircuitCarrierPatch(Model):
    """Fields of a carrier of a circuit to change, and the version they were read at."""

    row_version: int
    vendor_hid: Hid | None = None
    role: ChoiceValue | None = None
    circuit_number: ShortText | None = None
    priority: int | None = Field(default=None, ge=1, le=1000)
    notes: LongText | None = None


class CircuitCostOut(Model):
    """One line of what a carrier bills for a circuit each month."""

    hid: str
    circuit_hid: str
    description: str
    monthly_cost: SignedMoney = Field(description="Below zero for a credit.")
    vendor_hid: str | None = Field(
        description="The carrier that bills the line; blank is the circuit's primary carrier."
    )
    vendor: str | None = Field(description="The name of the vendor the line names, if any.")
    starts_on: date | None
    ends_on: date | None
    in_date: bool = Field(description="It is billed today.")
    notes: str | None
    row_version: int
    created_at: datetime
    updated_at: datetime


class CircuitCostAdd(Model):
    """A new cost line of a circuit."""

    description: Name = Field(min_length=1)
    monthly_cost: SignedMoney
    vendor_hid: Hid | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    notes: LongText | None = None


class CircuitCostPatch(Model):
    """Fields of a cost line to change, and the version they were read at."""

    row_version: int
    description: Name | None = None
    monthly_cost: SignedMoney | None = None
    vendor_hid: Hid | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    notes: LongText | None = None


class CircuitDeviceOut(Model):
    """An item or a device group that a circuit connects, on one of its sides."""

    hid: str
    circuit_hid: str
    side: Side
    item_hid: str | None
    group_hid: str | None
    name: str = Field(description="What the device is called: an item's name, a group's name.")
    record_status: RecordStatus = Field(description="That of the device; a retired one says so.")
    notes: str | None
    row_version: int
    created_at: datetime
    updated_at: datetime


class CircuitDeviceAdd(Model):
    """A device to connect: one item or one device group, on a side."""

    item_hid: Hid | None = None
    group_hid: Hid | None = None
    side: Side
    notes: LongText | None = None


class CircuitDevicesAdd(Model):
    """Devices to connect to a circuit, all together."""

    devices: list[CircuitDeviceAdd] = Field(min_length=1, max_length=MOST_AT_ONCE)


class CircuitDevicePatch(Model):
    """Fields of a device of a circuit to change, and the version they were read at."""

    row_version: int
    side: Side | None = None
    notes: LongText | None = None


class CircuitGroupRef(Model):
    """A circuit group, as a circuit lists it."""

    hid: str
    name: str
    record_status: RecordStatus


# --- circuits ------------------------------------------------------------------------


class CircuitEffective(Model):
    """The values a circuit has in force, each with where it came from."""

    support_weight: EffectiveWeight = Field(
        description="Its own, or `default_circuit_weight` with the source `setting`, raised "
        "to `minimum_circuit_weight` where it is below it, with `raised_from` (P-155)."
    )
    down_mbps: EffectiveValue = Field(
        description="The rate in force down: its own, or the full rate of the port, `port`."
    )
    up_mbps: EffectiveValue = Field(
        description="The rate in force up: its own, or the full rate of the port, `port`."
    )
    account_managers: CarrierContacts | None = Field(
        default=None,
        description="The carrier's account team in force (P-149): its own, or its primary "
        "carrier's, `vendor`. Null in a list unless `fields` asks for it.",
    )
    support_contacts: CarrierContacts | None = Field(
        default=None,
        description="The carrier's support desk in force (P-149), as `account_managers`.",
    )
    site_contacts: SiteContacts | None = Field(
        default=None,
        description="The site contacts of each side, its own or its location's with the "
        "level they came from (P-149). Null in a list unless `fields` asks for it.",
    )


class CircuitOut(Model):
    """A telecommunication circuit, with what is worked out when it is read.

    A list leaves `carriers`, `costs`, `devices` and `groups` out of each row, as null,
    unless `fields` names them; the record has them always.
    """

    hid: str
    name: str
    enterprise_circuit_id: str | None
    description: str | None
    notes: str | None
    circuit_type: str | None
    port_mbps: Mbps | None
    down_mbps: Mbps | None = Field(description="Its own rate down. Blank is the port's.")
    up_mbps: Mbps | None = Field(description="Its own rate up. Blank is the port's.")
    speed: str | None = Field(description="The speed written short: 1G / 200M / 20M.")
    a_location_hid: str | None
    a_note: str | None
    z_location_hid: str | None
    z_note: str | None
    a_side: CircuitSide | None = Field(description="Null for a side with no location.")
    z_side: CircuitSide | None = Field(description="Null for a side with no location.")
    cost_side: Side = Field(description="The side whose site its cost and weight count at.")
    cost_site_hid: str | None = Field(description="The site its cost and weight count at.")
    cost_site_path: str | None
    carrier_hid: str | None
    carrier: VendorRef | None = Field(description="The primary carrier.")
    carrier_circuit_number: str | None
    billing_account: str | None
    billing_contract: str | None
    installed_on: date | None
    activated_on: date | None
    disconnected_on: date | None
    production: bool
    support_weight: Weight | None
    owner_hid: str | None
    owner: OwnerRef | None
    owner_exception: bool = Field(description="Its owner is outside the operations team.")
    owner_exception_reason: str | None = Field(description="That owner's reason.")
    monthly_cost: SignedMoneySum = Field(
        description="The sum of its cost lines in date today while it is in service, and "
        "nothing on a day it is not; a draft is in service in a view of drafts, and when "
        "it is read by itself."
    )
    annual_cost: SignedMoneySum = Field(description="Twelve times the monthly cost.")
    in_service: bool = Field(
        description="It is in service today: active, or a draft in a view of drafts or read "
        "by itself, and not before its activation or after its disconnection."
    )
    carriers: list[CircuitCarrierOut] | None = Field(
        description="Its carriers beside the primary one, by priority."
    )
    costs: list[CircuitCostOut] | None = Field(description="Its cost lines, by description.")
    devices: list[CircuitDeviceOut] | None = Field(description="The devices it connects.")
    groups: list[CircuitGroupRef] | None = Field(description="The groups it is in, by name.")
    contacts: list[CircuitContactOut] | None = Field(
        default=None, description="The contacts it names of its own (P-149)."
    )
    effective: CircuitEffective
    tags: list[str]
    record_status: RecordStatus
    row_version: int
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None


class CircuitCreate(Model):
    """A new circuit. A side with no location has a note of where it ends, and at least
    one side is a location. `cost_side` left out is the setting's."""

    name: Name = Field(min_length=1)
    enterprise_circuit_id: ShortText | None = None
    description: LongText | None = None
    notes: LongText | None = None
    circuit_type: ChoiceValue | None = None
    port_mbps: Mbps | None = None
    down_mbps: Mbps | None = None
    up_mbps: Mbps | None = None
    a_location_hid: Hid | None = None
    a_note: Name | None = None
    z_location_hid: Hid | None = None
    z_note: Name | None = None
    cost_side: Side | None = None
    carrier_hid: Hid | None = None
    carrier_circuit_number: ShortText | None = None
    billing_account: ShortText | None = None
    billing_contract: Name | None = None
    installed_on: date | None = None
    activated_on: date | None = None
    disconnected_on: date | None = None
    production: bool = True
    support_weight: Weight | None = None
    owner_hid: Hid | None = None
    record_status: Literal["draft", "active"] = "active"
    tags: list[ShortText] = Field(default=[], max_length=100)


class CircuitPatch(Model):
    """Fields of a circuit to change, and the version they were read at."""

    row_version: int
    name: Name | None = None
    enterprise_circuit_id: ShortText | None = None
    description: LongText | None = None
    notes: LongText | None = None
    circuit_type: ChoiceValue | None = None
    port_mbps: Mbps | None = None
    down_mbps: Mbps | None = None
    up_mbps: Mbps | None = None
    a_location_hid: Hid | None = None
    a_note: Name | None = None
    z_location_hid: Hid | None = None
    z_note: Name | None = None
    cost_side: Side | None = None
    carrier_hid: Hid | None = None
    carrier_circuit_number: ShortText | None = None
    billing_account: ShortText | None = None
    billing_contract: Name | None = None
    installed_on: date | None = None
    activated_on: date | None = None
    disconnected_on: date | None = None
    production: bool | None = None
    support_weight: Weight | None = None
    owner_hid: Hid | None = None
    record_status: Literal["draft", "active"] | None = Field(
        default=None, description="Brings a retired circuit back."
    )
    tags: list[ShortText] | None = Field(default=None, max_length=100)


# --- circuit groups ------------------------------------------------------------------


class CircuitRef(Model):
    """A circuit, as a group lists it."""

    hid: str
    name: str
    enterprise_circuit_id: str | None
    circuit_type: str | None
    speed: str | None
    in_service: bool = Field(
        description="It is in service today: active, or a draft in a view of drafts or read "
        "by itself, and not before its activation or after its disconnection."
    )
    monthly_cost: SignedMoneySum = Field(
        description="The sum of its cost lines in date today while it is in service, and "
        "nothing on a day it is not; a draft is in service in a view of drafts, and when "
        "it is read by itself."
    )
    record_status: RecordStatus


class CircuitGroupOut(Model):
    """Circuits that may land at different sites, looked at and costed together."""

    hid: str
    name: str
    description: str | None
    notes: str | None
    owner_hid: str | None
    owner: OwnerRef | None
    circuits: int = Field(description="How many circuits it has.")
    in_service: int = Field(description="How many of them are in service today.")
    monthly_cost: SignedMoneySum = Field(
        description="What those in service cost a month today, each circuit once."
    )
    annual_cost: SignedMoneySum = Field(description="Twelve times the monthly cost.")
    tags: list[str]
    record_status: RecordStatus
    row_version: int
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None


class CircuitGroupCreate(Model):
    """A new circuit group."""

    name: Name = Field(min_length=1)
    description: LongText | None = None
    notes: LongText | None = None
    owner_hid: Hid | None = None
    record_status: Literal["draft", "active"] = "active"
    tags: list[ShortText] = Field(default=[], max_length=100)


class CircuitGroupPatch(Model):
    """Fields of a circuit group to change, and the version they were read at."""

    row_version: int
    name: Name | None = None
    description: LongText | None = None
    notes: LongText | None = None
    owner_hid: Hid | None = None
    record_status: Literal["draft", "active"] | None = None
    tags: list[ShortText] | None = Field(default=None, max_length=100)


class CircuitGroupMemberOut(Model):
    """One circuit in one group."""

    hid: str
    group_hid: str
    circuit_hid: str
    circuit: CircuitRef
    created_at: datetime


class CircuitGroupMembersAdd(Model):
    """Circuits to put into a group, all together, each once."""

    circuit_hids: list[Hid] = Field(min_length=1, max_length=MOST_AT_ONCE)
