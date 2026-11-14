"""The shapes of the inventory's requests and responses: the catalog, items and lists.

In a change, a field that is left out is left alone, and a field sent as null is
cleared, which for a field that inherits means it inherits again.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import Field, PlainSerializer, WithJsonSchema

from hirdir.api.schemas import Model
from hirdir.domain.inheritance import Source


def _plain(value: Decimal) -> str:
    """Write a decimal without an exponent and without zeros it does not need."""
    return format(value.normalize(), "f")


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


Money = Annotated[
    Decimal,
    Field(ge=0, max_digits=15, decimal_places=2),
    PlainSerializer(_money, return_type=str, when_used="json"),
    WithJsonSchema(
        {"type": "string", "pattern": r"^\d{1,13}(\.\d{1,2})?$", "examples": ["18000.00"]}
    ),
]
Weight = Annotated[
    Decimal,
    Field(ge=0, max_digits=15, decimal_places=2),
    PlainSerializer(_plain, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": r"^\d{1,13}(\.\d{1,2})?$", "examples": ["1.5"]}),
]
Percent = Annotated[
    Decimal,
    Field(ge=0, le=100, max_digits=5, decimal_places=2),
    PlainSerializer(_plain, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": r"^\d{1,3}(\.\d{1,2})?$", "examples": ["30"]}),
]

# A sum over many items may be larger than any one amount.
MoneySum = Annotated[
    Decimal,
    Field(ge=0, max_digits=60, decimal_places=2),
    PlainSerializer(_money, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": r"^\d+\.\d{2}$", "examples": ["54000.00"]}),
]
WeightSum = Annotated[
    Decimal,
    Field(ge=0, max_digits=60, decimal_places=2),
    PlainSerializer(_plain, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": r"^\d+(\.\d{1,2})?$", "examples": ["2.8"]}),
]

Name = Annotated[str, Field(max_length=200)]
ShortText = Annotated[str, Field(max_length=100)]
HostName = Annotated[str, Field(max_length=255)]
LongText = Annotated[str, Field(max_length=10_000)]
Hid = Annotated[str, Field(max_length=36)]
RecordStatus = Literal["draft", "active", "retired"]


class RowVersion(Model):
    """The version a record was read at, for an action that takes nothing else."""

    row_version: int


class ListQuery(Model):
    """What a list route takes, as a body, for a filter too large for a URL."""

    filter: dict[str, Any] | None = Field(
        default=None, description="A filter tree. See contract/filter.schema.json."
    )
    sort: list[str] = Field(default=[], description="Field names, `-` in front for descending.")
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0, le=10_000_000)
    include_archived: bool = False
    include_drafts: bool = False
    fields: list[ShortText] = Field(
        default=[],
        max_length=200,
        description="Only these fields of each record. `hid` and `row_version` always come.",
    )


class EffectiveValue(Model):
    """A value in force, and where it came from.

    A decimal and a date are text, and a truth value is true or false.
    """

    value: str | bool | None
    source: Source
    source_hid: str | None


class EffectiveReference(Model):
    """A record in force, and where it came from."""

    value: str | None = Field(description="The HID of the record.")
    label: str | None = Field(description="What people call the record.")
    source: Source
    source_hid: str | None


# --- vendors -------------------------------------------------------------------------


class VendorRef(Model):
    """A vendor, as named on another record."""

    hid: str
    name: str


class VendorOut(Model):
    """A manufacturer, a support provider, or both."""

    hid: str
    name: str
    aliases: list[str]
    notes: str | None
    review_status: str
    row_version: int
    created_at: datetime
    updated_at: datetime


class VendorCreate(Model):
    """A new vendor."""

    name: Name = Field(min_length=1)
    aliases: list[Name] = Field(default=[], max_length=50)
    notes: LongText | None = None
    review_status: str = Field(default="reviewed", max_length=12)


class VendorPatch(Model):
    """Fields of a vendor to change, and the version they were read at."""

    row_version: int
    name: Name | None = None
    aliases: list[Name] | None = Field(default=None, max_length=50)
    notes: LongText | None = None
    review_status: str | None = Field(default=None, max_length=12)


# --- catalog entries -----------------------------------------------------------------


class CatalogEffective(Model):
    """The values in force of the fields a catalog entry inherits."""

    stack_discount_pct: EffectiveValue


class CatalogEntryOut(Model):
    """What is true of every item of one model."""

    hid: str
    vendor_hid: str
    vendor: VendorRef
    pid: str
    model_name: str | None
    kind: str
    type: str | None
    function: str | None
    description: str | None
    end_of_sale: date | None
    end_of_sw_support: date | None
    end_of_hw_support: date | None
    ldos: date | None
    est_value: Money | None
    support_weight: Weight | None
    annual_support_cost: Money | None
    stack_discount_pct: Percent | None
    successor_hid: str | None
    review_status: str
    record_status: RecordStatus
    tags: list[str]
    effective: CatalogEffective
    row_version: int
    created_at: datetime
    updated_at: datetime


class CatalogEntryCreate(Model):
    """A new catalog entry: one vendor and product ID."""

    vendor_hid: Hid
    pid: ShortText = Field(min_length=1)
    model_name: Name | None = None
    kind: str = Field(default="hardware", max_length=20)
    type: str | None = Field(default=None, max_length=40)
    function: str | None = Field(default=None, max_length=40)
    description: LongText | None = None
    end_of_sale: date | None = None
    end_of_sw_support: date | None = None
    end_of_hw_support: date | None = None
    ldos: date | None = None
    est_value: Money | None = None
    support_weight: Weight | None = None
    annual_support_cost: Money | None = None
    stack_discount_pct: Percent | None = None
    successor_hid: Hid | None = None
    review_status: str = Field(default="reviewed", max_length=12)
    record_status: Literal["draft", "active"] = "active"
    tags: list[ShortText] = Field(default=[], max_length=100)


class CatalogEntryPatch(Model):
    """Fields of a catalog entry to change, and the version they were read at."""

    row_version: int
    vendor_hid: Hid | None = None
    pid: ShortText | None = None
    model_name: Name | None = None
    kind: str | None = Field(default=None, max_length=20)
    type: str | None = Field(default=None, max_length=40)
    function: str | None = Field(default=None, max_length=40)
    description: LongText | None = None
    end_of_sale: date | None = None
    end_of_sw_support: date | None = None
    end_of_hw_support: date | None = None
    ldos: date | None = None
    est_value: Money | None = None
    support_weight: Weight | None = None
    annual_support_cost: Money | None = None
    stack_discount_pct: Percent | None = None
    successor_hid: Hid | None = None
    review_status: str | None = Field(default=None, max_length=12)
    record_status: Literal["draft", "active"] | None = None
    tags: list[ShortText] | None = Field(default=None, max_length=100)


# --- owners --------------------------------------------------------------------------


class OwnerRef(Model):
    """An owner, as named on another record."""

    hid: str
    label: str


class OwnerOut(Model):
    """Who answers for an item."""

    hid: str
    label: str
    organization: str | None
    is_external: bool
    exception_reason: str | None
    record_status: RecordStatus
    row_version: int
    created_at: datetime
    updated_at: datetime


class OwnerCreate(Model):
    """A new owner."""

    label: Name = Field(min_length=1)
    organization: Name | None = None
    is_external: bool = False
    exception_reason: LongText | None = None
    record_status: Literal["draft", "active"] = "active"


class OwnerPatch(Model):
    """Fields of an owner to change, and the version they were read at."""

    row_version: int
    label: Name | None = None
    organization: Name | None = None
    is_external: bool | None = None
    exception_reason: LongText | None = None
    record_status: Literal["draft", "active"] | None = None


# --- items ---------------------------------------------------------------------------


class CatalogRef(Model):
    """A catalog entry, as shown on an item."""

    hid: str
    vendor_hid: str
    vendor: str
    pid: str
    model_name: str | None
    kind: str
    type: str | None
    function: str | None


class HealthOut(Model):
    """How a record is doing, worked out as it is read, and why."""

    value: Literal["good", "degraded", "failed", "unknown"]
    reasons: list[str]


ObservedStatus = Literal["online", "degraded", "unreachable", "present"]


class ItemRef(Model):
    """An item, as named on another record."""

    hid: str
    name: str | None = Field(description="Its name, or its hostname when it has no name.")
    serial_number: str | None
    asset_tag: str | None
    pid: str | None


class DeviceGroupRef(Model):
    """A device group, as named on another record."""

    hid: str
    name: str
    type: str


class NetworkRef(Model):
    """A network, as named on an address."""

    hid: str
    label: str


class MembershipRef(Model):
    """A group an item is a current member of, and as what."""

    hid: str = Field(description="The membership.")
    group_hid: str
    name: str
    type: str
    role: str
    position: int | None
    joined_on: date


class ControllerRef(ItemRef):
    """A controller of an endpoint, with the cluster it is in."""

    cluster_hid: str | None
    cluster: str | None = Field(description="The name of its cluster, when it is in one.")


class AddressRef(Model):
    """An address, as listed on the item or the group that has it."""

    hid: str
    address: str
    family: Literal[4, 6]
    network_hid: str | None
    network: str | None = Field(description="The label of the network, if it is under one.")
    role: str
    is_primary: bool


class ReplacementRef(Model):
    """The other item of a replacement, and why and when it was made."""

    hid: str = Field(description="The replacement.")
    item_hid: str
    name: str | None
    serial_number: str | None
    reason: str
    reference: str | None
    replaced_on: date


class ItemEffective(Model):
    """The values in force of the fields an item inherits: the amounts and the dates
    from its catalog entry, and for a minor item the owner and the standing of the item
    it is in."""

    owner_hid: EffectiveReference
    lifecycle_state: EffectiveValue
    disposition: EffectiveValue
    expected_online: EffectiveValue
    est_value: EffectiveValue
    support_weight: EffectiveValue
    annual_support_cost: EffectiveValue
    end_of_sale: EffectiveValue
    end_of_sw_support: EffectiveValue
    end_of_hw_support: EffectiveValue
    ldos: EffectiveValue


class ItemOut(Model):
    """One tracked thing. A field that inherits holds the item's own value, and
    `effective` holds the value in force with its source."""

    hid: str
    catalog_entry_hid: str | None
    catalog: CatalogRef | None
    serial_number: str | None
    mac_address: str | None = Field(description="Twelve lower-case hex digits.")
    asset_tag: str | None
    name: str | None = Field(description="Blank shows the hostname.")
    hostname: str | None
    fqdn: str | None
    description: str | None
    comments: str | None
    quantity: int
    lifecycle_state: str | None
    disposition: str | None
    expected_online: bool | None
    state_reason: str | None
    state_changed_at: datetime | None
    condition: str | None = Field(description="The state of the hardware, as a person knows it.")
    observed_status: ObservedStatus | None = Field(
        description="What is seen of it: on the network, or `present`, by a person."
    )
    observed_at: datetime | None
    health: HealthOut
    owner_hid: str | None
    owner: OwnerRef | None
    parent_item_hid: str | None
    parent: ItemRef | None = Field(description="The item a minor item is in.")
    position: str | None = Field(description="Where in its parent a minor item is.")
    is_major: bool = Field(description="An item with no parent. Major items are counted.")
    depth: int = Field(description="0 for a major item, 1 for a minor item of it, and so on.")
    minor_items: int = Field(description="How many minor items are directly in this one.")
    procured_on: date | None
    delivered_on: date | None
    in_service_on: date | None
    warranty_start: date | None
    warranty_end: date | None
    est_value: Money | None
    support_weight: Weight | None
    annual_support_cost: Money | None
    end_of_sale: date | None
    end_of_sw_support: date | None
    end_of_hw_support: date | None
    ldos: date | None
    effective: ItemEffective
    groups: list[MembershipRef] = Field(description="Its current memberships of groups.")
    controllers: list[ControllerRef] = Field(
        description="For an endpoint of a controller domain: the controllers of that domain."
    )
    addresses: list[AddressRef] = Field(description="Its addresses, the primary one first.")
    replaces: ReplacementRef | None = Field(description="The item whose place this one took.")
    replaced_by: ReplacementRef | None = Field(description="The item that took its place.")
    tags: list[str]
    record_status: RecordStatus
    row_version: int
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None


class ItemCreate(Model):
    """A new item. Only what identifies it is needed: a serial number with a catalog
    entry, or an asset tag, a name or a hostname. Everything else may be left blank."""

    catalog_entry_hid: Hid | None = None
    serial_number: ShortText | None = None
    mac_address: str | None = Field(
        default=None, max_length=40, description="In any common notation."
    )
    asset_tag: ShortText | None = None
    name: Name | None = None
    hostname: HostName | None = None
    fqdn: HostName | None = None
    description: LongText | None = None
    comments: LongText | None = None
    quantity: int = Field(default=1, ge=1, le=1_000_000_000)
    lifecycle_state: str | None = Field(default=None, max_length=20)
    disposition: str | None = Field(
        default=None, max_length=12, description="Left out, the state's own on entry."
    )
    expected_online: bool | None = None
    state_reason: str | None = Field(default=None, max_length=40)
    condition: str | None = Field(
        default=None, max_length=40, description="A value of the item_condition list."
    )
    observed_status: ObservedStatus | None = None
    observed_at: datetime | None = Field(
        default=None, description="Left out, now. Given with observed_status only."
    )
    owner_hid: Hid | None = None
    parent_item_hid: Hid | None = Field(
        default=None, description="The item this one is in. Given, the item is a minor item."
    )
    position: ShortText | None = Field(
        default=None, description="Where in its parent: PS-A, Slot 3."
    )
    procured_on: date | None = None
    delivered_on: date | None = None
    in_service_on: date | None = None
    warranty_start: date | None = None
    warranty_end: date | None = None
    est_value: Money | None = None
    support_weight: Weight | None = None
    annual_support_cost: Money | None = None
    end_of_sale: date | None = None
    end_of_sw_support: date | None = None
    end_of_hw_support: date | None = None
    ldos: date | None = None
    record_status: Literal["draft", "active"] = "active"
    tags: list[ShortText] = Field(default=[], max_length=100)


class ItemPatch(Model):
    """Fields of an item to change, and the version they were read at.

    The lifecycle state is not among them: it is changed by a transition.
    """

    row_version: int
    catalog_entry_hid: Hid | None = None
    serial_number: ShortText | None = None
    mac_address: str | None = Field(default=None, max_length=40)
    asset_tag: ShortText | None = None
    name: Name | None = None
    hostname: HostName | None = None
    fqdn: HostName | None = None
    description: LongText | None = None
    comments: LongText | None = None
    quantity: int | None = Field(default=None, ge=1, le=1_000_000_000)
    disposition: str | None = Field(default=None, max_length=12)
    expected_online: bool | None = None
    condition: str | None = Field(default=None, max_length=40)
    observed_status: ObservedStatus | None = Field(
        default=None, description="Null clears it, and the moment with it."
    )
    observed_at: datetime | None = None
    owner_hid: Hid | None = None
    parent_item_hid: Hid | None = Field(
        default=None, description="Null takes a minor item out of its parent."
    )
    position: ShortText | None = None
    procured_on: date | None = None
    delivered_on: date | None = None
    in_service_on: date | None = None
    warranty_start: date | None = None
    warranty_end: date | None = None
    est_value: Money | None = None
    support_weight: Weight | None = None
    annual_support_cost: Money | None = None
    end_of_sale: date | None = None
    end_of_sw_support: date | None = None
    end_of_hw_support: date | None = None
    ldos: date | None = None
    record_status: Literal["draft", "active"] | None = None
    tags: list[ShortText] | None = Field(default=None, max_length=100)


class Transition(Model):
    """A move to another lifecycle state."""

    row_version: int
    to: str | None = Field(
        max_length=20,
        description=(
            "The state to move to. Null returns a minor item to the standing of the item it is in."
        ),
    )
    reason: str | None = Field(
        default=None, max_length=40, description="A value of the state_reason list."
    )
    disposition: str | None = Field(
        default=None, max_length=12, description="Left out, kept or set as the new state has it."
    )
    expected_online: bool | None = Field(
        default=None, description="Left out, set as the new state has it."
    )
    force: bool = Field(
        default=False, description="A move the rules do not list. Admin only, with a reason."
    )


class Replace(Model):
    """The replacement of an item: what takes its place, why and when."""

    row_version: int = Field(description="The version of the item that leaves.")
    new_item_hid: Hid | None = Field(
        default=None, description="An item that exists and takes the place."
    )
    new_item: ItemCreate | None = Field(
        default=None, description="Or the fields of a new item, created by this request."
    )
    reason: str = Field(max_length=40, description="A value of the replacement_reason list.")
    reference: Name | None = Field(
        default=None, description="An RMA, service request or ticket number."
    )
    replaced_on: date | None = Field(default=None, description="Left out, today.")


class ReplacementOut(Model):
    """Two items linked by a replacement."""

    hid: str
    old_item_hid: str
    old_item: ItemOut
    new_item_hid: str
    new_item: ItemOut
    reason: str
    reference: str | None
    replaced_on: date
    row_version: int
    created_at: datetime
    created_by: str | None


# --- device groups -------------------------------------------------------------------

GroupType = Literal["stack", "cluster", "controller_domain", "custom"]


class MemberAdd(Model):
    """An item to make a member of a group."""

    item_hid: Hid
    role: str | None = Field(
        default=None,
        max_length=20,
        description=(
            "stack: member, or master for the one that is meant to be master. cluster: "
            "active, standby, member. controller domain: controller, endpoint. Left out, "
            "member, or endpoint in a controller domain."
        ),
    )
    position: int | None = Field(default=None, ge=0, le=10_000)
    joined_on: date | None = Field(default=None, description="Left out, today.")


class MembersAdd(Model):
    """Items to make members of a group together. The group is checked once all are in."""

    members: list[MemberAdd] = Field(min_length=1, max_length=1000)


class MemberPatch(Model):
    """Fields of a membership to change, and the version they were read at."""

    row_version: int
    role: str | None = Field(default=None, max_length=20)
    position: int | None = Field(default=None, ge=0, le=10_000)
    joined_on: date | None = None
    left_on: date | None = Field(default=None, description="Given, the membership ends.")


class MemberOut(Model):
    """One item's time in one group."""

    hid: str
    group_hid: str
    item_hid: str
    item: ItemRef
    role: str
    position: int | None
    joined_on: date
    left_on: date | None = Field(description="Blank for a current member.")
    row_version: int
    created_at: datetime
    updated_at: datetime


