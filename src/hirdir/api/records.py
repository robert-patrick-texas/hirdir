"""The shapes of the inventory's requests and responses: the catalog, items and lists.

In a change, a field that is left out is left alone, and a field sent as null is
cleared, which for a field that inherits means it inherits again.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import Field, PlainSerializer, WithJsonSchema

from hirdir.api.schemas import Model
from hirdir.domain import purchases, removal, settings
from hirdir.domain.inheritance import Source
from hirdir.io import listing


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
# Whether the person behind an operator is a user, internal, or is not, external (P-172).
Scope = Literal["internal", "external"]
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
    limit: int = Field(default=listing.DEFAULT_LIMIT, ge=1, le=listing.MAX_LIMIT)
    offset: int = Field(default=0, ge=0, le=listing.MAX_OFFSET)
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


class EffectiveWeight(Model):
    """A support weight in force, where it came from, and what it was before it was
    raised to the minimum of its kind (P-155)."""

    value: str | None = Field(description="The weight in force, as text. Blank: none.")
    source: Source = Field(description="`setting` where it is the default of its kind.")
    source_hid: str | None
    raised_from: str | None = Field(
        description="The weight before it was raised to the minimum of its kind. Blank where "
        "it was not raised."
    )


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
    # The contacts of a carrier (P-149): defined below, with the contacts of circuits.
    contacts: list[VendorContactOut] = Field(
        description="The account team and the support desk it names, by role and then by "
        "priority. Each circuit of the carrier that names nobody of its own in a role has "
        "these."
    )
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


# --- links ---------------------------------------------------------------------------


class Link(Model):
    """An address to reach about a record, with the text to show for it."""

    url: str
    text: str = Field(description="Blank where the address itself is shown.")


class LinkIn(Model):
    """A link of a record: an address on the web, and the text to show for it. What each
    may be is checked as a rule, and a refusal names the link."""

    url: str = Field(
        description="Begins with https:// or http://, with no space, `<` or `>`; 2,000 at most.",
        examples=["https://www.example.com/datasheet.pdf"],
    )
    text: str | None = Field(
        default="",
        description="At most 200 characters, with no `<` or `>`. Blank, the address is shown.",
    )


LINKS_DESCRIPTION = "Up to 20, in order, changed whole: an empty list has none."


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
    do_not_renew: bool = Field(
        description=(
            "Its support is not to be renewed: gear whose cover came with its purchase and "
            "is not bought again. Every item of the model has it unless it says otherwise."
        )
    )
    review_status: str
    links: list[Link] = Field(description=LINKS_DESCRIPTION)
    record_status: RecordStatus
    tags: list[str]
    items: int = Field(
        description=(
            "How many items are of the model, as the item list counts them (P-180): major "
            "and minor, drafts, retired items and items in Archived left out."
        )
    )
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
    do_not_renew: bool = Field(
        default=False,
        description=(
            "Its support is not to be renewed: gear whose cover came with its purchase and "
            "is not bought again."
        ),
    )
    review_status: str = Field(default="reviewed", max_length=12)
    links: list[LinkIn] = Field(default=[], max_length=20, description=LINKS_DESCRIPTION)
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
    do_not_renew: bool | None = Field(default=None, description="Null is false.")
    review_status: str | None = Field(default=None, max_length=12)
    links: list[LinkIn] | None = Field(default=None, max_length=20, description=LINKS_DESCRIPTION)
    record_status: Literal["draft", "active"] | None = None
    tags: list[ShortText] | None = Field(default=None, max_length=100)


# --- geography -----------------------------------------------------------------------

Code = Annotated[str, Field(max_length=40)]
Level = Literal["region", "site", "location"]


def _degrees(value: Decimal) -> str:
    return f"{value:.6f}"


Latitude = Annotated[
    Decimal,
    Field(ge=-90, le=90, max_digits=8, decimal_places=6),
    PlainSerializer(_degrees, return_type=str, when_used="json"),
    WithJsonSchema(
        {"type": "string", "pattern": r"^-?\d{1,2}(\.\d{1,6})?$", "examples": ["41.878100"]}
    ),
]
Longitude = Annotated[
    Decimal,
    Field(ge=-180, le=180, max_digits=9, decimal_places=6),
    PlainSerializer(_degrees, return_type=str, when_used="json"),
    WithJsonSchema(
        {"type": "string", "pattern": r"^-?\d{1,3}(\.\d{1,6})?$", "examples": ["-87.629800"]}
    ),
]


class OperatorRef(Model):
    """An operator, as shown on what it is given to: the label, and who is behind it."""

    hid: str
    label: str
    colour: str | None
    contact_hid: str | None
    contact: str | None = Field(description="The name of the person behind the label.")
    is_open: bool = Field(description="Nobody is behind it: no contact, or one that is retired.")
    scope: Scope | None = Field(
        description="internal where its contact is a user's, external where not; none if nobody."
    )
    record_status: RecordStatus


class PlaceRef(Model):
    """A region, a site or a location, as named on another record."""

    hid: str
    name: str
    path: str = Field(description="The names from the top region down, joined with ' > '.")


class LocationRef(PlaceRef):
    """A location, as named on the item or the group that is there, with its site."""

    kind: str | None
    site_hid: str
    site: str = Field(description="The name of its site.")
    region_hid: str
    region: str = Field(description="The name of the region its site is in.")


# --- the support weight of a place (P-139, P-155) ---

PLACE_WEIGHT = (
    "The work that supporting the network there adds by itself, beside what its devices "
    "weigh: its own, blank unless given. It is not passed down to the places beneath."
)


class SiteEffective(Model):
    """What a site has in force of what it takes from the settings."""

    support_weight: EffectiveWeight = Field(
        description="Its own, or else the setting `default_site_weight`, raised to "
        "`minimum_site_weight` where it is below it."
    )


# --- end of the support weight of a place ---


class RegionOut(Model):
    """A part of the world that sites are in."""

    hid: str
    code: str | None
    name: str
    parent_region_hid: str | None
    parent: PlaceRef | None
    path: str
    ship_address1: str | None
    ship_address2: str | None
    ship_city: str | None
    ship_state: str | None
    ship_postal_code: str | None
    ship_country: str | None
    ship_instructions: str | None
    operator_hid: str | None
    operator: OperatorRef | None = Field(description="Its own operator.")
    support_weight: Weight | None = Field(description=PLACE_WEIGHT)
    links: list[Link] = Field(description=LINKS_DESCRIPTION)
    notes: str | None
    record_status: RecordStatus
    tags: list[str]
    regions: int = Field(description="How many regions are directly in it, retired ones aside.")
    sites: int = Field(description="How many sites are directly in it, retired ones aside.")
    row_version: int
    created_at: datetime
    updated_at: datetime


class RegionCreate(Model):
    """A new region."""

    name: Name = Field(min_length=1)
    code: Code | None = None
    parent_region_hid: Hid | None = Field(
        default=None, description="The region it is in. Left out, a region at the top."
    )
    ship_address1: Name | None = None
    ship_address2: Name | None = None
    ship_city: Name | None = None
    ship_state: Name | None = None
    ship_postal_code: Name | None = None
    ship_country: Name | None = None
    ship_instructions: LongText | None = None
    operator_hid: Hid | None = None
    support_weight: Weight | None = Field(default=None, description=PLACE_WEIGHT)
    links: list[LinkIn] = Field(default=[], max_length=20, description=LINKS_DESCRIPTION)
    notes: LongText | None = None
    record_status: Literal["draft", "active"] = "active"
    tags: list[ShortText] = Field(default=[], max_length=100)


class RegionPatch(Model):
    """Fields of a region to change, and the version they were read at."""

    row_version: int
    name: Name | None = None
    code: Code | None = None
    parent_region_hid: Hid | None = Field(
        default=None, description="Another region moves it, with everything in it."
    )
    ship_address1: Name | None = None
    ship_address2: Name | None = None
    ship_city: Name | None = None
    ship_state: Name | None = None
    ship_postal_code: Name | None = None
    ship_country: Name | None = None
    ship_instructions: LongText | None = None
    operator_hid: Hid | None = None
    support_weight: Weight | None = Field(default=None, description=PLACE_WEIGHT)
    links: list[LinkIn] | None = Field(default=None, max_length=20, description=LINKS_DESCRIPTION)
    notes: LongText | None = None
    record_status: Literal["draft", "active"] | None = None
    tags: list[ShortText] | None = Field(default=None, max_length=100)


MAP_URL = (
    "The address of a map at its coordinates: the setting `map_link` with them in it. "
    "Null where it has none, or the setting is blank (P-229)."
)


class SiteOut(Model):
    """A place the team works at."""

    hid: str
    code: str | None
    name: str
    region_hid: str
    region: PlaceRef
    path: str
    address1: str | None
    address2: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    country: str | None
    ship_address1: str | None
    ship_address2: str | None
    ship_city: str | None
    ship_state: str | None
    ship_postal_code: str | None
    ship_country: str | None
    ship_instructions: str | None
    ship_same_as_address: bool = Field(
        description="Deliveries go to the street address: the shipping address is read from it."
    )
    operator_hid: str | None
    operator: OperatorRef | None = Field(description="Its own operator.")
    latitude: Latitude | None
    longitude: Longitude | None
    map_url: str | None = Field(description=MAP_URL)
    support_weight: Weight | None = Field(description=PLACE_WEIGHT)
    effective: SiteEffective
    links: list[Link] = Field(description=LINKS_DESCRIPTION)
    notes: str | None
    record_status: RecordStatus
    tags: list[str]
    locations: int = Field(description="How many locations it has, retired ones aside.")
    row_version: int
    created_at: datetime
    updated_at: datetime


class SiteCreate(Model):
    """A new site, in one region."""

    name: Name = Field(min_length=1)
    code: Code | None = None
    region_hid: Hid
    address1: Name | None = None
    address2: Name | None = None
    city: Name | None = None
    state: Name | None = None
    postal_code: Name | None = None
    country: Name | None = None
    ship_address1: Name | None = None
    ship_address2: Name | None = None
    ship_city: Name | None = None
    ship_state: Name | None = None
    ship_postal_code: Name | None = None
    ship_country: Name | None = None
    ship_instructions: LongText | None = None
    ship_same_as_address: bool = False
    operator_hid: Hid | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    support_weight: Weight | None = Field(default=None, description=PLACE_WEIGHT)
    links: list[LinkIn] = Field(default=[], max_length=20, description=LINKS_DESCRIPTION)
    notes: LongText | None = None
    record_status: Literal["draft", "active"] = "active"
    tags: list[ShortText] = Field(default=[], max_length=100)


class SitePatch(Model):
    """Fields of a site to change, and the version they were read at."""

    row_version: int
    name: Name | None = None
    code: Code | None = None
    region_hid: Hid | None = Field(default=None, description="Another region moves the site.")
    address1: Name | None = None
    address2: Name | None = None
    city: Name | None = None
    state: Name | None = None
    postal_code: Name | None = None
    country: Name | None = None
    ship_address1: Name | None = None
    ship_address2: Name | None = None
    ship_city: Name | None = None
    ship_state: Name | None = None
    ship_postal_code: Name | None = None
    ship_country: Name | None = None
    ship_instructions: LongText | None = None
    ship_same_as_address: bool | None = None
    operator_hid: Hid | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    support_weight: Weight | None = Field(default=None, description=PLACE_WEIGHT)
    links: list[LinkIn] | None = Field(default=None, max_length=20, description=LINKS_DESCRIPTION)
    notes: LongText | None = None
    record_status: Literal["draft", "active"] | None = None
    tags: list[ShortText] | None = Field(default=None, max_length=100)


class LocationOut(Model):
    """A place within a site: a building, a floor, a room, a rack."""

    hid: str
    code: str | None
    name: str
    site_hid: str
    site: PlaceRef
    parent_location_hid: str | None
    parent: PlaceRef | None
    kind: str | None
    path: str
    depth: int = Field(description="0 for a location directly in its site.")
    address1: str | None
    address2: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    country: str | None
    ship_address1: str | None
    ship_address2: str | None
    ship_city: str | None
    ship_state: str | None
    ship_postal_code: str | None
    ship_country: str | None
    ship_instructions: str | None
    ship_same_as_address: bool = Field(
        description="Deliveries go to the street address: the shipping address is read from it."
    )
    operator_hid: str | None
    operator: OperatorRef | None = Field(description="Its own operator.")
    latitude: Latitude | None
    longitude: Longitude | None
    map_url: str | None = Field(description=MAP_URL)
    support_weight: Weight | None = Field(description=PLACE_WEIGHT)
    links: list[Link] = Field(description=LINKS_DESCRIPTION)
    notes: str | None
    record_status: RecordStatus
    tags: list[str]
    locations: int = Field(description="How many locations are directly in it, retired aside.")
    items: int = Field(description="How many items have it as their own location.")
    planned_items: int = Field(description="How many items are planned for it, and not there yet.")
    planned_groups: int = Field(description="How many device groups are planned for it.")
    row_version: int
    created_at: datetime
    updated_at: datetime


class LocationCreate(Model):
    """A new location: in a site, or within a location of one."""

    name: Name = Field(min_length=1)
    code: Code | None = None
    site_hid: Hid | None = Field(
        default=None, description="Its site. May be left out when the parent is named."
    )
    parent_location_hid: Hid | None = None
    kind: str | None = Field(
        default=None, max_length=40, description="A value of the location_kind list."
    )
    address1: Name | None = None
    address2: Name | None = None
    city: Name | None = None
    state: Name | None = None
    postal_code: Name | None = None
    country: Name | None = None
    ship_address1: Name | None = None
    ship_address2: Name | None = None
    ship_city: Name | None = None
    ship_state: Name | None = None
    ship_postal_code: Name | None = None
    ship_country: Name | None = None
    ship_instructions: LongText | None = None
    ship_same_as_address: bool = False
    operator_hid: Hid | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    support_weight: Weight | None = Field(default=None, description=PLACE_WEIGHT)
    links: list[LinkIn] = Field(default=[], max_length=20, description=LINKS_DESCRIPTION)
    notes: LongText | None = None
    record_status: Literal["draft", "active"] = "active"
    tags: list[ShortText] = Field(default=[], max_length=100)


class LocationPatch(Model):
    """Fields of a location to change, and the version they were read at."""

    row_version: int
    name: Name | None = None
    code: Code | None = None
    parent_location_hid: Hid | None = Field(
        default=None, description="Another location of the same site moves it. Null: in the site."
    )
    kind: str | None = Field(default=None, max_length=40)
    address1: Name | None = None
    address2: Name | None = None
    city: Name | None = None
    state: Name | None = None
    postal_code: Name | None = None
    country: Name | None = None
    ship_address1: Name | None = None
    ship_address2: Name | None = None
    ship_city: Name | None = None
    ship_state: Name | None = None
    ship_postal_code: Name | None = None
    ship_country: Name | None = None
    ship_instructions: LongText | None = None
    ship_same_as_address: bool | None = None
    operator_hid: Hid | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    support_weight: Weight | None = Field(default=None, description=PLACE_WEIGHT)
    links: list[LinkIn] | None = Field(default=None, max_length=20, description=LINKS_DESCRIPTION)
    notes: LongText | None = None
    record_status: Literal["draft", "active"] | None = None
    tags: list[ShortText] | None = Field(default=None, max_length=100)


class PlaceCount(Model):
    """The items and the components of a set of items."""

    items: int = Field(description="Every item of the set, major and minor.")
    component_count: int


class GeographyNode(PlaceCount):
    """A region, a site or a location, with what is at or beneath it."""

    level: Level
    hid: str
    name: str
    code: str | None
    kind: str | None = Field(description="Of a location.")
    path: str
    record_status: RecordStatus
    planned: int = Field(description="The items planned for it or for a place beneath it.")
    planned_groups: int = Field(description="The device groups planned for it or beneath it.")
    children: list[GeographyNode]


class GeographyTree(Model):
    """The regions, their sites and the locations within them, with the counts of a view."""

    totals: PlaceCount = Field(description="The whole view.")
    unplaced: PlaceCount = Field(description="The items with no location in force.")
    hidden: PlaceCount = Field(description="The items in a place the view leaves out.")
    roots: list[GeographyNode]


# --- contacts ------------------------------------------------------------------------


class ContactRef(Model):
    """A contact, as shown where it is assigned."""

    hid: str
    name: str
    organization: str | None
    email: str | None
    phone: str | None
    phone2: str | None
    record_status: RecordStatus


class UserBrief(Model):
    """The user a contact is: who it signs in as."""

    hid: str
    username: str


class ContactOut(Model):
    """A person or a shared mailbox: one of the people, whatever part they play (P-172)."""

    hid: str
    name: str
    organization: str | None
    email: str | None
    phone: str | None
    phone2: str | None
    notes: str | None
    record_status: RecordStatus
    tags: list[str]
    is_user: bool = Field(description="The contact is the person a user is.")
    user: UserBrief | None = Field(description="The user this contact is, where it is one.")
    uses: int = Field(
        description=(
            "How many records name it: the places and owners it is assigned to, the "
            "operators it stands behind, and the agreements, contracts, vendors and circuits "
            "that name it. `GET /contacts/{hid}/uses` lists them."
        )
    )
    row_version: int
    created_at: datetime
    updated_at: datetime


class ContactCreate(Model):
    """A new contact."""

    name: Name = Field(min_length=1)
    organization: Name | None = None
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=50)
    phone2: str | None = Field(default=None, max_length=50)
    notes: LongText | None = None
    record_status: Literal["draft", "active"] = "active"
    tags: list[ShortText] = Field(default=[], max_length=100)


class ContactPatch(Model):
    """Fields of a contact to change, and the version they were read at."""

    row_version: int
    name: Name | None = None
    organization: Name | None = None
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=50)
    phone2: str | None = Field(default=None, max_length=50)
    notes: LongText | None = None
    record_status: Literal["draft", "active"] | None = None
    tags: list[ShortText] | None = Field(default=None, max_length=100)


class OperatorOut(Model):
    """A short label that stands for the member of the team who looks after what it is on."""

    hid: str
    label: str
    description: str | None
    colour: str | None
    contact_hid: str | None
    contact: ContactRef | None = Field(
        description="The person behind it, with the email and numbers it shows (P-172)."
    )
    user: UserBrief | None = Field(description="The user its contact is, where it is one.")
    scope: Scope | None = Field(
        description="internal where its contact is a user's, external where not; none if nobody."
    )
    is_open: bool = Field(description="Nobody is behind it: no contact, or one that is retired.")
    record_status: RecordStatus
    uses: int = Field(description="How many items, groups and places are given it as their own.")
    row_version: int
    created_at: datetime
    updated_at: datetime


class OperatorCreate(Model):
    """A new operator: a label, with somebody behind it or open."""

    label: str = Field(min_length=1, max_length=40)
    description: LongText | None = None
    colour: str | None = Field(default=None, max_length=20, description="In the form #1f6feb.")
    contact_hid: Hid | None = Field(default=None, description="Left out, an open assignment.")
    record_status: Literal["draft", "active"] = "active"


class OperatorPatch(Model):
    """Fields of an operator to change, and the version they were read at."""

    row_version: int
    label: str | None = Field(default=None, max_length=40)
    description: LongText | None = None
    colour: str | None = Field(default=None, max_length=20)
    contact_hid: Hid | None = Field(
        default=None,
        description="Another contact hands over everything the label is on. Null leaves it open.",
    )
    record_status: Literal["draft", "active"] | None = None


class AssignedPlace(PlaceRef):
    """The place of an assignment, and which of the three it is."""

    level: Level


class AssignmentOut(Model):
    """A contact of one region, site or location, in one role."""

    hid: str
    contact_hid: str | None
    contact: ContactRef | None
    region_hid: str | None
    site_hid: str | None
    location_hid: str | None
    place: AssignedPlace
    role: str
    priority: int
    stop_inheritance: bool
    row_version: int
    created_at: datetime
    updated_at: datetime


NamedType = Literal[
    "region", "site", "location", "owner", "operator", "agreement", "contract", "vendor", "circuit"
]


class NamedRecord(Model):
    """A record that names a contact, and the role the contact has there (P-205)."""

    hid: str
    record_type: NamedType = Field(description="Its kind, as the audit trail names it.")
    label: str = Field(
        description="What it is known by: a place by its path, a contract by its number and "
        "its vendor, a circuit by its enterprise circuit ID or its name, any other by its "
        "name or label."
    )
    record_status: RecordStatus = Field(description="A retired record is listed as any other.")
    role: str | None = Field(
        description="The role the contact has there: a value of `contact_role` for a place "
        "and for a side of a circuit, `primary` or `alternate` for an owner, "
        "`account_manager` or `support_contact` for an agreement, a contract, a vendor and "
        "the carrier of a circuit. Null for an operator, which the contact stands behind."
    )
    priority: int | None = Field(description="Where the record orders the contacts it names.")
    side: Literal["a", "z"] | None = Field(
        description="Of a circuit: the side the contact is named for; null for its carrier."
    )
    colour: str | None = Field(description="Of an operator: the colour of its label.")


class NamedRecords(Model):
    """The records of one kind that name a contact: how many, and at most 100 of them,
    by what each is known by."""

    total: int
    records: list[NamedRecord]


class ContactUses(Model):
    """Every record that names a contact, by kind (P-205): what `uses` of the contact
    counts, listed."""

    contact_hid: str
    total: int = Field(description="How many records name it: `uses` of the contact.")
    places: NamedRecords = Field(description="The regions, sites and locations it is assigned to.")
    owners: NamedRecords = Field(description="The owners it is one of the people of.")
    operators: NamedRecords = Field(description="The operators it stands behind.")
    agreements: NamedRecords
    contracts: NamedRecords
    vendors: NamedRecords = Field(description="The vendors, carriers among them, that name it.")
    circuits: NamedRecords


class AssignmentCreate(Model):
    """A contact for a place in a role, or the word that the place has none."""

    contact_hid: Hid | None = None
    region_hid: Hid | None = None
    site_hid: Hid | None = None
    location_hid: Hid | None = None
    role: str = Field(max_length=40, description="A value of the contact_role list.")
    priority: int | None = Field(
        default=None, ge=1, le=1000, description="1 is primary. Left out, after the last."
    )
    stop_inheritance: bool = Field(
        default=False,
        description="With no contact: none here, and do not look further up.",
    )


class AssignmentPatch(Model):
    """Fields of an assignment to change, and the version they were read at."""

    row_version: int
    contact_hid: Hid | None = None
    role: str | None = Field(default=None, max_length=40)
    priority: int | None = Field(default=None, ge=1, le=1000)
    stop_inheritance: bool | None = None


class EffectiveContact(ContactRef):
    """A contact in force for a place, with the assignment it comes by."""

    assignment_hid: str
    contact_hid: str
    priority: int


PlaceSource = Literal["own", "location", "site", "region", "none"]


class RoleContacts(Model):
    """The contacts in force for one role, and the level they came from."""

    role: str
    label: str
    source: PlaceSource
    source_hid: str | None
    source_path: str | None
    stopped: bool = Field(description="A level said: none here, and do not look further up.")
    overrides_hid: str | None = Field(
        description="The nearest level above the source that has contacts for the role too."
    )
    overrides_path: str | None
    contacts: list[EffectiveContact]


class ShipAddress(Model):
    """A shipping address, taken whole."""

    address1: str | None
    address2: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    country: str | None


class EffectiveShipAddress(Model):
    """The shipping address in force, and the level it came from."""

    value: ShipAddress | None
    same_as_address: bool = Field(description="It is the street address of the level it came from.")
    source: PlaceSource
    source_hid: str | None
    source_path: str | None
    overrides_hid: str | None = Field(
        description="The nearest level above the source that has one too: what it overrides."
    )
    overrides_path: str | None


class EffectivePlaceOperator(Model):
    """The operator of what is at a place and has none from elsewhere, and its level."""

    value: OperatorRef | None
    source: PlaceSource
    source_hid: str | None
    source_path: str | None
    overrides_hid: str | None
    overrides_path: str | None


class EffectiveInstructions(Model):
    """The shipping instructions in force, and the level they came from."""

    value: str | None
    source: PlaceSource
    source_hid: str | None
    source_path: str | None
    overrides_hid: str | None
    overrides_path: str | None


class OpeningOut(Model):
    """What making a place active would bring about: what is planned for it, or for a
    place beneath it that is thereby in use, moves in."""

    level: Level
    hid: str
    path: str
    record_status: RecordStatus
    moves_now: bool = Field(
        description="False while a place above it is not active: nothing moves until then."
    )
    waits_for: PlaceRef | None = Field(
        description="The nearest place above it that is not active. Null when none is."
    )
    waits_for_level: Level | None
    items: int = Field(
        description="The items that would be there: by a plan of their own, or with "
        "the item or the group they are in."
    )
    device_groups: int = Field(description="The device groups that would be there.")
    records_changed: int = Field(
        description="How many records would be written to, each with an entry of its "
        "own in the audit trail. What has no location of its own is not written to."
    )


class PlaceEffective(Model):
    """What a place has in force: its contacts by role, and where deliveries go."""

    level: Level
    hid: str
    path: str
    contacts: list[RoleContacts]
    ship_address: EffectiveShipAddress
    ship_instructions: EffectiveInstructions
    operator: EffectivePlaceOperator


# --- owners --------------------------------------------------------------------------


class OwnerRef(Model):
    """An owner, as named on another record."""

    hid: str
    label: str
    is_external: bool = Field(description="An owner outside the operations team.")


class OwnerMemberOut(Model):
    """One of the people of an owner."""

    hid: str
    owner_hid: str
    contact_hid: str
    contact: ContactRef
    role: Literal["primary", "alternate"]
    priority: int
    row_version: int
    created_at: datetime
    updated_at: datetime


class OwnerMemberAdd(Model):
    """A contact to make one of the people of an owner."""

    contact_hid: Hid
    role: Literal["primary", "alternate"] | None = Field(
        default=None,
        description="Left out, primary for the first member and alternate after that.",
    )
    priority: int | None = Field(default=None, ge=1, le=1000)


class OwnerMemberPatch(Model):
    """Fields of a member of an owner to change, and the version they were read at."""

    row_version: int
    role: Literal["primary", "alternate"] | None = None
    priority: int | None = Field(default=None, ge=1, le=1000)


class OwnerOut(Model):
    """Who answers for an item."""

    hid: str
    label: str
    organization: str | None
    is_external: bool
    exception_reason: str | None
    record_status: RecordStatus
    tags: list[str]
    members: list[OwnerMemberOut] = Field(description="Its people, the primary first.")
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
    tags: list[ShortText] = Field(default=[], max_length=100)


class OwnerPatch(Model):
    """Fields of an owner to change, and the version they were read at."""

    row_version: int
    label: Name | None = None
    organization: Name | None = None
    is_external: bool | None = None
    exception_reason: LongText | None = None
    record_status: Literal["draft", "active"] | None = None
    tags: list[ShortText] | None = Field(default=None, max_length=100)


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


class ItemCatalog(CatalogRef):
    """The catalog entry of an item, with the links of the model."""

    links: list[Link] = Field(description="The links of the model, in order.")


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
    catalog_entry_hid: str | None = Field(description="Its model, which `pid` names (P-232).")
    pid: str | None


ContractStatus = Literal["active", "renewal_pending", "expired", "pending", "cancelled"]
RegistrationStatus = Literal["registered", "pending", "removed", "not_reported"]


class ContractRef(Model):
    """A contract, as named on what it covers."""

    hid: str
    number: str
    vendor_hid: str = Field(description="Its vendor, which `vendor` names (P-232).")
    vendor: str = Field(description="The name of its vendor.")
    status: ContractStatus
    record_status: RecordStatus


class CoverageRef(Model):
    """One coverage of an item: the contract, and the days in force."""

    hid: str = Field(description="The coverage.")
    contract_hid: str
    contract: ContractRef
    starts_on: date | None = Field(description="The day it starts in force. Blank is open.")
    ends_on: date | None = Field(description="The day it ends in force. Blank is open.")
    in_force: bool = Field(description="It covers the item today.")
    left_service: bool = Field(
        description="Ended because the item left service; the vendor may still count it."
    )


class SystemRef(Model):
    """An external system, as named on a registration."""

    hid: str
    name: str
    kind: str


class RegistrationRef(Model):
    """One registration of an item or a group, as shown on that record."""

    hid: str = Field(description="The registration.")
    system_hid: str
    system: SystemRef
    external_id: str | None
    status: RegistrationStatus
    confirmed_at: datetime | None


class GroupRegistrationRef(RegistrationRef):
    """What a stack or a cluster an item is a member of is registered with."""

    group: DeviceGroupRef


class PurchaseLineRef(Model):
    """The line of a purchase request an item arrived on."""

    hid: str
    name: str = Field(description="The reference of the request and the number of the line.")
    request_hid: str
    reference: str
    line: int
    catalog_entry_hid: str | None = Field(
        description=(
            "The model of the line. A line with none takes no item, so an item's line has one."
        )
    )


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


class ReplacementEntry(Model):
    """One replacement an item is part of, and which of its two items this one was (P-241)."""

    hid: str = Field(description="The replacement.")
    part: Literal["left", "came"] = Field(
        description="`left`: this item left, and `item` took its place. `came`: this item "
        "took the place of `item`."
    )
    item: ItemRef = Field(description="The other item.")
    reason: str
    reference: str | None
    replaced_on: date
    row_version: int


class EffectiveLocation(EffectiveReference):
    """A location in force, with its site. The label is its path."""

    source_label: str | None = Field(
        description="The name of the item or the group it came from. Null for its own."
    )
    site_hid: str | None
    site: str | None = Field(description="The name of its site.")
    region_hid: str | None
    region: str | None = Field(description="The name of the region its site is in.")


class EffectiveOperator(EffectiveReference):
    """The operator in force: the label, who is behind it, and where it came from."""

    source_label: str | None = Field(
        description="The name of the item or group, or the path of the place, it came from."
    )
    colour: str | None
    contact_hid: str | None
    contact: str | None = Field(description="The name of the person behind the label.")
    is_open: bool = Field(description="Nobody is behind the label.")
    scope: Scope | None = Field(
        default=None,
        description="internal where its contact is a user's, external where not; none if nobody.",
    )


# --- why a value: the walk that finds it (P-176) --------------------------------------

ResolutionLevel = Literal[
    "own", "device_group", "parent_item", "host", "catalog", "setting", "location", "site", "region"
]
ResolutionOutcome = Literal["decides", "passed_over", "nothing", "retired", "raises"]
# A value of the walk: the HID of a reference, a decimal or a date as text, or a flag.
WalkValue = str | bool | None


class ResolutionStep(Model):
    """One record the walk looks at, and what it holds there."""

    level: ResolutionLevel
    hid: str | None = Field(description="The record looked at. None for a setting.")
    name: str | None = Field(description="Its name, its path for a place, or the setting's key.")
    type: str | None = Field(description="Of a device group: its type.")
    rank: int | None = Field(description="Of a device group: its place among the record's groups.")
    via_hid: str | None = Field(
        description="The group it is nested in that holds the value, where it holds none itself."
    )
    via_name: str | None
    value: WalkValue
    label: str | None = Field(description="What the value is called: a path, a label.")
    outcome: ResolutionOutcome


class ResolutionField(Model):
    """The walk of one value: what is in force, where from, and every step."""

    field: str
    value: WalkValue
    label: str | None
    source: str
    source_hid: str | None
    overrides: WalkValue = Field(
        description="Where the value is the record's own: the value it would have without it."
    )
    overrides_label: str | None
    steps: list[ResolutionStep]


class Resolution(Model):
    """Why a record has each value it may have from elsewhere."""

    hid: str
    fields: list[ResolutionField]


# --- the circuits a device is connected to (P-147) -----------------------------------


class CircuitConnection(Model):
    """A circuit, as the item or the device group it connects lists it."""

    hid: str = Field(description="The HID of the circuit.")
    name: str
    enterprise_circuit_id: str | None
    side: Literal["a", "z"] = Field(description="The side of the circuit the device is on.")
    link_hid: str = Field(description="The HID of the connection, a device of the circuit.")
    record_status: RecordStatus = Field(description="That of the circuit.")


# --- what runs on a host (P-246, P-249) -----------------------------------------------

ReviewReasonName = Literal["no_host", "host_gone", "not_reported"]


class HostRef(Model):
    """What an item runs on, as a person names it: an item, or a stack or a cluster.
    One of `item_hid` and `group_hid` is given, as a device of a circuit names one."""

    item_hid: str | None = Field(description="The item it runs on, where it is an item.")
    group_hid: str | None = Field(description="The stack or the cluster, where it is a group.")
    name: str = Field(description="What it is called: an item's name, a group's name.")
    type: str | None = Field(description="Of a group: `stack` or `cluster`. Null for an item.")
    pid: str | None = Field(description="Of an item: the PID of its model.")
    lifecycle_state: str | None = Field(description="Of an item: its own lifecycle state.")
    record_status: RecordStatus


class ReviewAbout(Model):
    """The record a reason to look at an item is about: its host, or a system."""

    hid: str
    record_type: Literal["item", "device_group", "external_system"]
    label: str = Field(description="What it is known by: its name.")


class ReviewReason(Model):
    """One reason a person should look at an item (P-249). A mark: it refuses nothing."""

    reason: ReviewReasonName = Field(
        description=(
            "`no_host`: of a kind that runs on a host, and names none; `host_gone`: the host "
            "it names is retired, or has left the team's hands; `not_reported`: a system it "
            "is registered with reports it no more."
        )
    )
    about: ReviewAbout | None = Field(
        description="The host or the system the reason is about. Null for `no_host`."
    )


class ItemEffective(Model):
    """The values in force of the fields an item inherits: the amounts and the dates
    from its catalog entry, and for a minor item the owner, the location and the
    standing of the item it is in."""

    owner_hid: EffectiveReference
    planned_location_hid: EffectiveLocation = Field(
        description="Where it is going, by its own plan or by that of what it is in."
    )
    operator_hid: EffectiveOperator = Field(
        description=(
            "The operator in force: its own, that of the item above it, of a group it is "
            "a member of, or of the place it is at."
        )
    )
    location_hid: EffectiveLocation
    lifecycle_state: EffectiveValue
    disposition: EffectiveValue
    expected_online: EffectiveValue
    est_value: EffectiveValue
    support_weight: EffectiveWeight = Field(
        description="Its own, or its model's; for a major item then the setting "
        "`default_item_weight`, raised to `minimum_item_weight` where it is below it."
    )
    annual_support_cost: EffectiveValue
    end_of_sale: EffectiveValue
    end_of_sw_support: EffectiveValue
    end_of_hw_support: EffectiveValue
    ldos: EffectiveValue
    do_not_renew: EffectiveValue = Field(
        description="Whether its support is not to be renewed: its own word, or its model's."
    )
    serial_number: EffectiveValue = Field(
        description=(
            "Its own serial number; for a virtual context with none, that of the item it runs "
            "on, with the source `host` (P-246). Shown, and never matched by."
        )
    )


class ItemOut(Model):
    """One tracked thing. A field that inherits holds the item's own value, and
    `effective` holds the value in force with its source."""

    hid: str
    catalog_entry_hid: str | None
    catalog: ItemCatalog | None
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
    owner_exception: bool = Field(description="The owner in force is outside the operations team.")
    owner_exception_reason: str | None = Field(
        description="Why that owner is an exception: its own reason, set on the owner."
    )
    location_hid: str | None
    location: LocationRef | None = Field(description="Its own location.")
    planned_location_hid: str | None
    planned_location: LocationRef | None = Field(
        description="Where it is going: a location that is not in use yet."
    )
    operator_hid: str | None
    operator: OperatorRef | None = Field(
        description="Its own operator: the label of who of the team looks after it."
    )
    parent_item_hid: str | None
    parent: ItemRef | None = Field(description="The item a minor item is in.")
    position: str | None = Field(description="Where in its parent a minor item is.")
    # What it runs on, and what runs on it (P-246, P-249).
    host_item_hid: str | None = Field(description="The item it runs on, as a person names it.")
    host_group_hid: str | None = Field(
        description="The stack or the cluster it runs on, as a person names it."
    )
    host: HostRef | None = Field(description="What it runs on, as a person names it.")
    observed_host_hid: str | None = Field(description="The item it was seen to run on.")
    observed_host: ItemRef | None
    host_observed_at: datetime | None = Field(description="When it was seen there.")
    host_differs: bool | None = Field(
        description=(
            "The item it was seen on is neither the host named nor a current member of the "
            "stack or cluster named. No fault. Null where either is not known."
        )
    )
    hosted_count: int = Field(description="How many items not retired name it as their host.")
    review: list[ReviewReason] = Field(
        description="The reasons a person should look at it. Empty where there is none."
    )
    purchase_line_hid: str | None
    purchase_line: PurchaseLineRef | None = Field(
        description="The line of a purchase request it arrived on."
    )
    purchase_line_mismatch: bool = Field(
        description=(
            "It is on a line of another model, which 0.6.0 let in: it is to be put right. "
            "An item put on a line now is of the line's model."
        )
    )
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
    do_not_renew: bool | None = Field(
        description="Its own word on renewing its support. Blank has its model's."
    )
    effective: ItemEffective
    groups: list[MembershipRef] = Field(description="Its current memberships of groups.")
    controllers: list[ControllerRef] = Field(
        description="For an endpoint of a controller domain: the controllers of that domain."
    )
    addresses: list[AddressRef] = Field(description="Its addresses, the primary one first.")
    replaces: ReplacementRef | None = Field(
        description="The item whose place this one took, the latest where it took several."
    )
    replaced_by: ReplacementRef | None = Field(
        description="The item that took its place, the latest where it was replaced several times."
    )
    replacements: list[ReplacementEntry] = Field(
        description="Every replacement it is part of, the latest first: by `replaced_on`, "
        "then by when it was entered (P-241)."
    )
    covered: bool = Field(description="A contract covers it today.")
    contract_count: int = Field(
        description="How many contracts cover it today. More than one is worth a look."
    )
    covered_until: date | None = Field(
        description=(
            "The last day its cover runs to. Blank when a coverage names no end, and when "
            "there is none."
        )
    )
    coverage: list[CoverageRef] = Field(description="Its coverages under contracts.")
    out_of_service_contracts: list[ContractRef] = Field(
        description=(
            "For an item out of service, the contracts that still count it: those that "
            "cover it past today, and those whose coverage of it was ended because it left "
            "while their term still runs. The list to send the vendor. Empty for an item "
            "in service."
        )
    )
    registrations: list[RegistrationRef] = Field(
        description="The external systems it is registered with."
    )
    group_registrations: list[GroupRegistrationRef] = Field(
        description=(
            "What a stack or a cluster it is a current member of is registered with: to be "
            "read, and changed on the group."
        )
    )
    # The circuits the item is connected to (P-147).
    circuits: list[CircuitConnection] = Field(
        description="The circuits it is connected to, each with its side: to be read only."
    )
    tags: list[str]
    record_status: RecordStatus
    row_version: int
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None


class HostedItem(Model):
    """An item that runs on a record, or on what runs on it."""

    depth: int = Field(description="1 for what runs on the record itself, 2 for what runs on that.")
    host_hid: str = Field(description="The item or the group it names as its host.")
    item: ItemOut


class HostedList(Model):
    """What runs on an item or a group, and beneath that, each after its host."""

    total: int
    items: list[HostedItem]


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
    location_hid: Hid | None = None
    planned_location_hid: Hid | None = Field(
        default=None,
        description="Where it is going: a location not in use yet. It moves in when that opens.",
    )
    operator_hid: Hid | None = Field(
        default=None, description="An operator: the label of who of the team looks after it."
    )
    parent_item_hid: Hid | None = Field(
        default=None, description="The item this one is in. Given, the item is a minor item."
    )
    position: ShortText | None = Field(
        default=None, description="Where in its parent: PS-A, Slot 3."
    )
    host_item_hid: Hid | None = Field(
        default=None,
        description="The item it runs on. Only an item of a kind that runs on a host has one.",
    )
    host_group_hid: Hid | None = Field(
        default=None, description="The stack or the cluster it runs on. Not with host_item_hid."
    )
    observed_host_hid: Hid | None = Field(default=None, description="The item it was seen on.")
    host_observed_at: datetime | None = Field(
        default=None, description="When it was seen there. Left out, now. With observed_host_hid."
    )
    purchase_line_hid: Hid | None = Field(
        default=None, description="The line of a purchase request it arrived on."
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
    do_not_renew: bool | None = Field(default=None, description="Left out, its model's.")
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
    location_hid: Hid | None = Field(
        default=None, description="Null: a minor item is where the item above it is."
    )
    planned_location_hid: Hid | None = Field(default=None, description="Null gives the plan up.")
    operator_hid: Hid | None = Field(
        default=None, description="Null: the operator it has from above, if any."
    )
    parent_item_hid: Hid | None = Field(
        default=None, description="Null takes a minor item out of its parent."
    )
    position: ShortText | None = None
    host_item_hid: Hid | None = Field(
        default=None,
        description="The item it runs on. Only an item of a kind that runs on a host has one.",
    )
    host_group_hid: Hid | None = Field(
        default=None, description="The stack or the cluster it runs on. Not with host_item_hid."
    )
    observed_host_hid: Hid | None = Field(default=None, description="The item it was seen on.")
    host_observed_at: datetime | None = Field(
        default=None,
        description="When it was seen there. Left out, now. Null with observed_host_hid.",
    )
    purchase_line_hid: Hid | None = None
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
    do_not_renew: bool | None = Field(default=None, description="Null has its model's again.")
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
    position: int | None = Field(
        default=None,
        ge=0,
        le=10_000,
        description=(
            "In a stack, one that no other current member holds. Left out, a member of a "
            "stack takes the lowest free one from 1, the stack's `next_position` (P-219)."
        ),
    )
    joined_on: date | None = Field(default=None, description="Left out, today.")
    drop_identity: bool = Field(
        default=False,
        description=(
            "A member of a stack only: in the same change the item's own hostname and FQDN "
            "are cleared, its addresses removed and its own location cleared, so that the "
            "stack's is in force (P-217)."
        ),
    )
    disposition: str | None = Field(
        default=None,
        max_length=12,
        description=(
            "Given, the item's disposition from this change, as the rule of its lifecycle "
            "state allows. Left out, it stays as it is."
        ),
    )
    expected_online: bool | None = Field(
        default=None,
        description=(
            "Given, whether the item is expected online from this change, as the rule of "
            "its lifecycle state allows. Left out, it stays as it is."
        ),
    )


class MembersAdd(Model):
    """Items to make members of a group together. The group is checked once all are in."""

    members: list[MemberAdd] = Field(
        min_length=1,
        max_length=settings.MOST_ITEMS_PER_REQUEST,
        description="At most as many as the setting `max_items_per_request` says.",
    )


class LeavingItem(Model):
    """What an item that leaves a group is to have from the end (P-218).

    Each is checked by the item's own rules once the membership has ended. A field left
    out stays as it is, and null clears hostname, fqdn, location_hid and condition.
    """

    hostname: HostName | None = None
    fqdn: HostName | None = None
    location_hid: Hid | None = None
    lifecycle_state: str | None = Field(
        default=None,
        max_length=20,
        description="The state to move to, by a move the rules list, as a transition makes it.",
    )
    state_reason: str | None = Field(
        default=None,
        max_length=40,
        description="A value of the state_reason list: why it moves. With lifecycle_state only.",
    )
    disposition: str | None = Field(
        default=None,
        max_length=12,
        description="With lifecycle_state, as a transition takes it; without, as an edit does.",
    )
    expected_online: bool | None = Field(
        default=None,
        description="With lifecycle_state, as a transition takes it; without, as an edit does.",
    )
    condition: str | None = Field(
        default=None,
        max_length=40,
        description="A value of the item_condition list. Null clears it; left out, it stays "
        "(P-245).",
    )


class Replace(Model):
    """The replacement of an item: what takes its place, why and when, and what each of
    the two is to have from it (P-242)."""

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
    drop_identity: bool = Field(
        default=False,
        description=(
            "Where the item that leaves is a current member of a stack: in the same change "
            "the item that comes gives up its own hostname, FQDN, addresses and location, as "
            "a member that joins a stack with it does (P-217)."
        ),
    )
    disposition: str | None = Field(
        default=None,
        max_length=12,
        description=(
            "Given, the disposition of the item that comes, as the rule of its lifecycle "
            "state allows. Left out, it stays as it is."
        ),
    )
    expected_online: bool | None = Field(
        default=None,
        description=(
            "Given, whether the item that comes is expected online, as the rule of its "
            "lifecycle state allows. Left out, it stays as it is."
        ),
    )
    old_item: LeavingItem | None = Field(
        default=None,
        description=(
            "What the item that leaves is to have from the replacement, as the end of a "
            "membership takes `item` (P-218): applied once its memberships have ended. Given "
            "with a replaced_on that has come."
        ),
    )
    hand_over_hosted: bool = Field(
        default=True,
        description=(
            "Whether what runs on the item that leaves, each item that names it as "
            "`host_item_hid`, is given the item that comes as its host, each by a change "
            "that names the replacement (P-247). Left out, true. Where something is handed "
            "over, the item that comes must be one that may be a host."
        ),
    )


class ReplacementRemove(Model):
    """Why a replacement that was a mistake is removed, by an Admin (P-238)."""

    reason: LongText = Field(
        min_length=1, description="Required, and kept in the audit event of the removal."
    )


class MakeStack(Model):
    """A stack made of an item that stands alone, with the item as its first member (P-243)."""

    row_version: int = Field(description="The version of the item.")
    name: Name | None = Field(
        default=None, description="The stack's name. Left out or blank, the item's own."
    )
    members: list[MemberAdd] = Field(
        default=[],
        max_length=settings.MOST_ITEMS_PER_REQUEST,
        description=(
            "More members, each as `POST /device-groups/{hid}/members` takes one, added "
            "after the first."
        ),
    )


class MemberPatch(Model):
    """Fields of a membership to change, and the version they were read at."""

    row_version: int
    role: str | None = Field(default=None, max_length=20)
    position: int | None = Field(
        default=None,
        ge=0,
        le=10_000,
        description="In a stack, one that no other current member holds (P-219).",
    )
    joined_on: date | None = None
    left_on: date | None = Field(default=None, description="Given, the membership ends.")
    item: LeavingItem | None = Field(
        default=None,
        description=(
            "Given with left_on on a current membership: what the item is to have from the "
            "end, changed with it (P-218)."
        ),
    )


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


class GroupEffective(Model):
    """What a device group has in force of what it may have from the group it is in."""

    owner_hid: EffectiveReference
    operator_hid: EffectiveOperator
    location_hid: EffectiveLocation
    planned_location_hid: EffectiveLocation


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
    owner_exception: bool = Field(description="Its owner is outside the operations team.")
    owner_exception_reason: str | None = Field(description="That owner's reason.")
    location_hid: str | None
    location: LocationRef | None
    planned_location_hid: str | None
    planned_location: LocationRef | None = Field(
        description="Where the group is going: a location that is not in use yet."
    )
    operator_hid: str | None
    operator: OperatorRef | None = Field(
        description="Its own operator, which is that of its members that have none."
    )
    effective: GroupEffective
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
    hosted_count: int = Field(
        description="How many items not retired name it as their host (P-246)."
    )
    next_position: int | None = Field(
        description=(
            "A stack: the lowest position from 1 that no current member holds, which a "
            "member added with none takes (P-219). Null for a group of another type."
        )
    )
    addresses: list[AddressRef]
    registrations: list[RegistrationRef] = Field(
        description="The external systems the group is registered with, as one device."
    )
    # The circuits the group is connected to (P-147).
    circuits: list[CircuitConnection] = Field(
        description="The circuits it is connected to, each with its side: to be read only."
    )
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
    location_hid: Hid | None = None
    planned_location_hid: Hid | None = None
    operator_hid: Hid | None = None
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
    members: list[MemberAdd] = Field(
        default=[],
        max_length=settings.MOST_ITEMS_PER_REQUEST,
        description="At most as many as the setting `max_items_per_request` says.",
    )


class DeviceGroupPatch(Model):
    """Fields of a device group to change, and the version they were read at."""

    row_version: int
    type: GroupType | None = None
    name: Name | None = None
    hostname: HostName | None = None
    fqdn: HostName | None = None
    parent_group_hid: Hid | None = None
    owner_hid: Hid | None = None
    location_hid: Hid | None = None
    planned_location_hid: Hid | None = None
    operator_hid: Hid | None = None
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


# --- several retired at once, and deleting (P-227, P-228, P-236) ---------------------

LABEL = (
    "What it is known by: an item by its name, host name, serial number or asset tag, the "
    "first it has, and a device group by its name."
)


class RetireMany(Model):
    """Items or device groups to retire at once, as a person ticked them."""

    hids: list[Hid] = Field(
        min_length=1,
        max_length=removal.MOST_AT_ONCE,
        description="Each is retired as its own retire route does. One named twice counts once.",
    )
    dry_run: bool = Field(
        default=False,
        description="Answer what it would do, `hosted` among it, and change nothing (P-247).",
    )


class RecordLabel(Model):
    """A record of a request that retires or deletes several."""

    hid: str
    label: str = Field(description=LABEL)


class Dependent(Model):
    """A record that depends on one that is to be deleted, and so stands in the way."""

    record_type: str = Field(
        description="Its kind, as the audit trail names it: `contract` for a coverage under "
        "it, `purchase_line`, `item` for an item installed in it or that runs on it, "
        "`item_replacement`, `circuit`, `reference_file`, or `device_group` for a group "
        "nested in it."
    )
    hid: str
    label: str = Field(
        description="What it is known by: a contract by its number, a purchase line as "
        "RITM0012345/2, a replacement by its two items, a circuit by its enterprise circuit "
        "ID or its name, a reference by its title, an item or a group as `label` above."
    )


class RetireRefused(RecordLabel):
    """A record the rules did not let be retired."""

    detail: str = Field(description="Why.")
    depends_on: list[Dependent] = Field(
        description="Where what runs on it is why, a stack or a cluster that items name as "
        "their host: those items (P-247). Empty otherwise.",
    )


class HostedRetired(RecordLabel):
    """An item retired with the host it runs on, which the request named (P-247)."""

    host_hid: str = Field(
        description="The item it runs on, which went first: one named, or one that went "
        "with one named."
    )


class RetiredMany(Model):
    """What a request that retires several did, or with `dry_run` would do, with each."""

    dry_run: bool
    retired: list[RecordLabel] = Field(description="What this request retired.")
    already: list[RecordLabel] = Field(description="What was retired before it: not refused.")
    refused: list[RetireRefused]
    missing: list[str] = Field(description="Each HID that names no such record.")
    hosted: list[HostedRetired] = Field(
        description="The items not named that are retired with those named, because they "
        "run on one of them or on what runs on one, each once (P-247). Empty for groups.",
    )


class DeleteMany(Model):
    """Items or device groups that were a mistake, to delete, for an Admin."""

    hids: list[Hid] = Field(min_length=1, max_length=removal.MOST_AT_ONCE)
    reason: LongText | None = Field(
        default=None,
        description="Why they are deleted, kept in the audit event of each. A deletion "
        "requires it, and a dry run does not.",
    )
    dry_run: bool = Field(default=False, description="Answer what it would do, and change nothing.")


class DeleteRefused(RecordLabel):
    """A record that is not deleted, and what depends on it."""

    depends_on: list[Dependent]


class DeletedMany(Model):
    """What a request that deletes several did, or with `dry_run` would do, with each."""

    dry_run: bool
    deleted: list[RecordLabel]
    refused: list[DeleteRefused]
    missing: list[str] = Field(description="Each HID that names no such record.")


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


# --- contracts and coverage ----------------------------------------------------------

Url = Annotated[str, Field(max_length=2000)]


PartBegun = Literal["created", "renewal", "joined", "left"]


class NextTerm(Model):
    """A term that is still to begin: a renewal that was entered ahead of its period."""

    number: str | None = Field(description="Its number, where the renewal gives another.")
    starts_on: date
    ends_on: date | None
    annual_cost: Money | None
    purchase_reference: str | None
    with_agreement: bool = Field(
        default=False,
        description=(
            "A new number that waits on the agreement's next term and has no dates of its "
            "own: `starts_on` and `ends_on` are the agreement's, as they stand."
        ),
    )


# --- the contacts of agreements and contracts ----------------------------------------

ContractContactRole = Literal["account_manager", "support_contact"]
ContractContactSource = Literal["own", "agreement", "none"]


class ContractContactOut(Model):
    """A contact record named for an agreement or a contract, in a role."""

    hid: str = Field(description="The naming: what is changed and removed.")
    agreement_hid: str | None = Field(description="The agreement it is named for, or blank.")
    contract_hid: str | None = Field(description="The contract it is named for, or blank.")
    role: ContractContactRole
    priority: int = Field(description="The order in which they are listed, from 1.")
    contact_hid: str
    contact: ContactRef = Field(
        description="The contact as its record is now. A retired one is still listed, so marked."
    )
    row_version: int
    created_at: datetime
    updated_at: datetime


class ContractContactAdd(Model):
    """A contact record to name for an agreement or a contract, in a role."""

    contact_hid: Hid
    role: ContractContactRole
    priority: int | None = Field(
        default=None,
        ge=1,
        le=1000,
        description="Left out, one more than the highest there is for the record and the role.",
    )


class ContractContactPatch(Model):
    """Fields of a naming to change, and the version they were read at. It stays with
    its agreement or its contract."""

    row_version: int
    contact_hid: Hid | None = None
    role: ContractContactRole | None = None
    priority: int | None = Field(default=None, ge=1, le=1000)


class EffectiveContacts(Model):
    """The contacts in force for one role, and the record they came from: the record's
    own where it names any, else, for a contract, its agreement's, else none."""

    value: list[ContractContactOut]
    source: ContractContactSource
    source_hid: str | None


