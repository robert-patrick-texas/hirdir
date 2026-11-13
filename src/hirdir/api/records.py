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


class EffectiveValue(Model):
    """A value in force, and where it came from."""

    value: str | None
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
    row_version: int
    created_at: datetime
    updated_at: datetime


class VendorCreate(Model):
    """A new vendor."""

    name: Name = Field(min_length=1)
    aliases: list[Name] = Field(default=[], max_length=50)
    notes: LongText | None = None


class VendorPatch(Model):
    """Fields of a vendor to change, and the version they were read at."""

    row_version: int
    name: Name | None = None
    aliases: list[Name] | None = Field(default=None, max_length=50)
    notes: LongText | None = None


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


class ItemEffective(Model):
    """The values in force of the fields an item inherits from its catalog entry."""

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
    owner_hid: str | None
    owner: OwnerRef | None
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
    owner_hid: Hid | None = None
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
    owner_hid: Hid | None = None
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
    to: str = Field(max_length=20, description="The state to move to.")
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