ManagedAs = Literal["one", "members", "members_and_cluster"]


class DeviceGroupOut(Model):
    """A stack, a cluster, a controller domain or another labelled set of items."""

    hid: str
    type: GroupType
    name: str
    hostname: str | None
    fqdn: str | None
    parent_group_hid: str | None
    parent: DeviceGroupRef | None
    groups: list[DeviceGroupRef] = Field(description="The groups nested directly in this one.")
    owner_hid: str | None
    owner: OwnerRef | None
    members_disagree: list[str] = Field(
        description="The fields of the group that a current member contradicts."
    )
    managed_as: ManagedAs | None = Field(
        description="A cluster: one managed node, one for each member, or those and its own."
    )
    expected_members: int | None
    observed_status: ObservedStatus | None
    observed_at: datetime | None
    health: HealthOut | None = Field(description="Of a stack and a cluster; otherwise null.")
    serial_number: str | None = Field(
        description=(
            "For a stack: the serial number of the master that is seen, or else of the one "
            "intended, read as it is asked for."
        )
    )
    serial_source: Literal["observed", "intended"] | None = Field(
        description="Which of the two masters the serial number is read from."
    )
    master: ItemRef | None = Field(description="The master that is intended, if one is marked.")
    observed_master_hid: str | None
    observed_master: ItemRef | None = Field(description="The member that is seen to be master.")
    master_observed_at: datetime | None
    master_as_intended: bool | None = Field(
        description="False when the master that is seen is not the one intended. Not a fault."
    )
    member_count: int = Field(description="How many current members it has.")
    addresses: list[AddressRef]
    tags: list[str]
    record_status: RecordStatus
    row_version: int
    created_at: datetime
    updated_at: datetime