class AgreementEffective(Model):
    """The contacts an agreement has in force for each role: its own."""

    account_managers: EffectiveContacts
    support_contacts: EffectiveContacts


class AgreementRef(Model):
    """A support agreement, as named on a contract that is in it."""

    hid: str
    name: str
    number: str | None


class AgreementOut(Model):
    """A support agreement with a vendor, such as an enterprise agreement, that groups
    contracts. A contract in it has from it what the contract leaves blank."""

    hid: str
    name: str
    number: str | None = Field(description="The agreement's own number, if it has one.")
    vendor_hid: str
    vendor: VendorRef
    reseller_hid: str | None
    reseller: VendorRef | None
    starts_on: date | None
    ends_on: date | None
    status: ContractStatus
    support_level: str | None
    purchase_reference: str | None
    account_manager: str | None = Field(description="Whom to ask about it: free text.")
    support_contact: str | None = Field(description="Whom to call for support: free text.")
    contacts: list[ContractContactOut] = Field(
        description="The contact records it names, by role and then by priority."
    )
    effective: AgreementEffective
    support_url: str | None
    annual_cost: Money | None = Field(description="The agreement's own total, added to nothing.")
    notes: str | None
    record_status: RecordStatus
    tags: list[str]
    lapsed: bool = Field(description="Its period has ended, and it still says it is active.")
    next_term: NextTerm | None = Field(
        description="The term that begins on a day to come. Until then the present one runs on."
    )
    contracts: int = Field(description="How many contracts that are not retired are in it.")
    members_to_review: list[ContractRef] = Field(
        description=(
            "Its members that still say their renewal is pending or that they have expired "
            "while it runs on: no renewal of an agreement changes them, and a person "
            "makes each active, takes it out, or retires it (D-180)."
        )
    )
    row_version: int
    created_at: datetime
    updated_at: datetime


class AgreementRenewed(AgreementOut):
    """An agreement as a renewal leaves it, with what the renewal did with each contract
    that shares its period and how many coverages it left behind."""

    members: list[MemberRenewedOut]
    left_behind: int
    to_review: list[ContractRef] = Field(
        description="The members to look at: those of `members` with `to_review`."
    )


class AgreementCreate(Model):
    """A new support agreement. Contracts are put into it afterwards."""

    name: Name = Field(min_length=1)
    number: ShortText | None = None
    vendor_hid: Hid
    reseller_hid: Hid | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    status: ContractStatus = "active"
    support_level: Name | None = None
    purchase_reference: Name | None = None
    account_manager: LongText | None = None
    support_contact: LongText | None = None
    support_url: Url | None = None
    annual_cost: Money | None = None
    notes: LongText | None = None
    record_status: Literal["draft", "active"] = "active"
    tags: list[ShortText] = Field(default=[], max_length=100)


class AgreementPatch(Model):
    """Fields of an agreement to change, and the version they were read at. Every
    contract in it that says nothing of its own shows the change at once."""

    row_version: int
    name: Name | None = None
    number: ShortText | None = None
    vendor_hid: Hid | None = None
    reseller_hid: Hid | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    status: ContractStatus | None = None
    support_level: Name | None = None
    purchase_reference: Name | None = None
    account_manager: LongText | None = None
    support_contact: LongText | None = None
    support_url: Url | None = None
    annual_cost: Money | None = None
    notes: LongText | None = None
    record_status: Literal["draft", "active"] | None = None
    tags: list[ShortText] | None = Field(default=None, max_length=100)