class DeviceGroupCreate(Model):
    """A new device group, with its first members if they are known."""

    type: GroupType
    name: Name = Field(min_length=1)
    hostname: HostName | None = None
    fqdn: HostName | None = None
    parent_group_hid: Hid | None = None
    owner_hid: Hid | None = None
    managed_as: ManagedAs | None = Field(default=None, description="A cluster only. Left out, one.")
    expected_members: int | None = Field(default=None, ge=1, le=10_000)
    observed_status: ObservedStatus | None = None
    observed_at: datetime | None = None
    observed_master_hid: Hid | None = Field(
        default=None, description="A stack only: one of the members given here."
    )
    master_observed_at: datetime | None = None
    record_status: Literal["draft", "active"] = "active"
    tags: list[ShortText] = Field(default=[], max_length=100)
    members: list[MemberAdd] = Field(default=[], max_length=1000)


class DeviceGroupPatch(Model):
    """Fields of a device group to change, and the version they were read at."""

    row_version: int
    type: GroupType | None = None
    name: Name | None = None
    hostname: HostName | None = None
    fqdn: HostName | None = None
    parent_group_hid: Hid | None = None
    owner_hid: Hid | None = None
    managed_as: ManagedAs | None = None
    expected_members: int | None = Field(default=None, ge=1, le=10_000)
    observed_status: ObservedStatus | None = None
    observed_at: datetime | None = None
    observed_master_hid: Hid | None = Field(
        default=None, description="A current member of the stack. Null clears it."
    )
    master_observed_at: datetime | None = None
    record_status: Literal["draft", "active"] | None = None
    tags: list[ShortText] | None = Field(default=None, max_length=100)