class ContractEffectiveValue(EffectiveValue):
    """A value a contract has in force, where it came from, and what its agreement
    gives for it."""

    from_agreement: str | None = Field(
        description=(
            "What the agreement gives for this field today, whether the contract overrides "
            "it or not. Blank for a contract in no agreement, and where the agreement has "
            "nothing."
        )
    )


class ContractEffectiveReference(EffectiveReference):
    """The reseller a contract has in force, where it came from, and the agreement's."""

    from_agreement: str | None = Field(
        description="The HID of the reseller the agreement gives, whether overridden or not."
    )
    from_agreement_label: str | None = Field(description="That reseller's name.")


class ContractEffective(Model):
    """What a contract has in force of the fields it may have from its agreement, each
    with what the agreement gives for it, so that an override says what it is in place
    of."""

    reseller_hid: ContractEffectiveReference
    starts_on: ContractEffectiveValue
    ends_on: ContractEffectiveValue
    support_level: ContractEffectiveValue
    account_manager: ContractEffectiveValue
    support_contact: ContractEffectiveValue
    support_url: ContractEffectiveValue
    account_managers: EffectiveContacts = Field(
        description="Its own account managers where it names any, else its agreement's."
    )
    support_contacts: EffectiveContacts = Field(
        description="Its own support contacts where it names any, else its agreement's."
    )