# --- networks and addresses ----------------------------------------------------------


class NetworkOut(Model):
    """A label for an address space, and how many addresses are under it."""

    hid: str
    label: str
    kind: Literal["network", "vrf", "other"]
    uses: int
    row_version: int
    created_at: datetime
    updated_at: datetime


class NetworkCreate(Model):
    """A new network label."""

    label: ShortText = Field(min_length=1)
    kind: Literal["network", "vrf", "other"] = "network"


class NetworkPatch(Model):
    """Fields of a network to change, and the version they were read at."""

    row_version: int
    label: ShortText | None = None
    kind: Literal["network", "vrf", "other"] | None = None


AddressRole = Literal["management", "loopback", "secondary", "virtual"]
AddressText = Annotated[str, Field(min_length=1, max_length=45)]


class AddressOut(Model):
    """One address of an item or of a device group."""

    hid: str
    item_hid: str | None
    item: ItemRef | None
    group_hid: str | None
    group: DeviceGroupRef | None
    address: str = Field(description="In canonical form, with no prefix length.")
    family: Literal[4, 6]
    network_hid: str | None
    network: NetworkRef | None
    role: AddressRole
    is_primary: bool
    row_version: int
    created_at: datetime
    updated_at: datetime


class AddressCreate(Model):
    """A new address, of an item or of a group: exactly one of the two."""

    item_hid: Hid | None = None
    group_hid: Hid | None = None
    address: AddressText = Field(description="IPv4 or IPv6, in any common notation.")
    network_hid: Hid | None = Field(default=None, description="Blank is the unlabelled space.")
    role: AddressRole = "management"
    is_primary: bool = Field(
        default=False,
        description="The primary management address of the record, of this address's family.",
    )