class ContractOut(Model):
    """A support contract. It is one record for every item it covers: what it says is
    said here, once. A field it may have from its agreement holds the contract's own
    value, and `effective` the value in force with its source."""

    hid: str
    number: str
    vendor_hid: str
    vendor: VendorRef = Field(description="The manufacturer or the provider.")
    agreement_hid: str | None
    agreement: AgreementRef | None = Field(
        description="The agreement it is grouped into. Blank for one that stands by itself."
    )
    effective: ContractEffective
    reseller_hid: str | None
    reseller: VendorRef | None = Field(description="The vendor it was bought through.")
    starts_on: date | None
    ends_on: date | None
    status: ContractStatus = Field(description="What a person says of it. Never set by the clock.")
    support_level: str | None
    purchase_reference: str | None = Field(
        description="The request or tracking number the present term was bought under."
    )
    account_manager: str | None = Field(description="Whom to ask about the contract: free text.")
    support_contact: str | None = Field(description="Whom to call for support: free text.")
    contacts: list[ContractContactOut] = Field(
        description="The contact records it names of its own, by role and then by priority."
    )
    support_url: str | None = Field(description="Where support is reached online.")
    annual_cost: Money | None = Field(description="The contract's own total, added to nothing.")
    notes: str | None
    record_status: RecordStatus
    tags: list[str]
    covers_today: bool = Field(
        description="Active and today is within its period, or past it with its renewal pending."
    )
    lapsed: bool = Field(description="Its period has ended, and it still says it is active.")
    next_term: NextTerm | None = Field(
        description="The term that begins on a day to come. Until then the present one runs on."
    )
    covered_items: int = Field(description="How many items it covers today.")
    items_in_scope: int = Field(
        description="How many items have a coverage under it that has not been ended."
    )
    ends_with_term: bool = Field(
        description=(
            "It is not to be renewed: it covers to the end of its present term, is not lapsed "
            "after it, and is expired in force from the next day."
        )
    )
    renewal_pending_days: int | None = Field(
        description=(
            "While its renewal is pending, the days since the end of the term the renewal is "
            "for, and zero before that end. Blank otherwise."
        )
    )
    renewal_overdue: bool = Field(
        description="Its renewal has been pending for longer than `renewal_pending_overdue_days`."
    )
    part_began_on: date | None = Field(
        default=None,
        description=(
            "The day the present part of its history began. Answered by `GET "
            "/contracts/{hid}`, and blank in a list."
        ),
    )
    part_began_by: PartBegun | None = Field(
        default=None, description="What began the present part. Blank in a list, as above."
    )
    row_version: int
    created_at: datetime
    updated_at: datetime


class ContractRenewed(ContractOut):
    """A contract as a renewal leaves it, with what the renewal did besides."""

    left_behind: int = Field(
        description=(
            "How many coverages the renewal ended with the present term, because their items "
            "are not to be renewed."
        )
    )


class ContractCreate(Model):
    """A new contract. Items are put under it afterwards."""

    number: ShortText = Field(min_length=1)
    vendor_hid: Hid | None = Field(
        default=None, description="Left out, the vendor of the agreement it is put into."
    )
    agreement_hid: Hid | None = None
    reseller_hid: Hid | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    status: ContractStatus = "active"
    support_level: Name | None = None
    purchase_reference: Name | None = None
    account_manager: LongText | None = None
    support_contact: LongText | None = None
    support_url: Url | None = None
    annual_cost: Money | None = None
    notes: LongText | None = None
    record_status: Literal["draft", "active"] = "active"
    tags: list[ShortText] = Field(default=[], max_length=100)
    ends_with_term: bool = Field(
        default=False, description="It is not to be renewed, and ends with its present term."
    )


class ContractPatch(Model):
    """Fields of a contract to change, and the version they were read at. Every item
    under it shows the change at once."""

    row_version: int
    number: ShortText | None = None
    vendor_hid: Hid | None = None
    agreement_hid: Hid | None = Field(
        default=None,
        description="Puts the contract into an agreement, or with null takes it out of one.",
    )
    reseller_hid: Hid | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    status: ContractStatus | None = None
    support_level: Name | None = None
    purchase_reference: Name | None = None
    account_manager: LongText | None = None
    support_contact: LongText | None = None
    support_url: Url | None = None
    annual_cost: Money | None = None
    notes: LongText | None = None
    record_status: Literal["draft", "active"] | None = None
    tags: list[ShortText] | None = Field(default=None, max_length=100)
    ends_with_term: bool | None = Field(
        default=None, description="It is not to be renewed, and ends with its present term."
    )


class ContractRenew(Model):
    """A renewal: the new number, the new period, or both, and what else changes with
    them. A field that is left out stays as it is."""

    row_version: int
    number: ShortText | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    annual_cost: Money | None = None
    purchase_reference: Name | None = None
    reseller_hid: Hid | None = None
    support_level: Name | None = None
    notes: LongText | None = None
    status: ContractStatus | None = Field(
        default=None,
        description="Left out, `active` for a renewal in force at once, and as it is otherwise.",
    )
    withdraw: bool = Field(
        default=False,
        description="Withdraw the term that is still to begin. Nothing else is sent with it.",
    )


MemberChoice = Literal["same", "new_number", "ends"]


class MemberRenewal(Model):
    """What a renewal of an agreement does with one contract that shares its period."""

    contract_hid: Hid
    renewal: MemberChoice = Field(
        default="same",
        description=(
            "`same`: it follows into the new term under its number. `new_number`: its new "
            "number begins with the new term. `ends`: it is let go with the present term."
        ),
    )
    number: ShortText | None = Field(default=None, description="The new number, for `new_number`.")
    status: ContractStatus | None = Field(
        default=None,
        description=(
            "The status it is to have from this change: the operator's confirmation that it "
            "moves forward. Left out, its status stays as it is; nothing else in the renewal "
            "changes it."
        ),
    )
    annual_cost: Money | None = Field(default=None, description="Its cost in the new term.")
    purchase_reference: Name | None = Field(
        default=None, description="What its new term was bought under."
    )


class AgreementRenew(ContractRenew):
    """A renewal of an agreement, and what it does with each contract that shares its
    period. A member left out is `same`, or `ends` where it is marked to end with its
    term."""

    members: list[MemberRenewal] = Field(default=[], max_length=1000)


class MemberRenewedOut(Model):
    """What a renewal of an agreement did with one contract that shares its period."""

    contract_hid: str
    number: str = Field(description="The number it has in the new term, or its last one.")
    renewal: MemberChoice
    left_behind: int
    to_review: bool = Field(
        description=(
            "Carried into the new term while it says its renewal is pending or that it has "
            "expired, or while it is marked not to be renewed: a person looks at it."
        )
    )


class AgreementTerm(Model):
    """A term an agreement had before it was renewed."""

    number: str | None
    starts_on: date | None
    ends_on: date | None
    annual_cost: Money | None
    purchase_reference: str | None
    renewed_at: datetime = Field(description="When the renewal that ended this term was made.")
    renewed_by: str | None
    renewed_by_name: str | None
    began_on: date | None = Field(description="The first day of this part of its history.")
    ended_on: date | None = Field(description="The last day of this part of its history.")
    began_by: PartBegun


TermSource = Literal["own", "agreement", "none"]


class ContractTerm(Model):
    """A term a contract had before it was renewed, with the dates it had in force."""

    number: str
    starts_on: date | None = Field(
        description=(
            "The first day of the term in force: the contract's own, or, where it had none, "
            "that of the agreement's term in force when the contract's term began."
        )
    )
    ends_on: date | None = Field(description="The last day of the term in force, in the same way.")
    starts_on_source: TermSource
    ends_on_source: TermSource
    agreement_hid: str | None = Field(description="The agreement the contract was in then.")
    annual_cost: Money | None
    purchase_reference: str | None
    renewed_at: datetime = Field(
        description="When the change that ended this part was made: a renewal, a join or a leave."
    )
    renewed_by: str | None
    renewed_by_name: str | None
    began_on: date | None = Field(description="The first day of this part of its history.")
    ended_on: date | None = Field(description="The last day of this part of its history.")
    began_by: PartBegun = Field(
        description="What began this part: `created`, `renewal`, `joined` or `left`."
    )


class CoverageOut(Model):
    """One item under one contract, for a range of days."""

    hid: str
    contract_hid: str
    contract: ContractRef
    item_hid: str
    item: ItemRef
    item_lifecycle_state: str | None = Field(description="The item's own lifecycle state.")
    item_record_status: RecordStatus
    starts_on: date | None = Field(description="Its own. Blank takes the contract's.")
    ends_on: date | None = Field(description="Its own. Blank takes the contract's.")
    effective_starts_on: date | None = Field(description="The day it starts in force.")
    effective_ends_on: date | None = Field(description="The day it ends in force.")
    in_force: bool = Field(description="It covers the item today.")
    left_service: bool = Field(
        description="Ended because the item left service; cleared once the vendor is told."
    )
    row_version: int
    created_at: datetime
    updated_at: datetime


class CoverageEntry(Model):
    """One item to put under a contract."""

    item_hid: Hid
    starts_on: date | None = Field(default=None, description="Left out, the contract's.")
    ends_on: date | None = Field(default=None, description="Left out, the contract's.")


class CoverageAdd(Model):
    """Items to put under a contract together: all of them, or none."""

    items: list[CoverageEntry] = Field(
        min_length=1,
        max_length=settings.MOST_ITEMS_PER_REQUEST,
        description="At most as many as the setting `max_items_per_request` says.",
    )


class CoveragePatch(Model):
    """The days of a coverage to change, and the version they were read at. A coverage
    is ended by giving it `ends_on`."""

    row_version: int
    starts_on: date | None = None
    ends_on: date | None = None
    left_service: bool | None = Field(
        default=None, description="False says that the vendor has been told the item left."
    )


# --- the contacts of carriers and of circuits (P-149) --------------------------------

CarrierContactRole = Literal["account_manager", "support_contact"]
CircuitSide = Literal["a", "z"]


class VendorContactOut(Model):
    """A contact record named for a vendor: its account team or its support desk."""

    hid: str = Field(description="The naming: what is changed and removed.")
    vendor_hid: str
    role: CarrierContactRole
    priority: int = Field(description="The order in which they are listed, from 1.")
    contact_hid: str
    contact: ContactRef = Field(
        description="The contact as its record is now: the number and the address of a "
        "support desk are its telephone and its email. A retired one is still listed, so "
        "marked."
    )
    row_version: int
    created_at: datetime
    updated_at: datetime


# Defined above, before the contacts it lists.
VendorOut.model_rebuild()


class VendorContactAdd(Model):
    """A contact record to name for a vendor, in a role."""

    contact_hid: Hid
    role: CarrierContactRole
    priority: int | None = Field(
        default=None,
        ge=1,
        le=1000,
        description="Left out, one more than the highest there is for the vendor and the role.",
    )


class VendorContactPatch(Model):
    """Fields of a naming of a vendor to change, and the version they were read at. It
    stays with its vendor."""

    row_version: int
    contact_hid: Hid | None = None
    role: CarrierContactRole | None = None
    priority: int | None = Field(default=None, ge=1, le=1000)


class CircuitContactOut(Model):
    """A contact a circuit names of its own: one of the carrier's, with no side, or a
    site contact of a side."""

    hid: str = Field(description="The naming: what is changed and removed.")
    circuit_hid: str
    side: CircuitSide | None = Field(
        description="Blank for one of the carrier's; `a` or `z` for a site contact of that side."
    )
    role: str = Field(
        description="With no side, `account_manager` or `support_contact`; with a side, a "
        "value of the `contact_role` list."
    )
    priority: int = Field(description="The order in which they are listed, from 1.")
    contact_hid: str
    contact: ContactRef = Field(
        description="The contact as its record is now. A retired one is still listed, so marked."
    )
    row_version: int
    created_at: datetime
    updated_at: datetime


class CircuitContactAdd(Model):
    """A contact record to name for a circuit: one of the carrier's, or a site contact of
    a side."""

    contact_hid: Hid
    side: CircuitSide | None = Field(
        default=None,
        description="Left out, one of the carrier's, in the role `account_manager` or "
        "`support_contact`; `a` or `z`, a site contact of that side, in a role of the "
        "`contact_role` list.",
    )
    role: str = Field(max_length=40)
    priority: int | None = Field(
        default=None,
        ge=1,
        le=1000,
        description="Left out, one more than the highest there is for the circuit, the side "
        "and the role.",
    )