class AddressPatch(Model):
    """Fields of an address to change, and the version they were read at."""

    row_version: int
    address: AddressText | None = None
    network_hid: Hid | None = None
    role: AddressRole | None = None
    is_primary: bool | None = None


# --- reports -------------------------------------------------------------------------

SummaryBy = Literal[
    "vendor",
    "kind",
    "type",
    "function",
    "owner",
    "lifecycle_state",
    "disposition",
    "condition",
    "health",
    "tag",
]
ManagementBy = Literal["vendor", "kind", "type", "function", "owner", "tag"]


class HealthCount(Model):
    """The components of each health."""

    good: int
    degraded: int
    failed: int
    unknown: int


class Counted(Model):
    """The items and the components that share one value: a kind, or a condition."""

    key: str | None
    label: str | None
    items: int
    component_count: int = Field(
        description=(
            "The components among them. By kind, the major items in hand of that kind, "
            "also where the headline count leaves the kind out."
        )
    )


class Measures(Model):
    """What the summary counts of a set of items. It holds no money."""

    items: int = Field(description="Every item of the set, major and minor.")
    component_count: int
    managed_node_count: int
    support_weight: WeightSum
    by_health: HealthCount


class SummaryTotals(Measures):
    """The measures of the whole view, and its items by condition and by kind."""

    by_condition: list[Counted]
    by_kind: list[Counted]