class CircuitContactPatch(Model):
    """Fields of a naming of a circuit to change, and the version they were read at. It
    stays with its circuit, and its role is one its side takes."""

    row_version: int
    contact_hid: Hid | None = None
    side: CircuitSide | None = Field(
        default=None, description="Sent as null, the naming is one of the carrier's."
    )
    role: str | None = Field(default=None, max_length=40)
    priority: int | None = Field(default=None, ge=1, le=1000)


class NamedContact(Model):
    """A contact in force for a circuit, with what names it: a contact of the circuit
    or of its carrier, or, among the site contacts, an assignment of a place."""

    hid: str = Field(description="The naming, or the assignment, it comes by.")
    role: str
    priority: int = Field(description="The order in which they are listed, from 1.")
    contact_hid: str
    contact: ContactRef = Field(
        description="The contact as its record is when it is read. A retired one is marked so."
    )


class CarrierContacts(Model):
    """The carrier's contacts of a circuit in force for one role: its own where it names
    any, else those of its primary carrier, else none."""

    value: list[NamedContact]
    source: Literal["own", "vendor", "none"]
    source_hid: str | None = Field(
        description="The circuit for its own, the vendor for the carrier's."
    )


class SiteRoleContacts(Model):
    """The site contacts of one side of a circuit in force for one role, and the level
    they came from: the circuit's own, or as the location of the side resolves them."""

    role: str
    value: list[NamedContact]
    source: Literal["own", "location", "site", "region"] = Field(
        description="`own` for those the circuit names; `location` for the location of the "
        "side or one above it, `site` or `region` for the level they came from."
    )
    source_hid: str = Field(description="The circuit, or the place, they came from.")


class SiteContacts(Model):
    """The site contacts in force of each side of a circuit: one entry for each role
    that has any, in the order of the `contact_role` list."""

    a: list[SiteRoleContacts]
    z: list[SiteRoleContacts]


class CircuitContactsEffective(Model):
    """The contacts a circuit has in force, for its `effective` block."""

    account_managers: CarrierContacts
    support_contacts: CarrierContacts
    site_contacts: SiteContacts


# --- purchases -----------------------------------------------------------------------

PurchaseStatus = Literal["draft", "pending", "ordered", "received", "cancelled"]


class PurchaseLineOut(Model):
    """One line of a purchase request: a model or a part number, and how many."""

    hid: str
    request_hid: str
    reference: str = Field(description="The reference of its request.")
    request_status: PurchaseStatus
    name: str = Field(description="How the line is named: `RITM0012345/2`.")
    line: int
    catalog_entry_hid: str | None = Field(description="The model. A line with none is not tracked.")
    catalog: CatalogRef | None
    part_number: str | None = Field(description="As the procurement system gave it.")
    description: str | None = Field(description="As the procurement system gave it.")
    tracked: bool = Field(
        description=(
            "The line has a model. One that has none takes no item, is in no count and is "
            "not waited for."
        )
    )
    quantity: int
    received_quantity: int = Field(description="The items that name this line.")
    pending_quantity: int = Field(
        description="What is still to come: nothing on a line that is not tracked."
    )
    mismatched_items: int = Field(
        description=(
            "How many of the items that name this line are of another model, which 0.6.0 "
            "let in, counted as the item list counts them. They are found by "
            "`purchase_line_mismatch` in the item list."
        )
    )
    destination_site_hid: str | None
    destination_site: PlaceRef | None
    expected_on: date | None
    notes: str | None
    row_version: int
    created_at: datetime
    updated_at: datetime


class ReceivedOut(PurchaseLineOut):
    """A line after a receipt, with the items the receipt created."""

    items: list[ItemRef]


class PurchaseLineAdd(Model):
    """A new line of a purchase request: a model, or a part number for what is not
    tracked, or both."""

    catalog_entry_hid: Hid | None = Field(
        default=None, description="The model. Left out, the line is not tracked."
    )
    part_number: ShortText | None = Field(
        default=None, description="As the procurement system gave it."
    )
    description: LongText | None = Field(
        default=None, description="As the procurement system gave it."
    )
    quantity: int = Field(ge=1, le=purchases.MAX_QUANTITY)
    line: int | None = Field(
        default=None, ge=1, le=purchases.MAX_QUANTITY, description="Left out, the next."
    )
    destination_site_hid: Hid | None = None
    expected_on: date | None = None
    notes: LongText | None = None


class PurchaseLinePatch(Model):
    """Fields of a purchase line to change, and the version they were read at."""

    row_version: int
    catalog_entry_hid: Hid | None = Field(
        default=None,
        description=(
            "The model, corrected at any time. Null takes it off, which leaves the line not "
            "tracked, only while nothing has arrived on it."
        ),
    )
    items: Literal["follow", "stay"] | None = Field(
        default=None,
        description=(
            "Where items have arrived on the line and its model is corrected: `follow` gives "
            "each of them that is not retired the corrected model as well, in the same change, "
            "and `stay` leaves them as they are, to be found by `purchase_line_mismatch`. "
            "Required then, and a `422` without it."
        ),
    )
    part_number: ShortText | None = None
    description: LongText | None = None
    quantity: int | None = Field(
        default=None, ge=0, le=purchases.MAX_QUANTITY, description="Never below what has arrived."
    )
    line: int | None = Field(default=None, ge=1, le=purchases.MAX_QUANTITY)
    destination_site_hid: Hid | None = None
    expected_on: date | None = None
    notes: LongText | None = None


class PurchaseRequestOut(Model):
    """A request to buy, with its lines."""

    hid: str
    reference: str
    requested_on: date | None
    status: PurchaseStatus
    notes: str | None
    lines: list[PurchaseLineOut]
    quantity: int = Field(description="The items of all its lines that are tracked.")
    received_quantity: int
    pending_quantity: int
    row_version: int
    created_at: datetime
    updated_at: datetime


class PurchaseRequestCreate(Model):
    """A new purchase request, with its lines if they are known."""

    reference: ShortText = Field(min_length=1)
    requested_on: date | None = None
    status: PurchaseStatus = "pending"
    notes: LongText | None = None
    lines: list[PurchaseLineAdd] = Field(default=[], max_length=purchases.MAX_LINES)


class PurchaseRequestPatch(Model):
    """Fields of a purchase request to change, and the version they were read at."""

    row_version: int
    reference: ShortText | None = None
    requested_on: date | None = None
    status: PurchaseStatus | None = None
    notes: LongText | None = None


class Arrived(Model):
    """One item that arrived on a line: something to know it by."""

    serial_number: ShortText | None = None
    asset_tag: ShortText | None = None
    name: Name | None = None
    hostname: HostName | None = None
    mac_address: str | None = Field(default=None, max_length=40)
    comments: LongText | None = None


class Receive(Model):
    """The items that arrived on a line, and when and where."""

    row_version: int
    items: list[Arrived] = Field(
        default=[],
        max_length=settings.MOST_ITEMS_PER_REQUEST,
        description=(
            "With `quantity`, at most as many as the setting `max_items_per_request` says."
        ),
    )
    quantity: int = Field(
        default=0,
        ge=0,
        le=settings.MOST_ITEMS_PER_REQUEST,
        description="How many more arrived that nothing is known of yet, each named for its line.",
    )
    delivered_on: date | None = Field(default=None, description="Left out, today.")
    location_hid: Hid | None = Field(default=None, description="Where they were put.")


# --- external systems ----------------------------------------------------------------

SystemKind = Annotated[
    str,
    Field(
        max_length=40,
        description="A value of the system_kind list, which GET /choices?list=system_kind gives.",
    ),
]


class ExternalSystemOut(Model):
    """Another system that knows items or groups."""

    hid: str
    name: str
    kind: SystemKind
    url: str | None
    notes: str | None
    record_status: RecordStatus
    registrations: int = Field(
        description="How many records are registered with it, those removed not counted."
    )
    row_version: int
    created_at: datetime
    updated_at: datetime


class ExternalSystemCreate(Model):
    """A new external system."""

    name: Name = Field(min_length=1)
    kind: SystemKind | None = Field(
        default=None, description="Left out, other, where the list offers other."
    )
    url: Url | None = None
    notes: LongText | None = None
    record_status: Literal["draft", "active"] = "active"


class ExternalSystemPatch(Model):
    """Fields of an external system to change, and the version they were read at."""

    row_version: int
    name: Name | None = None
    kind: SystemKind | None = None
    url: Url | None = None
    notes: LongText | None = None
    record_status: Literal["draft", "active"] | None = None


class RegistrationOut(Model):
    """An item or a device group as one external system knows it."""

    hid: str
    system_hid: str
    system: SystemRef
    item_hid: str | None
    item: ItemRef | None
    group_hid: str | None
    group: DeviceGroupRef | None
    external_id: str | None
    status: RegistrationStatus
    confirmed_at: datetime | None
    row_version: int
    created_at: datetime
    updated_at: datetime


class RegistrationCreate(Model):
    """A new registration: of one item, or of one device group."""

    system_hid: Hid
    item_hid: Hid | None = None
    group_hid: Hid | None = None
    external_id: Name | None = None
    status: RegistrationStatus = "registered"
    confirmed_at: datetime | None = Field(
        default=None, description="With no zone, in the application's time zone."
    )


class RegistrationPatch(Model):
    """Fields of a registration to change, and the version they were read at."""

    row_version: int
    external_id: Name | None = None
    status: RegistrationStatus | None = None
    confirmed_at: datetime | None = None


# --- capacity ------------------------------------------------------------------------

Units = Annotated[
    Decimal,
    PlainSerializer(_plain, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": r"^-?\d+(\.\d{1,4})?$", "examples": ["1.5"]}),
]
Side = Literal["supply", "demand"]


Effect = Literal["add", "multiply"]
Share = Annotated[
    Decimal,
    Field(ge=0, le=1, max_digits=3, decimal_places=2),
    PlainSerializer(_plain, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": r"^[01](\.\d{1,2})?$", "examples": ["0.5"]}),
]


class CapacityLineRef(Model):
    """A capacity line, as named on another: a staff line that one which multiplies
    works on."""

    hid: str
    name: str


class CapacityLineOut(Model):
    """A source of resource units, or a call on them other than the infrastructure."""

    hid: str
    side: Side
    category: str
    category_label: str
    name: str
    effect: Effect = Field(
        description="`add` a fixed amount, or `multiply` the staff lines of `applies_to`."
    )
    quantity: Weight | None = Field(description="Blank on a line that multiplies.")
    units_each: Weight | None = Field(description="Blank on a line that multiplies.")
    units: Units | None = Field(
        description=(
            "`quantity` times `units_each`. Blank on a line that multiplies, whose units "
            "are those of the lines it applies to in each view: see `GET /reports/capacity`."
        )
    )
    factor: Weight | None = Field(
        description="A line that multiplies: how much more one person does with it."
    )
    share: Share | None = Field(
        description="A line that multiplies: the share of the positions that use it."
    )
    applies_to: list[CapacityLineRef] = Field(
        description="A line that multiplies: the staff lines it works on, by name."
    )
    annual_cost: Money | None
    vendor_hid: str | None
    vendor: VendorRef | None
    region_hid: str | None
    region: PlaceRef | None
    site_hid: str | None
    site: PlaceRef | None
    starts_on: date | None
    ends_on: date | None
    in_date: bool = Field(description="It counts today: not before it starts, not after it ends.")
    notes: str | None
    record_status: RecordStatus
    row_version: int
    created_at: datetime
    updated_at: datetime


class CapacityLineCreate(Model):
    """A new capacity line."""

    side: Side
    category: str | None = Field(
        default=None,
        max_length=40,
        description="A value of the capacity_category list. Left out on a demand line.",
    )
    name: Name = Field(min_length=1)
    effect: Effect = Field(
        default="add",
        description="`multiply` only for a supply line of the category tools or services.",
    )
    quantity: Weight | None = Field(
        default=None, description="Left out, 1 on a line that adds. Blank on one that multiplies."
    )
    units_each: Weight | None = Field(
        default=None, description="Required on a line that adds. Blank on one that multiplies."
    )
    factor: Weight | None = Field(
        default=None, description="At least 1, on a line that multiplies."
    )
    share: Share | None = Field(default=None, description="Left out, 1 on a line that multiplies.")
    applies_to: list[Hid] = Field(
        default=[],
        max_length=100,
        description="The staff lines that a line that multiplies works on: at least one.",
    )
    annual_cost: Money | None = None
    vendor_hid: Hid | None = None
    region_hid: Hid | None = None
    site_hid: Hid | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    notes: LongText | None = None
    record_status: Literal["draft", "active"] = "active"


class CapacityLinePatch(Model):
    """Fields of a capacity line to change, and the version they were read at."""

    row_version: int
    category: str | None = Field(default=None, max_length=40)
    name: Name | None = None
    effect: Effect | None = None
    quantity: Weight | None = None
    units_each: Weight | None = None
    factor: Weight | None = None
    share: Share | None = None
    applies_to: list[Hid] | None = Field(default=None, max_length=100, description="Changed whole.")
    annual_cost: Money | None = None
    vendor_hid: Hid | None = None
    region_hid: Hid | None = None
    site_hid: Hid | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    notes: LongText | None = None
    record_status: Literal["draft", "active"] | None = None


class CapacityCategory(Model):
    """The supply of one category."""

    category: str
    label: str
    lines: int
    units: Units
    annual_cost: MoneySum


class CapacityTarget(Model):
    """A staff line that a line which multiplies works on, as the view counts it."""

    hid: str
    name: str
    counted: bool = Field(
        description="It counts in this view: active, or a draft with the drafts, and in date."
    )
    units: Units = Field(description="Its units in this view, nothing when it is not counted.")


class MultiplyingLine(Model):
    """A line that multiplies, the staff lines it works on, and what it adds to them."""

    hid: str
    name: str
    category: str
    factor: Weight
    share: Share
    applies_to: list[CapacityTarget]
    base_units: Units = Field(description="The units of the lines it works on that count.")
    units: Units = Field(
        description="`factor` less 1, times `share`, times `base_units`: its gain."
    )


class RegionDemand(Model):
    """Where the work is: the support weight at or beneath one region, or of the items
    that are nowhere."""

    region_hid: str | None = Field(description="Blank for the items that are nowhere.")
    parent_region_hid: str | None = Field(description="Blank for a region at the top.")
    path: str | None
    support_weight: WeightSum
    infrastructure_demand: Units
    share_pct: Units | None = Field(
        description="Its share of the whole support weight. Blank when there is none."
    )


class WeightCounts(Model):
    """How many items, sites and circuits of a view (P-155)."""

    items: int
    sites: int
    circuits: int


class CapacityView(Model):
    """The balance of one view."""

    support_weight: WeightSum = Field(
        description="That of the items, the places and the circuits together."
    )
    items_weight: WeightSum = Field(description="The support weight of the major items.")
    places_weight: WeightSum = Field(
        description="The weights in force of the regions, sites and locations that count."
    )
    circuits_weight: WeightSum = Field(
        description="The weights in force of the circuits that carry their weight."
    )
    defaulted: WeightCounts = Field(
        description="How many items, sites and circuits counted at the default of their kind."
    )
    raised: WeightCounts = Field(
        description="How many items, sites and circuits were raised to the minimum of their kind."
    )
    infrastructure_demand: Units
    other_demand: Units
    demand: Units
    supply: Units
    balance: Units = Field(description="Supply less demand.")
    coverage_pct: Units | None = Field(description="Supply over demand. Blank with no demand.")
    own_units: Units = Field(description="The supply that is the team's own positions.")
    outside_units: Units
    own_share_pct: Units | None
    annual_cost: MoneySum = Field(description="What the supply lines cost a year.")
    by_category: list[CapacityCategory]
    multiplying_lines: list[MultiplyingLine] = Field(
        description="The lines that multiply and count in this view, by name."
    )
    demand_by_region: list[RegionDemand] = Field(
        description=(
            "Each region that holds an item, a place or a circuit that weighs in the view, "
            "by path, with what is beneath it, and last the items that are nowhere. No "
            "supply is divided among regions."
        )
    )


class CapacityOut(Model):
    """Demand against supply for the whole installation, with and without the drafts."""

    as_of: date
    weight_per_resource_unit: Units
    active: CapacityView
    with_drafts: CapacityView


class CapacityRecordView(Model):
    """The balance of one view as a record of a week keeps it."""

    support_weight: WeightSum
    items_weight: WeightSum | None = Field(
        description="The parts of the support weight: blank in a week recorded before 0.8.0."
    )
    places_weight: WeightSum | None
    circuits_weight: WeightSum | None
    defaulted: WeightCounts | None = Field(
        description="As the report answered them: blank in a week recorded before 0.8.0."
    )
    raised: WeightCounts | None
    infrastructure_demand: Units
    other_demand: Units
    demand: Units
    supply: Units
    balance: Units = Field(description="Supply less demand, worked out when it is read.")
    coverage_pct: Units | None = Field(
        description="Supply over demand, worked out when it is read. Blank with no demand."
    )
    own_units: Units
    outside_units: Units
    by_category: list[CapacityCategory]


class CapacityRecordOut(Model):
    """The capacity balance as it was in a week, kept to show the trend."""

    hid: str
    week_of: date = Field(description="The Monday that begins the week, in the time zone.")
    recorded_at: datetime
    weight_per_resource_unit: Units
    active: CapacityRecordView
    with_drafts: CapacityRecordView
    adjusted: bool = Field(description="A person has corrected the figures.")
    note: str | None
    row_version: int
    created_at: datetime
    updated_at: datetime


class CapacityRecordCreate(Model):
    """A record of the balance as it is now, which replaces the record of this week."""

    note: LongText | None = None


class CapacityFigures(Model):
    """The two figures of one view of a record that a person may correct."""

    demand: Units | None = None
    supply: Units | None = None


class CapacityRecordPatch(Model):
    """A correction of a saved week, with why, and the version it was read at."""

    row_version: int
    note: LongText = Field(min_length=1, description="Why the figures are corrected.")
    active: CapacityFigures | None = None
    with_drafts: CapacityFigures | None = None


# --- Try, the what-if of the capacity report (P-156) ---

# A figure to try, which the setting of the same name checks as it would check a change.
Tried = Annotated[
    Decimal,
    WithJsonSchema({"type": "string", "pattern": r"^-?\d+(\.\d+)?$", "examples": ["1.5"]}),
]


class StaffAdd(Model):
    """A staff line to try that is not there: it adds, and is active and in date."""

    name: Name = Field(min_length=1)
    quantity: Weight = Field(default=Decimal(1), description="Left out, 1.")
    units_each: Weight


class StaffChange(Model):
    """A staff line that adds and is there, tried with another quantity or units of one,
    and active and in date."""

    hid: Hid
    quantity: Weight | None = Field(default=None, description="Left out, as it is.")
    units_each: Weight | None = Field(default=None, description="Left out, as it is.")


class StaffTry(Model):
    """The staff lines to try: added, changed, and left out."""

    add: list[StaffAdd] = Field(default=[], max_length=1000)
    change: list[StaffChange] = Field(default=[], max_length=1000)
    leave_out: list[Hid] = Field(
        default=[], max_length=1000, description="Staff lines that are there, by HID."
    )


class CapacityTry(Model):
    """What a Try of the capacity report tries. A key left out is as it is in force, and
    null tries a setting at its default, which for a weight is blank."""

    default_item_weight: Tried | None = None
    minimum_item_weight: Tried | None = None
    default_site_weight: Tried | None = None
    minimum_site_weight: Tried | None = None
    default_circuit_weight: Tried | None = None
    minimum_circuit_weight: Tried | None = None
    weight_per_resource_unit: Tried | None = None
    stack_discount_pct: Tried | None = Field(
        default=None, description="The global discount: a model that sets its own keeps it."
    )
    staff: StaffTry = Field(default_factory=StaffTry)


class StaffLineTried(Model):
    """A staff line as it was tried: added, with no HID, or changed."""

    hid: str | None = Field(description="Blank for a line that is added.")
    name: str
    quantity: Weight
    units_each: Weight
    units: Units


class StaffLineLeftOut(Model):
    """A staff line that was left out."""

    hid: str
    name: str


class StaffTried(Model):
    """The staff lines as they were tried."""

    add: list[StaffLineTried]
    change: list[StaffLineTried]
    leave_out: list[StaffLineLeftOut]


class CapacityTried(Model):
    """What was tried: each figure as the balance tried was worked out with it, and the
    staff lines."""

    default_item_weight: Weight | None
    minimum_item_weight: Weight | None
    default_site_weight: Weight | None
    minimum_site_weight: Weight | None
    default_circuit_weight: Weight | None
    minimum_circuit_weight: Weight | None
    weight_per_resource_unit: Units
    stack_discount_pct: Percent
    staff: StaffTried
    changed: list[str] = Field(
        description=(
            "The settings whose value tried is not the one in force: those an Admin who "
            "agrees the estimate saves, each by `PUT /settings/{key}`."
        )
    )


class CapacityTryOut(Model):
    """The capacity balance in force beside the balance tried. Nothing was saved."""

    in_force: CapacityOut = Field(description="As `GET /reports/capacity` answers it.")
    tried: CapacityOut = Field(description="As the figures and the staff lines tried give it.")
    parameters: CapacityTried


# --- end of Try ---


# --- the reports that look ahead -----------------------------------------------------

CoverageSection = Literal[
    "uncovered", "out_of_service", "expiring", "overlapping", "renewal_pending", "not_renewed"
]
EndOfLifeSection = Literal["past", "approaching"]
EndOfLifeDate = Literal["end_of_sale", "end_of_sw_support", "end_of_hw_support", "ldos"]


class ReportSection(Model):
    """One list of a report: how many items, and what lists them on the item list."""

    count: int
    filter: dict[str, Any] | None = Field(description="The filter of `GET /items` for them.")
    include_archived: bool = Field(description="As it is to be sent with that filter.")
    include_drafts: bool


class CoverageTotals(Model):
    """The counts of the coverage report."""

    in_service: int = Field(description="Major items whose state in force is a service state.")
    covered: int
    uncovered: int = Field(
        description="In service, under no contract, and not flagged as not to be renewed."
    )
    out_of_service: int = Field(
        description="Out of service, and a contract still counts it: the list for the vendor."
    )
    expiring: int = Field(
        description=(
            "In service, the cover runs out within the days, and not flagged as not to be renewed."
        )
    )
    overlapping: int = Field(description="Items that more than one contract covers today.")
    renewal_pending: int = Field(
        description="Items covered by a contract whose renewal is pending."
    )
    not_renewed: int = Field(
        description=(
            "In service, under no contract, and flagged as not to be renewed: left out of "
            "support on purpose, and no gap."
        )
    )


class NotRenewedModel(Model):
    """The items of one model that are not to be renewed and that no contract covers."""

    catalog_entry_hid: str | None = Field(description="Blank for the items that have no model.")
    vendor_hid: str | None
    vendor: str | None
    pid: str | None
    model_name: str | None
    count: int
    filter: dict[str, Any] | None = Field(description="The filter of `GET /items` for them.")


class CoverageReportSection(ReportSection):
    """One list of the coverage report."""

    by_model: list[NotRenewedModel] | None = Field(
        default=None,
        description="Of `not_renewed` alone: its items counted by model, by vendor and PID.",
    )


class LapsedContracts(Model):
    """The contracts whose period has ended while they still say they are active."""

    count: int
    filter: dict[str, Any] | None = Field(
        description=(
            "The filter of `GET /contracts` for them; blank where the report's filter "
            "leads to more of them than a filter can name."
        )
    )


class CoverageReport(Model):
    """What contracts cover, of a view of the items, today."""

    as_of: date
    within_days: int
    service_states: list[str]
    totals: CoverageTotals
    sections: dict[str, CoverageReportSection]
    lapsed_contracts: LapsedContracts
    section: CoverageSection | None
    items: list[ItemOut]
    total: int
    limit: int
    offset: int


# --- the renewal worklist and the alert (D-178, D-179) --------------------------------

RenewalSection = Literal[
    "ending", "lapsed", "renewal_pending", "overdue", "ends_with_term", "to_review", "overlapping"
]


class RenewalTotals(Model):
    """The counts of the renewal worklist."""

    ending: int = Field(
        description="Contracts that cover and end within the days, with no renewal entered."
    )
    lapsed: int = Field(description="Contracts whose period has ended while they still say active.")
    renewal_pending: int = Field(description="Contracts whose renewal is pending.")
    overdue: int = Field(
        description="Of those, the ones pending for longer than `renewal_pending_overdue_days`."
    )
    ends_with_term: int = Field(
        description=(
            "Contracts the team marked not to renew that end within the days or have ended, "
            "until a person says they have expired: never alerted."
        )
    )
    to_review: int = Field(
        description=(
            "Members of an agreement that was renewed that still say their renewal is "
            "pending or that they have expired: no renewal of an agreement changes them."
        )
    )
    overlapping: int = Field(description="Items that more than one contract covers today.")


class AgreementTotals(Model):
    """The agreements on the lists of the worklist: renewing one renews its members."""

    ending: int
    lapsed: int
    renewal_pending: int


class RenewalGroup(Model):
    """One vendor and one agreement of the worklist, or the contracts of a vendor that
    stand by themselves, with the count of each list and the filter that lists it."""

    vendor_hid: str
    vendor: str
    agreement_hid: str | None
    agreement: str | None = Field(description="Blank for contracts that stand by themselves.")
    counts: RenewalTotals
    filters: dict[str, dict[str, Any] | None] = Field(
        description=(
            "For each list, the filter of `GET /contracts`, or of `GET /items` for "
            "`overlapping`, that lists its rows."
        )
    )


class RenewalsReport(Model):
    """What a person must act on to keep the cover going: the renewal worklist."""

    as_of: date
    within_days: int
    overdue_after: int = Field(description="The `renewal_pending_overdue_days` setting.")
    totals: RenewalTotals
    sections: dict[str, ReportSection] = Field(
        description=(
            "Each list with its filter: of `GET /contracts`, and of `GET /items` for `overlapping`."
        )
    )
    agreements: dict[str, ReportSection] = Field(
        description="The agreements on each list, with the filter of `GET /agreements`."
    )
    groups: list[RenewalGroup]
    section: RenewalSection | None
    contracts: list[ContractOut] = Field(description="A page of a list of contracts.")
    items: list[ItemOut] = Field(description="A page of `overlapping`.")
    total: int
    limit: int
    offset: int


class AlertCount(Model):
    """One count of the alert, and the list of the worklist it leads to."""

    count: int
    new: int = Field(description="How many of them were not on the list when last seen.")
    section: RenewalSection


class RenewalAlert(Model):
    """The renewal alert, as the person signed in is to be shown it."""

    as_of: date
    within_days: int
    overdue_after: int
    show: bool = Field(
        description=(
            "Whether to show it: for the Inventory and the Admin role, when a count is more "
            "than none and they have not dismissed it yet today, in the application's time "
            "zone."
        )
    )
    version: str = Field(description="What `POST /renewals/alert/seen` may be sent with.")
    lapsed: AlertCount
    renewal_pending: AlertCount
    overdue: int = Field(description="Of those pending, how many are overdue.")
    ending: AlertCount
    agreements: dict[str, int] = Field(
        description="How many agreements have lapsed, have a renewal pending and end soon."
    )


class AlertSeen(Model):
    """That the alert has been seen today."""

    version: str | None = Field(
        default=None, max_length=64, description="The version that was shown. Not required."
    )


class AlertSeenOut(Model):
    """What is kept of the alert a person has seen."""

    as_of: date
    seen_at: datetime


class ItemsCounted(Model):
    """Items, and the components among them."""

    items: int
    component_count: int


class PastAndApproaching(Model):
    """What is past a date, and what approaches it."""

    past: ItemsCounted
    approaching: ItemsCounted


class FiscalYearCount(ItemsCounted):
    """The items whose date falls in one fiscal year."""

    fiscal_year: int = Field(description="Named for the calendar year it ends in.")
    starts_on: date
    ends_on: date


class EndOfLifeReport(Model):
    """The items of a view that are past, or near, an end-of-life date."""

    as_of: date
    within_days: int
    date: EndOfLifeDate
    dates: dict[str, PastAndApproaching]
    by_fiscal_year: list[FiscalYearCount]
    sections: dict[str, ReportSection]
    section: EndOfLifeSection | None
    items: list[ItemOut]
    total: int
    limit: int
    offset: int


class ReplacementRow(Model):
    """One replacement, as a row of the report."""

    hid: str
    old_item_hid: str
    old_item: ItemRef
    new_item_hid: str
    new_item: ItemRef
    reason: str
    reason_label: str
    reference: str | None
    replaced_on: date
    row_version: int
    created_at: datetime


class ReasonCount(Model):
    """How many replacements were made for one reason."""

    reason: str
    label: str
    count: int


class ReplacementsReport(Model):
    """A page of the replacements, and the count of each reason among all that match."""

    items: list[ReplacementRow]
    total: int
    limit: int
    offset: int
    by_reason: list[ReasonCount]


class PortfolioMeasures(Model):
    """What a vendor's items come to."""

    items: int
    component_count: int
    support_weight: WeightSum
    est_value: MoneySum
    annual_support_cost: MoneySum
    covered: int = Field(description="Major items that a contract covers today.")
    uncovered: int = Field(description="Major items that no contract covers today.")


class PortfolioKind(PortfolioMeasures):
    """The items of one kind."""

    kind: str


class PortfolioModel(PortfolioMeasures):
    """The items of one model, with the model's dates."""

    catalog_entry_hid: str
    pid: str
    model_name: str | None
    kind: str
    type: str | None
    function: str | None
    end_of_sale: date | None
    end_of_sw_support: date | None
    end_of_hw_support: date | None
    ldos: date | None
    covered_until: date | None = Field(
        description="The soonest day the cover of one of its covered items runs out."
    )


class PortfolioOut(Model):
    """Everything from one vendor, in one place."""

    vendor: VendorRef
    as_of: date
    totals: PortfolioMeasures
    kinds: list[PortfolioKind]
    models: list[PortfolioModel]
    agreements: list[AgreementOut]
    contracts: list[ContractOut]
    capacity_lines: list[CapacityLineOut]
    filter: dict[str, Any] = Field(description="The filter of `GET /items` for its items.")


# --- reports -------------------------------------------------------------------------

SummaryBy = Literal[
    "vendor",
    "kind",
    "type",
    "function",
    "owner",
    "operator",
    "site",
    "region",
    "contract",
    "group",
    "model",
    "lifecycle_state",
    "disposition",
    "condition",
    "health",
    "tag",
]
ManagementBy = Literal[
    "vendor",
    "kind",
    "type",
    "function",
    "owner",
    "operator",
    "site",
    "region",
    "contract",
    "group",
    "model",
    "tag",
]


ItemsFilter = Annotated[
    str | None,
    Field(
        description=(
            "The filter of `GET /items` that keeps exactly the items `items` counts, within "
            "the view asked for, to be sent with its `include_archived` and "
            "`include_drafts` and with the minor items asked for (P-206): the short form "
            "where it can say it, and otherwise the filter tree as JSON, as `filter=` takes "
            "either. Blank for every item. Null where it, with a condition of `conditions` "
            "joined to it, would hold more conditions or nest deeper than a filter may."
        )
    ),
]


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
    filter: ItemsFilter


class Measures(Model):
    """What the summary counts of a set of items. It holds no money."""

    items: int = Field(description="Every item of the set, major and minor.")
    component_count: int
    managed_node_count: int
    support_weight: WeightSum
    by_health: HealthCount
    filter: ItemsFilter


class HealthConditions(Model):
    """What a count of each health adds to a filter of the answer: its components of that health."""

    good: str
    degraded: str
    failed: str
    unknown: str


class CountConditions(Model):
    """What each count adds to a `filter` of the answer, joined to it by AND, to keep
    exactly what it counts (P-206). Each is a filter of `GET /items`, written as a
    `filter` of the answer is."""

    component_count: str = Field(
        description="The components among the items, as `component_count` counts them."
    )
    component_count_by_kind: str = Field(
        description=(
            "For an entry of `by_kind`: the major items in hand, of whatever kind, as its "
            "`component_count` counts them."
        )
    )
    by_health: HealthConditions = Field(
        description="The components of each health, as `by_health` counts them."
    )


class SummaryTotals(Measures):
    """The measures of the whole view, and its items by condition and by kind."""

    by_condition: list[Counted]
    by_kind: list[Counted]


class RowOperator(Model):
    """An operator in force among the items of one row, and how much of the row it has."""

    hid: str | None = Field(description="Null for what nobody is assigned to.")
    label: str | None
    colour: str | None
    contact: str | None = Field(description="The name of the person behind the label.")
    is_open: bool
    items: int
    component_count: int
    support_weight: WeightSum


class RowRecord(Model):
    """What a row of a report by group, by model or by operator says of the record it is
    of (P-178, P-180). Every field is null on the rows of anything else, and on the blank
    row."""

    type: str | None = Field(
        default=None,
        description="By group, the type of the group; by model, the type of the model.",
    )
    member_count: int | None = Field(default=None, description="By group: its current members.")
    nested_groups: int | None = Field(
        default=None, description="By group: how many groups are nested in it, at any depth."
    )
    vendor: str | None = Field(default=None, description="By model: the name of its vendor.")
    pid: str | None = Field(default=None, description="By model: its PID.")
    model_name: str | None = Field(default=None, description="By model: its name.")
    kind: str | None = Field(default=None, description="By model: its kind.")
    own: int | None = Field(default=None, description="By operator: items given it as their own.")
    from_item: int | None = Field(
        default=None, description="By operator: minor items that have it from the item they are in."
    )
    from_group: int | None = Field(
        default=None, description="By operator: items that have it from a group."
    )
    from_place: int | None = Field(
        default=None, description="By operator: items that have it from a place."
    )
    groups_given: int | None = Field(
        default=None, description="By operator: the groups given it as their own."
    )
    places_given: int | None = Field(
        default=None, description="By operator: the regions, sites and locations given it."
    )


class SummaryRow(Measures, RowRecord):
    """The measures of the items that share one value of what the summary is by."""

    key: str | None = Field(description="The value, or the HID of the record. Null for none.")
    label: str | None = Field(description="What people call it.")
    operators: list[RowOperator] | None = Field(
        description=(
            "With `operators=true`: who looks after the items of the row, the one with "
            "the most first and nobody last. Otherwise null."
        )
    )


class SummaryOut(Model):
    """A summary of a view of the items, for the people who run the network."""

    by: SummaryBy | None
    totals: SummaryTotals
    rows: list[SummaryRow]
    conditions: CountConditions


class ManagementConditions(Model):
    """What a count of components adds to a `filter` of the answer (P-206)."""

    component_count: str = Field(
        description="The components among the items, as `component_count` counts them."
    )


class ManagementMeasures(Model):
    """What the management report counts of a set of items."""

    items: int = Field(description="Every item of the set, major and minor.")
    component_count: int
    est_value: MoneySum
    annual_support_cost: MoneySum
    filter: ItemsFilter


class ManagementRow(ManagementMeasures, RowRecord):
    """The value and the cost of the items that share one value."""

    key: str | None
    label: str | None


class ManagementOut(Model):
    """The value and the cost of a view of the items, for the people who pay for it."""

    by: ManagementBy = Field(description="What the rows are by: the site, unless asked.")
    totals: ManagementMeasures
    rows: list[ManagementRow]
    conditions: ManagementConditions


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
    """A setting: the value in force, its default, what it means and what it takes. Or
    a value that is fixed in the code, with `fixed` true: what it limits and why it is
    fixed, at its default always."""

    key: str
    value: Any
    default: Any
    is_default: bool
    meaning: str = Field(description="What the setting is for, or what a fixed value limits.")
    accepts: str | None = Field(
        default=None, description="The values a setting takes. Blank for a fixed value."
    )
    options: list[str] | None = Field(
        default=None, description="The values to choose from, where a setting is of a list."
    )
    fixed: bool = Field(
        default=False, description="Fixed in the code: listed, and not changed by any request."
    )
    reason: str | None = Field(default=None, description="Why a fixed value is fixed.")
    decision: str | None = Field(
        default=None, description="The decision that fixed it, where one did: `D-142`."
    )
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
    "contacts",
    "vendor_contacts",
    "operators",
    "regions",
    "sites",
    "locations",
    "contact_assignments",
    "owners",
    "owner_members",
    "networks",
    "external_systems",
    "agreements",
    "contracts",
    "contract_contacts",
    "purchase_requests",
    "purchase_lines",
    "items",
    "device_groups",
    "device_group_members",
    "item_replacements",
    "addresses",
    "contract_coverage",
    "registrations",
    "capacity_lines",
    # Circuits and their parts, and circuit groups (P-153).
    "circuit_groups",
    "circuits",
    "circuit_carriers",
    "circuit_costs",
    "circuit_contacts",
    "circuit_devices",
]
Outcome = Literal["create", "update", "unchanged", "rejected"]
# What an apply in the background did with a row (D-185).
AppliedOutcome = Literal["create", "update", "unchanged", "stale", "rejected"]


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
    status: Literal["previewed", "queued", "applying", "applied", "stopped", "failed"] = Field(
        description="`queued` and `applying` while it is applied in the background, "
        "`applied` once every row is worked, `stopped` when it stopped partway, to be "
        "resumed. `failed` is a job of a release before 0.7.0 that was not applied."
    )
    row_count: int
    created: int = Field(description="Rows that create a record, as the preview found.")
    updated: int = Field(description="Rows that change a record, as the preview found.")
    unchanged: int = Field(description="Rows that find their record as the row has it.")
    rejected: int = Field(description="Rows that cannot be applied, as the preview found.")
    rows_done: int = Field(description="How many rows the apply has worked so far.")
    applied: int = Field(description="How many rows the apply applied as they were previewed.")
    stale: int = Field(
        description="How many rows the apply left out because they changed since the preview."
    )
    skip_rejected: bool | None = Field(description="Whether it was applied without them.")
    system_hid: str | None = Field(
        description="An import of items: the external system the file was read from, by "
        "whose identifier, `external_id`, its rows are matched first (P-248)."
    )
    system: SystemRef | None
    complete: bool | None = Field(
        description="With a system: the file is everything that system reports, so that each "
        "item registered with it that no row names is marked `not_reported` once the file is "
        "applied whole."
    )
    not_reported: int = Field(
        description="How many items that marks: as the preview found, and once applied, how "
        "many it marked. None is marked where a row was rejected, left out or stale."
    )
    failure: str | None = Field(
        description="Why a stopped job stopped, or why a failed one was not applied."
    )
    applied_at: datetime | None = Field(description="When it was last asked to be applied.")
    applied_by: str | None = Field(description="Who last asked for it to be applied.")
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
    applied_outcome: AppliedOutcome | None = Field(
        description="What the apply did with the row. Blank until it is worked."
    )
    applied_reasons: list[RowReason] = Field(
        description="Why the apply left a `stale` or `rejected` row out."
    )


class ImportPreview(Model):
    """A preview: the job with its counts, and the first of its rows."""

    job: ImportJobOut
    rows: list[ImportRowOut] = Field(
        description="The first hundred rows. `GET /imports/{hid}/rows` pages through all."
    )
    not_reported_first: list[RecordLabel] = Field(
        description="Of a `complete` import that is not applied yet: the first ten items it "
        "would mark `not_reported`, by label (P-248). Empty otherwise.",
    )


# What a record an import made is now (P-234).
CreatedState = Literal["active", "draft", "retired", "deleted"]


class CreatedRecord(Model):
    """A record that a row of an import made, and what it is now."""

    row: int = Field(description="The row of the file that made it, from 1.")
    record_type: str = Field(description="Its kind, as the audit trail names it: `item`.")
    record_hid: str
    label: str = Field(
        description="What it is known by now, as the routes that retire several give it; "
        "for one that was deleted, what it was known by then."
    )
    state: CreatedState = Field(
        description="A record with no status of its own, such as a tag or a membership, is "
        "`active` while it stands."
    )


class MadeForARow(Model):
    """A vendor or a catalog entry an import made only because a row named it."""

    record_type: Literal["vendor", "catalog_entry"]
    record_hid: str
    label: str = Field(description="A vendor by its name, a catalog entry by vendor and PID.")
    state: CreatedState


class ImportCreated(Model):
    """The records an import made, a page of them, and those it made for a row."""

    total: int
    limit: int
    offset: int
    items: list[CreatedRecord] = Field(description="By row, in the order of the file.")
    also: list[MadeForARow] = Field(
        description="Whole, on every page: the vendors and catalog entries made only "
        "because a row named them, that no row of the import described."
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
    place_codes: bool = Field(
        default=False,
        description="Write each place the short way, by the codes of its site and its own: "
        "`S2 > R102`, with names where a place has no code (P-235).",
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


# --- what an operator is on (P-177) ---------------------------------------------------


class ItemCount(Model):
    """How many items of the view, and the filter of the item list that lists them."""

    count: int
    filter: dict[str, Any]


class PlaceBeneath(Model):
    hid: str
    level: Level
    path: str


class GroupBeneath(Model):
    hid: str
    name: str
    type: GroupType


class PlacesBeneath(Model):
    """The places beneath a place that have the operator from it, at most 20 named."""

    count: int
    more: int = Field(description="How many more there are than are named.")
    shown: list[PlaceBeneath]


class GroupsBeneath(Model):
    """The groups nested in a group that have the operator from it, at most 20 named."""

    count: int
    more: int
    shown: list[GroupBeneath]


class OperatorPlace(Model):
    """A place given the operator as its own."""

    hid: str
    level: Level
    path: str
    items: ItemCount = Field(description="The items that have the operator from this place.")
    places_beneath: PlacesBeneath
    exceptions: ItemCount = Field(description="The items beneath it that have another.")


class OperatorGroup(Model):
    """A device group given the operator as its own."""

    hid: str
    name: str
    type: GroupType
    items: ItemCount = Field(description="The items that have the operator from this group.")
    groups_beneath: GroupsBeneath
    exceptions: ItemCount = Field(description="Its members that have another.")


class OperatorAssignments(Model):
    """What an operator is on, and how: what the page of an operator draws."""

    operator_hid: str
    places: list[OperatorPlace]
    groups: list[OperatorGroup]
    own: ItemCount = Field(description="The items given it as their own.")
    from_item: ItemCount = Field(
        description="The items that have it from an item above them: the one they are "
        "installed in, or the one they run on (P-246)."
    )
    totals: ItemCount = Field(description="Every item it is in force for.")