class SummaryRow(Measures):
    """The measures of the items that share one value of what the summary is by."""

    key: str | None = Field(description="The value, or the HID of the record. Null for none.")
    label: str | None = Field(description="What people call it.")


class SummaryOut(Model):
    """A summary of a view of the items, for the people who run the network."""

    by: SummaryBy | None
    totals: SummaryTotals
    rows: list[SummaryRow]


class ManagementMeasures(Model):
    """What the management report counts of a set of items."""

    items: int = Field(description="Every item of the set, major and minor.")
    component_count: int
    est_value: MoneySum
    annual_support_cost: MoneySum


class ManagementRow(ManagementMeasures):
    """The value and the cost of the items that share one value."""

    key: str | None
    label: str | None


class ManagementOut(Model):
    """The value and the cost of a view of the items, for the people who pay for it."""

    by: ManagementBy | None
    totals: ManagementMeasures
    rows: list[ManagementRow]


class AddressHolder(Model):
    """An item or a group that holds an address."""

    address_hid: str
    item_hid: str | None
    group_hid: str | None
    name: str | None
    role: str
    is_primary: bool


class DuplicateOut(Model):
    """An address that is held more than once under one network."""

    address: str
    network_hid: str | None
    network: str | None = Field(description="Null for the unlabelled address space.")
    count: int
    holders: list[AddressHolder]


# --- labels and lists ----------------------------------------------------------------


class TagOut(Model):
    """A tag, and how many records carry it."""

    hid: str
    label: str
    colour: str | None
    description: str | None
    uses: int
    row_version: int
    created_at: datetime
    updated_at: datetime


class TagCreate(Model):
    """A new tag."""

    label: ShortText = Field(min_length=1)
    colour: str | None = Field(default=None, max_length=20, description="In the form #1f6feb.")
    description: LongText | None = None


class TagPatch(Model):
    """Fields of a tag to change, and the version they were read at."""

    row_version: int
    label: ShortText | None = None
    colour: str | None = Field(default=None, max_length=20)
    description: LongText | None = None


class ChoiceOut(Model):
    """One value of one editable list."""

    hid: str
    list: str
    value: str
    label: str
    sort: int
    active: bool
    row_version: int
    created_at: datetime
    updated_at: datetime


class ChoiceCreate(Model):
    """A new value for a list."""

    list: str
    value: str = Field(min_length=1, max_length=40)
    label: ShortText = ""
    sort: int = Field(default=0, ge=-1_000_000, le=1_000_000)
    active: bool = True


class ChoicePatch(Model):
    """Fields of a choice to change, and the version they were read at."""

    row_version: int
    label: ShortText | None = None
    sort: int | None = Field(default=None, ge=-1_000_000, le=1_000_000)
    active: bool | None = None


class SettingOut(Model):
    """A setting: the value in force, its default, and what it means."""

    key: str
    value: Any
    default: Any
    is_default: bool
    meaning: str
    row_version: int = Field(description="0 for a setting that has never been changed.")
    updated_at: datetime | None
    updated_by: str | None


class SettingSet(Model):
    """A new value for a setting. Null returns it to its default."""

    row_version: int
    value: Any = None


class LifecycleRuleOut(Model):
    """What one lifecycle state allows, and where an item may move from it."""

    hid: str
    state: str
    sort: int
    dispositions: list[str] = Field(description="The dispositions an item in this state may have.")
    keeps_disposition: bool = Field(
        description="An item keeps the disposition it came with, which is then allowed too."
    )
    may_be_online: list[str] = Field(description="Dispositions that may be expected online.")
    must_be_online: list[str] = Field(description="Dispositions that are always expected online.")
    entry_disposition: str | None = Field(
        description="Set on entry when the item's own is not allowed."
    )
    entry_online: bool | None = Field(
        description="The intent set on entry, where it may be either."
    )
    next_states: list[str] = Field(description="The states an item may move to from this one.")
    row_version: int
    updated_at: datetime


class LifecycleRulePatch(Model):
    """Fields of a lifecycle rule to change, and the version they were read at."""

    row_version: int
    dispositions: list[str] | None = Field(default=None, max_length=10)
    keeps_disposition: bool | None = None
    may_be_online: list[str] | None = Field(default=None, max_length=10)
    must_be_online: list[str] | None = Field(default=None, max_length=10)
    entry_disposition: str | None = Field(default=None, max_length=12)
    entry_online: bool | None = None
    next_states: list[str] | None = Field(default=None, max_length=10)


# --- files and bulk edits ------------------------------------------------------------

EntityName = Literal[
    "tags",
    "vendors",
    "catalog_entries",
    "owners",
    "networks",
    "items",
    "addresses",
    "device_groups",
    "device_group_members",
]
Outcome = Literal["create", "update", "unchanged", "rejected"]


class ImportEnvelope(Model):
    """A JSON file: the records of one entity, as an export writes them."""

    schema_: Literal["hirdir/1"] = Field(alias="schema")
    entity: EntityName
    mode: Literal["create", "upsert"] = "upsert"
    records: list[dict[str, Any]]


class ImportJobOut(Model):
    """A stored preview of an import or a bulk edit, and what became of it."""

    hid: str
    source: Literal["file", "bulk"]
    entity: str
    mode: Literal["create", "upsert", "update"]
    file_name: str | None
    file_sha256: str | None
    status: Literal["previewed", "applied", "failed"]
    row_count: int
    created: int = Field(description="Rows that create a record.")
    updated: int = Field(description="Rows that change a record.")
    unchanged: int = Field(description="Rows that find their record as the row has it.")
    rejected: int = Field(description="Rows that cannot be applied.")
    skip_rejected: bool | None = Field(description="Whether it was applied without them.")
    failure: str | None = Field(description="Why a failed job was not applied.")
    applied_at: datetime | None
    applied_by: str | None
    applied_by_name: str | None
    created_at: datetime
    created_by: str | None
    created_by_name: str | None


class RowChange(Model):
    """One field a row changes, in the columns of the file."""

    field: str
    old: Any
    new: Any


class RowReason(Model):
    """Why a row is rejected."""

    field: str
    message: str


class ImportRowOut(Model):
    """One row of a preview: what it would do, or why it is rejected."""

    row: int = Field(description="Its number in the file, from 1.")
    outcome: Outcome
    record_hid: str | None = Field(
        description="The record the row matched, or the one it created once applied."
    )
    key: str = Field(description="How the row names its record.")
    changes: list[RowChange]
    reasons: list[RowReason]
    notes: list[str] = Field(description="What else the row brings about.")


class ImportPreview(Model):
    """A preview: the job with its counts, and the first of its rows."""

    job: ImportJobOut
    rows: list[ImportRowOut] = Field(
        description="The first hundred rows. `GET /imports/{hid}/rows` pages through all."
    )


class ExportRequest(Model):
    """What to export. The filter and the sort are those of a list."""

    entity: EntityName
    format: Literal["csv", "json"] = "csv"
    filter: dict[str, Any] | str | None = Field(
        default=None, description="A filter tree, or the short form."
    )
    sort: list[str] = Field(default=[], max_length=50)
    columns: list[ShortText] | None = Field(
        default=None,
        max_length=200,
        description="Left out, the columns that can be set. `hid` is always first.",
    )
    hids: list[Hid] | None = Field(
        default=None,
        max_length=10_000,
        description="Only these records, of those the filter keeps.",
    )
    include_sources: bool = Field(
        default=False, description="Add a `_source` column for each field that inherits."
    )
    own_values: bool = Field(
        default=False,
        description="Stored values and not the ones in force: the form to import back.",
    )
    include_archived: bool = False
    include_drafts: bool = False


class BulkUpdate(Model):
    """One change to many items. The rows are named by a filter, by HIDs, or as all."""

    filter: dict[str, Any] | str | None = Field(
        default=None, description="A filter tree, or the short form."
    )
    hids: list[Hid] | None = Field(default=None, max_length=10_000)
    all_rows: bool = Field(default=False, description="Every item, when no filter is given.")
    include_archived: bool = False
    include_drafts: bool = False
    set: dict[str, Any] = Field(
        default={},
        description="Columns of an import and their new values. Null clears a field.",
    )
    add_tags: list[ShortText] = Field(default=[], max_length=100)
    remove_tags: list[ShortText] = Field(default=[], max_length=100)
