"""The records a file can carry: their columns, how a row finds its record, and how a
row is written.

Nothing here decides whether a value is acceptable. A row is written by the same
functions in `domain/` that the routes call, so a file goes through the rules that
every other door goes through. What is here is what belongs to files alone: the names
of the columns, the keys a row is matched by, and references written as people write
them, such as a vendor's name for a vendor.
"""

from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import Any, ClassVar, Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hirdir import ids
from hirdir.auth.roles import Role
from hirdir.db import dialect
from hirdir.db.models import (
    ADDRESS_FIELDS,
    SHIP_FIELDS,
    Address,
    CatalogEntry,
    Contact,
    ContactAssignment,
    DeviceGroup,
    DeviceGroupMember,
    Item,
    Location,
    Network,
    Owner,
    OwnerMember,
    Region,
    Site,
    Tag,
    Vendor,
)
from hirdir.domain import (
    addresses,
    catalog,
    contacts,
    geography,
    groups,
    health,
    inheritance,
    items,
    lifecycle,
    operators,
    owners,
    records,
    settings,
    tags,
)
from hirdir.domain.audit import AuditContext
from hirdir.domain.errors import DomainError, Invalid
from hirdir.domain.lifecycle import UNSET
from hirdir.io import fields
from hirdir.io.columns import Column
from hirdir.io.fields import Listing

_MISSING: Final[Any] = object()
FEW = 2
LONG = 10_000

HID = Column("hid", limit=36, settable=False)
BOOKKEEPING = (
    Column("row_version", "integer", settable=False),
    Column("created_at", "timestamp", settable=False),
    Column("updated_at", "timestamp", settable=False),
)
STATUS = Column("record_status", limit=10)
REVIEW = Column("review_status", limit=12)
TAGS = Column("tags", "list", limit=100)
DATES = tuple(Column(name, "date", inherits=True) for name in catalog.DATES)
AMOUNTS = (
    Column("est_value", "money", inherits=True),
    Column("support_weight", "number", inherits=True),
    Column("annual_support_cost", "money", inherits=True),
)
STREET = tuple(Column(name) for name in ADDRESS_FIELDS)
SHIPPING = (*(Column(name) for name in SHIP_FIELDS), Column("ship_instructions", limit=LONG))
COORDINATES = (Column("latitude", "degrees"), Column("longitude", "degrees"))
SAME_AS_ADDRESS = Column(geography.SAME, "boolean")
CODE = Column("code", limit=40)
NOTES = Column("notes", limit=LONG)
PATH = Column("path", limit=LONG, settable=False)


def _sources(columns: tuple[Column, ...]) -> tuple[Column, ...]:
    return tuple(
        Column(f"{column.name}_source", limit=20, settable=False)
        for column in columns
        if column.inherits
    )


def _by_hid(db: Session, model: Any, hids: set[str | None]) -> dict[str, Any]:
    wanted = {hid for hid in hids if hid}
    if len(wanted) <= FEW:
        # One row of a file refers to one or two records, and the session may well
        # hold them already.
        return {hid: db.get(model, hid) for hid in wanted}
    return {record.hid: record for record in db.scalars(select(model).where(model.hid.in_(wanted)))}


class Run:
    """One pass through the rows of a file: who is importing, and what it has met so far.

    It finds the records that rows refer to, and makes the vendors and catalog entries
    that are missing. What it has learned while working on a row is forgotten again if
    the row is rejected, because a rejected row leaves nothing behind.
    """

    def __init__(self, db: Session, context: AuditContext, role: Role | None, mode: str) -> None:
        self.db = db
        self.context = context
        self.role = role
        self.mode = mode
        # The row that already named each record, by the record's HID.
        self.seen: dict[str, int] = {}
        # Records this run made because a row referred to them and they were not there.
        self.stubs: set[str] = set()
        self.notes: list[str] = []
        self._undo: list[Callable[[], None]] = []
        self._vendors: dict[str, str] = {}
        self._entries: dict[tuple[str, str], str] = {}
        self._owners: dict[str, str] = {}
        # The row being worked, and the rows that named a master of each stack: the
        # one intended, and the one seen. A stack has one of each at most, so a second
        # row that names one says something else than the first, and is refused.
        self.row = 0
        self.masters: dict[tuple[str, str], int] = {}
        # The session lets go of a record that nothing else holds. These are held, so
        # that the vendor of a thousand rows is read once and not a thousand times.
        self._held: dict[str, Any] = {}

    def start_row(self, number: int = 0) -> None:
        """Begin a row: nothing noted yet, nothing to forget."""
        self.row = number
        self.notes = []
        self._undo = []

    def forget_row(self) -> None:
        """Forget what the row taught, because the row was rejected."""
        for step in reversed(self._undo):
            step()
        self._undo = []
        self._held.clear()

    def let_go(self) -> None:
        """Let the session forget the records worked on so far."""
        self.db.flush()
        self.db.expunge_all()
        self._held.clear()

    def _get(self, model: Any, hid: str) -> Any:
        record = self._held.get(hid)
        if record is None:
            record = self.db.get(model, hid)
            self._held[hid] = record
        return record

    def _learn(self, cache: dict[Any, Any], key: Any, value: Any) -> None:
        before = cache.get(key, _MISSING)
        cache[key] = value

        def forget() -> None:
            if before is _MISSING:
                cache.pop(key, None)
            else:
                cache[key] = before

        self._undo.append(forget)

    def _stub(self, hid: str, note: str) -> None:
        self.stubs.add(hid)
        self.notes.append(note)
        self._undo.append(lambda: self.stubs.discard(hid))

    def renamed(self) -> None:
        """A row has changed a vendor or a catalog entry itself: what was looked up
        under their names is looked up afresh."""
        self._vendors.clear()
        self._entries.clear()

    def claim(self, hid: str) -> None:
        """A row describes a record this run made for a reference: it is that row's own."""
        self.stubs.discard(hid)
        self._undo.append(lambda: self.stubs.add(hid))

    def vendor(self, text: str, create: bool = False) -> Vendor | None:
        """Return the vendor a row names, by HID, name or alias. With create, make it."""
        if ids.is_hid(text):
            vendor = self.db.get(Vendor, text)
            if vendor is not None:
                return vendor
        key = records.key(text)
        known = self._vendors.get(key)
        if known is None:
            # Only what was found is remembered. That a vendor is not there is looked
            # up again each time, because a row of the file may have made it since.
            found = catalog.find_vendor(self.db, text)
            if found is not None:
                known = found.hid
                self._learn(self._vendors, key, known)
        if known is not None:
            return self._get(Vendor, known)
        if not create:
            return None
        vendor = catalog.create_vendor(
            self.db, self.context, {"name": text, "review_status": "unreviewed"}
        )
        self._learn(self._vendors, key, vendor.hid)
        self._stub(vendor.hid, f"creates the vendor {vendor.name}, to be reviewed")
        return vendor

    def entry(self, vendor_text: str, pid: str, create: bool = False) -> CatalogEntry | None:
        """Return the catalog entry a row names by vendor and PID. With create, make it."""
        vendor = self.vendor(vendor_text, create)
        if vendor is None:
            return None
        key = (vendor.hid, records.key(pid))
        known = self._entries.get(key)
        if known is None:
            known = self.db.scalar(
                select(CatalogEntry.hid).where(
                    CatalogEntry.vendor_hid == vendor.hid, CatalogEntry.pid_key == key[1]
                )
            )
            if known is not None:
                self._learn(self._entries, key, known)
        if known is not None:
            return self._get(CatalogEntry, known)
        if not create:
            return None
        entry = catalog.create_entry(
            self.db,
            self.context,
            {"vendor_hid": vendor.hid, "pid": pid, "review_status": "unreviewed"},
        )
        self._learn(self._entries, key, entry.hid)
        self._stub(
            entry.hid, f"creates the catalog entry {vendor.name} {entry.pid}, to be reviewed"
        )
        return entry

    def owner(self, text: str) -> Owner:
        """Return the owner a row names, by HID or label. An owner is never made here."""
        if ids.is_hid(text):
            owner = self.db.get(Owner, text)
            if owner is not None:
                return owner
        key = records.key(text)
        known = self._owners.get(key)
        if known is None:
            known = self.db.scalar(select(Owner.hid).where(Owner.label_key == key))
            if known is None:
                raise Invalid("there is no such owner", {"owner": f"there is no owner {text}"})
            self._learn(self._owners, key, known)
        return self._get(Owner, known)

    def item(self, text: str, field: str) -> Item:
        """Return the one item a row names: by HID, serial number, asset tag or name."""
        return items.the_one(self.db, text, field)

    def names_master(self, group_hid: str, which: str, field: str) -> None:
        """Note that this row names a master of a stack, refusing a second that does."""
        before = self.masters.get((group_hid, which))
        if before is not None and before != self.row:
            raise Invalid(
                f"row {before} names the {which} master of this stack",
                {field: f"row {before} of the file names the {which} master of this stack"},
            )
        self._learn(self.masters, (group_hid, which), self.row)

    def place(self, text: str, field: str, level: str | None = None) -> geography.Place:
        """Return the region, site or location a row names, by its HID or its path."""
        return geography.the_place(self.db, text, field, level)

    def contact(self, text: str, field: str = "contact") -> Contact:
        """Return the one contact a row names: by HID, email address or name."""
        return contacts.the_one(self.db, text, field)

    def network(self, text: str, field: str = "network") -> Network:
        """Return the network a row names, by HID or label. A network is never made here."""
        found = addresses.find_network(self.db, text)
        if found is None:
            raise Invalid("there is no such network", {field: f"there is no network {text}"})
        return found

    def group(self, text: str, field: str = "group") -> DeviceGroup:
        """Return the device group a row names, by HID or name."""
        found = self.db.get(DeviceGroup, text) if ids.is_hid(text) else None
        found = found or groups.find_group(self.db, text)
        if found is None:
            raise Invalid("there is no such group", {field: f"there is no device group {text}"})
        return found


# The columns that set a primary management address, and the family each is of: an
# address of either family in `mgmt_address`, which is filed under its own.
MGMT = {"mgmt_ipv4": 4, "mgmt_ipv6": 6, "mgmt_address": None}
# The spellings a site's own file is likely to use for them.
MGMT_SPELLINGS = {
    "ip_address": "mgmt_address",
    "ip": "mgmt_address",
    "mgmt_ip": "mgmt_address",
    "ipv4_address": "mgmt_ipv4",
    "ipv4": "mgmt_ipv4",
    "ipv6_address": "mgmt_ipv6",
    "ipv6": "mgmt_ipv6",
}


def _management(run: Run, field: str, hid: str, values: Mapping[str, Any]) -> None:
    """Set, change or remove the primary management addresses of an item or a group.

    There is one of each family. `mgmt_ipv4` and `mgmt_ipv6` name theirs, and
    `mgmt_address` takes either and files it under its own; cleared, it removes both.
    """
    named = [name for name in MGMT if name in values]
    if not named:
        if values.get("mgmt_network") is not None:
            raise Invalid(
                "a network is named with its address",
                {"mgmt_network": "give mgmt_address, mgmt_ipv4 or mgmt_ipv6 with it"},
            )
        return
    network: Any = addresses.UNSET
    if "mgmt_network" in values:
        label = values["mgmt_network"]
        network = run.network(label, "mgmt_network").hid if label is not None else None

    def stored(name: str) -> str | None:
        given = values[name]
        try:
            return addresses.canonical(given) if given is not None else None
        except ValueError as error:
            raise Invalid("the address is not acceptable", {name: str(error)}) from None

    # What each family is to have: an address, or nothing. The columns that name a
    # family are read first, and `mgmt_address` then fills in what they leave open.
    wanted: dict[int, str | None] = {}
    for name, which in (("mgmt_ipv4", 4), ("mgmt_ipv6", 6)):
        if name not in values:
            continue
        address = stored(name)
        if address is not None and addresses.family(address) != which:
            raise Invalid(
                "the address is of the other family",
                {name: f"an IPv{which} address; this one is IPv{addresses.family(address)}"},
            )
        wanted[which] = address
    if "mgmt_address" in values:
        address = stored("mgmt_address")
        if address is None:
            wanted.setdefault(4, None)
            wanted.setdefault(6, None)
        else:
            which = addresses.family(address)
            if wanted.get(which, address) != address:
                raise Invalid(
                    "two columns name the management address",
                    {"mgmt_address": f"mgmt_ipv{which} names another IPv{which} address"},
                )
            wanted[which] = address
    for which, address in sorted(wanted.items()):
        addresses.set_primary(run.db, run.context, field, hid, address, network, which)


def _primaries(db: Session, field: str, hids: list[str]) -> dict[str, dict[str, str | None]]:
    """Return the management columns of each record: its primary address of each family,
    either of them as `mgmt_address`, and the label of the network it is under."""
    found = addresses.of_holders(db, field, hids)
    networks = _by_hid(
        db, Network, {address.network_hid for listed in found.values() for address in listed}
    )
    columns: dict[str, dict[str, str | None]] = {}
    for hid, listed in found.items():
        primary = {addresses.family(one.address): one for one in listed if one.is_primary}
        first = primary.get(4) or primary.get(6)
        # One column names the network of both. Where the two are under different
        # networks it says nothing, and a file that is loaded back leaves each where
        # it is: the file of addresses holds every address with its own network.
        under = {one.network_hid for one in primary.values()}
        shared = next(iter(under)) if len(under) == 1 else None
        columns[hid] = {
            "mgmt_address": first.address if first else None,
            "mgmt_ipv4": primary[4].address if 4 in primary else None,
            "mgmt_ipv6": primary[6].address if 6 in primary else None,
            "mgmt_network": networks[shared].label if shared else None,
        }
    return columns


NO_MGMT: Mapping[str, str | None] = dict.fromkeys((*MGMT, "mgmt_network"))
MANAGEMENT = (
    # Every address is in a file of its own, so an export writes these when asked.
    Column("mgmt_address", limit=45, listed=False),
    Column("mgmt_ipv4", limit=45, listed=False),
    Column("mgmt_ipv6", limit=45, listed=False),
    Column("mgmt_network", limit=100, listed=False),
)
OBSERVATION = (Column("observed_status", limit=12), Column("observed_at", "timestamp"))


def _status(values: Mapping[str, Any], record: Any) -> dict[str, Any]:
    """Return the record status a row sets. An import does not retire."""
    if "record_status" not in values:
        return {}
    wanted = values["record_status"]
    if wanted is not None and records.key(wanted) == "retired":
        if record is not None and record.record_status == "retired":
            return {}
        raise Invalid(
            "an import does not retire",
            {"record_status": "retire the record on its own page; a file does not retire"},
        )
    return {"record_status": wanted}


def _plain_fields(values: Mapping[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    return {name: values[name] for name in names if name in values}


def _new(given: dict[str, Any]) -> dict[str, Any]:
    """Return the fields of a new record: one that is cleared is simply not given."""
    return {name: value for name, value in given.items() if value is not None}


class Entity:
    """One kind of record that a file can carry."""

    name: ClassVar[str]
    record_type: ClassVar[str]
    model: ClassVar[Any]
    listing: ClassVar[Listing]
    columns: ClassVar[tuple[Column, ...]]
    # The names a filter has for the same columns.
    aliases: ClassVar[Mapping[str, str]] = {}
    # The column a row reads for a field the rules name otherwise.
    renamed: ClassVar[Mapping[str, str]] = {}
    # The columns a bulk edit may not set: they tell one record from another.
    not_in_bulk: ClassVar[frozenset[str]] = frozenset()
    # The columns that the clock sets when a row gives them no moment. A preview and
    # its apply are made at different moments, so what a row is said to do leaves such
    # a column out unless the row itself says when.
    by_the_clock: ClassVar[frozenset[str]] = frozenset()
    # The columns that say again what other columns say, and are never told as
    # changed: `mgmt_address` is the management address of one family or the other,
    # and each of those has a column of its own, which is the one that is told.
    restated: ClassVar[frozenset[str]] = frozenset()

    def column(self, name: str) -> Column | None:
        """Return the column with a name, as a file or as a filter names it."""
        wanted = records.key(name)
        wanted = self.aliases.get(wanted, wanted)
        for column in self.columns:
            if column.name == wanted:
                return column
        return None

    @property
    def settable(self) -> tuple[Column, ...]:
        """The columns an import may set, in the order an export writes them."""
        return tuple(column for column in self.columns if column.settable)

    def find(self, run: Run, values: Mapping[str, Any]) -> Any | None:
        """Return the record a row with no HID names, or None when it names a new one."""
        raise NotImplementedError

    def key(self, values: Mapping[str, Any], record: Any | None) -> str:
        """Return how a row names its record, for a person to read."""
        raise NotImplementedError

    def write(self, run: Run, record: Any | None, values: Mapping[str, Any], new: bool) -> Any:
        """Create the record of a row, or change the one it matched. Return it.

        `new` says the record did not exist before this file, also when an earlier row
        made it for a reference and `record` is therefore given.
        """
        raise NotImplementedError

    def read(self, db: Session, found: list[Any], own: bool = True) -> list[dict[str, Any]]:
        """Return the columns of each record, typed. With own, stored values and not
        the ones in force."""
        raise NotImplementedError

    def order(self, run: Run, rows: Sequence[Mapping[str, Any]]) -> list[int]:
        """Return the numbers of the rows, from 1, in the order they are to be worked.

        That is the order of the file, unless a row leans on what another row of the
        same file does to a record above it.
        """
        return list(range(1, len(rows) + 1))

    def finish(self, run: Run) -> dict[int, list[dict[str, str]]]:
        """Return the rows that cannot stand once the whole file is worked, with why.

        Most records are right or wrong a row at a time. The members of a stack are
        right together, so they are checked when all of them are in.
        """
        return {}


def _kept(record: Any) -> dict[str, Any]:
    return {
        "hid": record.hid,
        "row_version": record.row_version,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


class Tags(Entity):
    """Tags."""

    name = "tags"
    record_type = "tag"
    model = Tag
    listing = fields.TAGS
    columns = (
        HID,
        Column("label", limit=100),
        Column("colour", limit=20),
        Column("description", limit=LONG),
        *BOOKKEEPING,
    )

    def find(self, run: Run, values: Mapping[str, Any]) -> Any | None:
        label = values.get("label")
        if not label:
            return None
        return run.db.scalar(select(Tag).where(Tag.label_key == records.key(label)))

    def key(self, values: Mapping[str, Any], record: Any | None) -> str:
        return values.get("label") or (record.label if record is not None else "")

    def write(self, run: Run, record: Any | None, values: Mapping[str, Any], new: bool) -> Any:
        given = _plain_fields(values, ("label", "colour", "description"))
        if record is None:
            return tags.create_tag(run.db, run.context, _new(given))
        return tags.update_tag(run.db, run.context, record.hid, record.row_version, given)

    def read(self, db: Session, found: list[Any], own: bool = True) -> list[dict[str, Any]]:
        return [
            {
                **_kept(tag),
                "label": tag.label,
                "colour": tag.colour,
                "description": tag.description,
            }
            for tag in found
        ]


class Vendors(Entity):
    """Vendors."""

    name = "vendors"
    record_type = "vendor"
    model = Vendor
    listing = fields.VENDORS
    columns = (
        HID,
        Column("name"),
        Column("aliases", "list"),
        Column("notes", limit=LONG),
        REVIEW,
        *BOOKKEEPING,
    )

    def find(self, run: Run, values: Mapping[str, Any]) -> Any | None:
        name = values.get("name")
        return run.vendor(name) if name else None

    def key(self, values: Mapping[str, Any], record: Any | None) -> str:
        return values.get("name") or (record.name if record is not None else "")

    def write(self, run: Run, record: Any | None, values: Mapping[str, Any], new: bool) -> Any:
        given = _plain_fields(values, ("name", "aliases", "notes", "review_status"))
        if given.get("aliases", _MISSING) is None:
            given["aliases"] = []
        run.renamed()
        if record is None:
            return catalog.create_vendor(run.db, run.context, _new(given))
        if not values.get("hid") and "name" in given:
            # Found by its name or by an alias. A row that calls a vendor by another of
            # its spellings does not rename it.
            del given["name"]
        return catalog.update_vendor(run.db, run.context, record.hid, record.row_version, given)

    def read(self, db: Session, found: list[Any], own: bool = True) -> list[dict[str, Any]]:
        return [
            {
                **_kept(vendor),
                "name": vendor.name,
                "aliases": list(vendor.aliases),
                "notes": vendor.notes,
                "review_status": vendor.review_status,
            }
            for vendor in found
        ]


class Owners(Entity):
    """Owners."""

    name = "owners"
    record_type = "owner"
    model = Owner
    listing = fields.OWNERS
    columns = (
        HID,
        Column("label"),
        Column("organization"),
        Column("is_external", "boolean"),
        Column("exception_reason", limit=LONG),
        STATUS,
        TAGS,
        *BOOKKEEPING,
    )

    def find(self, run: Run, values: Mapping[str, Any]) -> Any | None:
        label = values.get("label")
        if not label:
            return None
        return run.db.scalar(select(Owner).where(Owner.label_key == records.key(label)))

    def key(self, values: Mapping[str, Any], record: Any | None) -> str:
        return values.get("label") or (record.label if record is not None else "")

    def write(self, run: Run, record: Any | None, values: Mapping[str, Any], new: bool) -> Any:
        given = {
            **_plain_fields(
                values, ("label", "organization", "is_external", "exception_reason", "tags")
            ),
            **_status(values, record),
        }
        if given.get("is_external", _MISSING) is None:
            given["is_external"] = False
        if given.get("tags", _MISSING) is None:
            given["tags"] = []
        if record is None:
            return owners.create_owner(run.db, run.context, _new(given))
        return owners.update_owner(run.db, run.context, record.hid, record.row_version, given)

    def read(self, db: Session, found: list[Any], own: bool = True) -> list[dict[str, Any]]:
        labels = tags.labels_of(db, self.record_type, [owner.hid for owner in found])
        return [
            {
                **_kept(owner),
                "label": owner.label,
                "organization": owner.organization,
                "is_external": owner.is_external,
                "exception_reason": owner.exception_reason,
                "record_status": owner.record_status,
                "tags": labels[owner.hid],
            }
            for owner in found
        ]


def _region_named(atlas: geography.Atlas, hid: str | None) -> str | None:
    """Return how a file names a region: by its path, unless the path has the form of
    an HID and would be read as one. Only a region at the top can be named so."""
    return items.name_or_hid(atlas.region_path(hid), hid) if hid else None


def _in_force_parts(text: Any) -> int:
    """Return how many names a path holds, for working a place before what is in it."""
    return len(text.split(geography.SEPARATOR)) if isinstance(text, str) and text.strip() else 0


class _Places(Entity):
    """What the files of regions, sites and locations share."""

    level: ClassVar[str]
    _fields: ClassVar[tuple[str, ...]]

    def key(self, values: Mapping[str, Any], record: Any | None) -> str:
        named = [values.get(name) for name in ("region", "site", "parent", "name")]
        return geography.JOINED.join(str(part) for part in named if part) or (
            record.name if record is not None else ""
        )

    def _given(self, values: Mapping[str, Any], record: Any | None) -> dict[str, Any]:
        given = {**_plain_fields(values, (*self._fields, "tags")), **_status(values, record)}
        if given.get("tags", _MISSING) is None:
            given["tags"] = []
        if given.get(geography.SAME, _MISSING) is None:
            given[geography.SAME] = False
        return given

    def _store(self, run: Run, record: Any | None, given: dict[str, Any]) -> Any:
        if record is None:
            return geography.create_place(run.db, run.context, self.level, _new(given))
        return geography.update_place(
            run.db, run.context, self.level, record.hid, record.row_version, given
        )

    def _row(self, record: Any, labels: dict[str, list[str]], path: str) -> dict[str, Any]:
        return {
            **_kept(record),
            **{name: getattr(record, name) for name in self._fields},
            "record_status": record.record_status,
            "tags": labels[record.hid],
            "path": path,
        }


class Regions(_Places):
    """Regions."""

    name = "regions"
    record_type = "region"
    level = geography.REGION
    model = Region
    listing = fields.REGIONS
    columns = (
        HID,
        Column("name"),
        Column("parent", limit=LONG),
        CODE,
        *SHIPPING,
        NOTES,
        STATUS,
        TAGS,
        PATH,
        *BOOKKEEPING,
    )
    aliases: ClassVar[Mapping[str, str]] = {
        "parent.name": "parent",
        "parent_region_hid": "parent",
    }
    renamed: ClassVar[Mapping[str, str]] = {"parent_region_hid": "parent"}
    _fields = ("name", "code", *geography.SHIPPING, "notes")

    def find(self, run: Run, values: Mapping[str, Any]) -> Any | None:
        name, parent = values.get("name"), values.get("parent")
        if not name:
            return None
        # Among the regions of the one it is in, and at the top when it is in none: a
        # region of the same name elsewhere is another record.
        within = run.place(parent, "parent", geography.REGION) if parent else None
        found = geography.find_within(run.db, within, name)
        return found.record if found is not None and found.level == geography.REGION else None

    def order(self, run: Run, rows: Sequence[Mapping[str, Any]]) -> list[int]:
        """Work a region before the regions of the same file that are within it."""
        return sorted(
            range(1, len(rows) + 1),
            key=lambda number: (_in_force_parts(rows[number - 1].get("parent")), number),
        )

    def write(self, run: Run, record: Any | None, values: Mapping[str, Any], new: bool) -> Any:
        given = self._given(values, record)
        if "parent" in values:
            parent = values["parent"]
            given["parent_region_hid"] = (
                run.place(parent, "parent", geography.REGION).hid if parent is not None else None
            )
        return self._store(run, record, given)

    def read(self, db: Session, found: list[Any], own: bool = True) -> list[dict[str, Any]]:
        atlas = geography.Atlas(db)
        labels = tags.labels_of(db, self.record_type, [region.hid for region in found])
        return [
            {
                **self._row(region, labels, atlas.region_path(region.hid)),
                "parent": _region_named(atlas, region.parent_region_hid),
            }
            for region in found
        ]


class Sites(_Places):
    """Sites."""

    name = "sites"
    record_type = "site"
    level = geography.SITE
    model = Site
    listing = fields.SITES
    columns = (
        HID,
        Column("name"),
        Column("region", limit=LONG),
        CODE,
        *STREET,
        *SHIPPING,
        SAME_AS_ADDRESS,
        *COORDINATES,
        NOTES,
        STATUS,
        TAGS,
        PATH,
        *BOOKKEEPING,
    )
    aliases: ClassVar[Mapping[str, str]] = {"region.name": "region", "region_hid": "region"}
    renamed: ClassVar[Mapping[str, str]] = {"region_hid": "region"}
    _fields = (
        "name",
        "code",
        *ADDRESS_FIELDS,
        *geography.SHIPPING,
        geography.SAME,
        "latitude",
        "longitude",
        "notes",
    )

    def find(self, run: Run, values: Mapping[str, Any]) -> Any | None:
        name, region = values.get("name"), values.get("region")
        if not name or not region:
            return None
        within = run.place(region, "region", geography.REGION)
        return run.db.scalar(
            select(Site).where(Site.region_hid == within.hid, Site.name_key == records.key(name))
        )

    def write(self, run: Run, record: Any | None, values: Mapping[str, Any], new: bool) -> Any:
        given = self._given(values, record)
        if values.get("region"):
            given["region_hid"] = run.place(values["region"], "region", geography.REGION).hid
        elif "region" in values:
            raise Invalid("a site is in a region", {"region": "is not cleared"})
        return self._store(run, record, given)

    def read(self, db: Session, found: list[Any], own: bool = True) -> list[dict[str, Any]]:
        atlas = geography.Atlas(db)
        atlas.take(found)
        labels = tags.labels_of(db, self.record_type, [site.hid for site in found])
        return [
            {
                **self._row(site, labels, atlas.site_path(site.hid)),
                "region": _region_named(atlas, site.region_hid),
            }
            for site in found
        ]


class Locations(_Places):
    """Locations."""

    name = "locations"
    record_type = "location"
    level = geography.LOCATION
    model = Location
    listing = fields.LOCATIONS
    columns = (
        HID,
        Column("name"),
        Column("site", limit=LONG),
        Column("parent", limit=LONG),
        CODE,
        Column("kind", limit=40),
        *STREET,
        *SHIPPING,
        SAME_AS_ADDRESS,
        *COORDINATES,
        NOTES,
        STATUS,
        TAGS,
        PATH,
        *BOOKKEEPING,
    )
    aliases: ClassVar[Mapping[str, str]] = {
        "site.name": "site",
        "site_hid": "site",
        "parent.name": "parent",
        "parent_location_hid": "parent",
    }
    renamed: ClassVar[Mapping[str, str]] = {
        "site_hid": "site",
        "parent_location_hid": "parent",
    }
    _fields = (
        "name",
        "code",
        "kind",
        *ADDRESS_FIELDS,
        *geography.SHIPPING,
        geography.SAME,
        "latitude",
        "longitude",
        "notes",
    )

    @staticmethod
    def _where(
        run: Run, values: Mapping[str, Any], record: Any | None
    ) -> tuple[geography.Place | None, geography.Place | None]:
        """Return the site a row names and the location its location is in.

        The parent is named whole, or from the site down, and a row that names it whole
        need not name the site.
        """
        site_text, parent_text = values.get("site"), values.get("parent")
        site = run.place(site_text, "site", geography.SITE) if site_text else None
        if site is None and record is not None:
            site = geography.get_place(run.db, geography.SITE, record.site_hid)
        parent = None
        if parent_text:
            parent = geography.find_place(run.db, parent_text)
            if (parent is None or parent.level != geography.LOCATION) and site is not None:
                # Named from the site down. A region or a site that answers to the
                # same words from the top is not what is in this site.
                parent = geography.find_within(run.db, site, parent_text)
            if parent is None or parent.level != geography.LOCATION:
                raise Invalid(
                    "there is no such location", {"parent": f"there is no location {parent_text}"}
                )
            if site is None:
                site = geography.get_place(run.db, geography.SITE, parent.record.site_hid)
        return site, parent

    def find(self, run: Run, values: Mapping[str, Any]) -> Any | None:
        name = values.get("name")
        if not name:
            return None
        site, parent = self._where(run, values, None)
        if site is None:
            return None
        # Among the locations of the one it is in, or of the site when it is in none.
        found = geography.find_within(run.db, parent or site, name)
        if found is None or found.level != geography.LOCATION:
            return None
        return found.record

    def order(self, run: Run, rows: Sequence[Mapping[str, Any]]) -> list[int]:
        """Work a location before the locations of the same file that are within it."""

        to_site: dict[str, int] = {}

        def depth(row: Mapping[str, Any]) -> int:
            """Return how deep within its site the row's location is: the names of
            its parent, without those that lead to the site when it is named whole."""
            parent = row.get("parent")
            if not isinstance(parent, str) or ids.is_hid(parent.strip()):
                return 0
            if parent not in to_site:
                to_site[parent] = geography.names_to_site(run.db, parent)
            return _in_force_parts(parent) - to_site[parent]

        return sorted(range(1, len(rows) + 1), key=lambda number: (depth(rows[number - 1]), number))

    def write(self, run: Run, record: Any | None, values: Mapping[str, Any], new: bool) -> Any:
        given = self._given(values, record)
        site, parent = self._where(run, values, record)
        if "site" in values or record is None:
            if site is None:
                raise Invalid("a location is in a site", {"site": "name the site it is in"})
            given["site_hid"] = site.hid
        if "parent" in values:
            given["parent_location_hid"] = parent.hid if parent is not None else None
        return self._store(run, record, given)

    def read(self, db: Session, found: list[Any], own: bool = True) -> list[dict[str, Any]]:
        atlas = geography.Atlas(db)
        atlas.take(found)
        atlas.read_locations(location.parent_location_hid for location in found)
        atlas.read_sites(location.site_hid for location in found)
        labels = tags.labels_of(db, self.record_type, [location.hid for location in found])
        return [
            {
                **self._row(location, labels, atlas.location_path(location.hid)),
                "site": atlas.site_path(location.site_hid),
                "parent": atlas.location_path(location.parent_location_hid) or None,
            }
            for location in found
        ]


class Contacts(Entity):
    """Contacts."""

    name = "contacts"
    record_type = "contact"
    model = Contact
    listing = fields.CONTACTS
    columns = (
        HID,
        Column("name"),
        Column("organization"),
        Column("email", limit=254),
        Column("phone", limit=50),
        NOTES,
        STATUS,
        TAGS,
        *BOOKKEEPING,
    )
    _direct = ("name", "organization", "email", "phone", "notes", "tags")

    def find(self, run: Run, values: Mapping[str, Any]) -> Any | None:
        """Match a row to a contact: by its email address, and with none by its name."""
        email, name = values.get("email"), values.get("name")
        if email:
            return run.db.scalar(select(Contact).where(Contact.email_key == records.key(email)))
        if not name:
            return None
        named = list(
            run.db.scalars(select(Contact).where(Contact.name_key == records.key(name)).limit(50))
        )
        if len(named) <= 1:
            return named[0] if named else None
        # Of several of one name, a row with no email address is the one that has none.
        bare = [contact for contact in named if contact.email is None]
        if len(bare) != 1:
            raise Invalid(
                f"more than one contact is called {name}",
                {"name": "more than one contact answers to this; give its email address or HID"},
            )
        return bare[0]

    def key(self, values: Mapping[str, Any], record: Any | None) -> str:
        return (
            values.get("email") or values.get("name") or (record.name if record is not None else "")
        )

    def write(self, run: Run, record: Any | None, values: Mapping[str, Any], new: bool) -> Any:
        given = {**_plain_fields(values, self._direct), **_status(values, record)}
        if given.get("tags", _MISSING) is None:
            given["tags"] = []
        if record is None:
            return contacts.create_contact(run.db, run.context, _new(given))
        return contacts.update_contact(run.db, run.context, record.hid, record.row_version, given)

    def read(self, db: Session, found: list[Any], own: bool = True) -> list[dict[str, Any]]:
        labels = tags.labels_of(db, self.record_type, [contact.hid for contact in found])
        return [
            {
                **_kept(contact),
                **{name: getattr(contact, name) for name in self._direct if name != "tags"},
                "record_status": contact.record_status,
                "tags": labels[contact.hid],
            }
            for contact in found
        ]


class ContactAssignments(Entity):
    """The contacts of regions, sites and locations, each in a role."""

    name = "contact_assignments"
    record_type = "contact_assignment"
    model = ContactAssignment
    listing = fields.CONTACT_ASSIGNMENTS
    columns = (
        HID,
        Column("region", limit=LONG),
        Column("site", limit=LONG),
        Column("location", limit=LONG),
        Column("role", limit=40),
        Column("contact", limit=254),
        Column("priority", "integer"),
        Column("stop_inheritance", "boolean"),
        *BOOKKEEPING,
    )
    aliases: ClassVar[Mapping[str, str]] = {
        "region_hid": "region",
        "site_hid": "site",
        "location_hid": "location",
        "contact_hid": "contact",
        "contact.name": "contact",
        "contact.email": "contact",
    }
    renamed: ClassVar[Mapping[str, str]] = {
        "region_hid": "region",
        "site_hid": "site",
        "location_hid": "location",
        "contact_hid": "contact",
    }
    _levels = (geography.REGION, geography.SITE, geography.LOCATION)

    def _place(self, run: Run, values: Mapping[str, Any]) -> dict[str, str]:
        """Return the place a row names, as the field of an assignment that holds it."""
        named = [level for level in self._levels if values.get(level)]
        if len(named) != 1:
            raise Invalid(
                "an assignment is to one place",
                dict.fromkeys(named or self._levels, "exactly one of region, site and location"),
            )
        return {f"{named[0]}_hid": run.place(values[named[0]], named[0], named[0]).hid}

    def find(self, run: Run, values: Mapping[str, Any]) -> Any | None:
        """Match a row to an assignment: by its place, its role and its contact, or as
        the one that stops inheritance for its place and role."""
        role = values.get("role")
        if not role or not any(values.get(level) for level in self._levels):
            return None
        ((field, hid),) = self._place(run, values).items()
        query = select(ContactAssignment).where(
            getattr(ContactAssignment, field) == hid,
            ContactAssignment.role == records.key(role),
        )
        if values.get("contact"):
            query = query.where(ContactAssignment.contact_hid == run.contact(values["contact"]).hid)
        elif values.get("stop_inheritance"):
            query = query.where(ContactAssignment.stop_inheritance.is_(True))
        else:
            return None
        return run.db.scalar(query)

    def key(self, values: Mapping[str, Any], record: Any | None) -> str:
        named = [values.get(name) for name in (*self._levels, "role", "contact")]
        return " ".join(str(part) for part in named if part)

    def write(self, run: Run, record: Any | None, values: Mapping[str, Any], new: bool) -> Any:
        given = _plain_fields(values, ("role", "priority", "stop_inheritance"))
        if given.get("stop_inheritance", _MISSING) is None:
            given["stop_inheritance"] = False
        if "contact" in values:
            contact = values["contact"]
            given["contact_hid"] = run.contact(contact).hid if contact is not None else None
        if record is None:
            given.update(self._place(run, values))
            return contacts.create_assignment(run.db, run.context, _new(given))
        if any(level in values for level in self._levels):
            given.update(self._place(run, values))
        return contacts.update_assignment(
            run.db, run.context, record.hid, record.row_version, given
        )

    def read(self, db: Session, found: list[Any], own: bool = True) -> list[dict[str, Any]]:
        atlas = geography.Atlas(db)
        atlas.read_sites(assignment.site_hid for assignment in found)
        atlas.read_locations(assignment.location_hid for assignment in found)
        people = _by_hid(db, Contact, {assignment.contact_hid for assignment in found})
        named = contacts.reference_texts(db, list(people.values()))
        return [
            {
                **_kept(assignment),
                "region": _region_named(atlas, assignment.region_hid),
                "site": atlas.site_path(assignment.site_hid) or None,
                "location": atlas.location_path(assignment.location_hid) or None,
                "role": assignment.role,
                "contact": named[assignment.contact_hid] if assignment.contact_hid else None,
                "priority": assignment.priority,
                "stop_inheritance": assignment.stop_inheritance,
            }
            for assignment in found
        ]


class OwnerMembers(Entity):
    """The people of owners."""

    name = "owner_members"
    record_type = "owner_member"
    model = OwnerMember
    listing = fields.OWNER_MEMBERS
    columns = (
        HID,
        Column("owner"),
        Column("contact", limit=254),
        Column("role", limit=10),
        Column("priority", "integer"),
        *BOOKKEEPING,
    )
    aliases: ClassVar[Mapping[str, str]] = {
        "owner_hid": "owner",
        "owner.label": "owner",
        "contact_hid": "contact",
        "contact.name": "contact",
    }
    renamed: ClassVar[Mapping[str, str]] = {"owner_hid": "owner", "contact_hid": "contact"}

    def order(self, run: Run, rows: Sequence[Mapping[str, Any]]) -> list[int]:
        """Work the rows that name a primary before the others, wherever they stand.

        An owner that has people has exactly one primary: its first member is it, and
        the one that had the role gives it up to the one a row names. Both come out
        right when the primary of each owner is settled first.
        """

        def later(number: int) -> bool:
            role = rows[number - 1].get("role")
            return not (isinstance(role, str) and records.key(role) == owners.PRIMARY)

        return sorted(range(1, len(rows) + 1), key=lambda number: (later(number), number))

    def find(self, run: Run, values: Mapping[str, Any]) -> Any | None:
        owner, contact = values.get("owner"), values.get("contact")
        if not owner or not contact:
            return None
        return run.db.scalar(
            select(OwnerMember).where(
                OwnerMember.owner_hid == run.owner(owner).hid,
                OwnerMember.contact_hid == run.contact(contact).hid,
            )
        )

    def key(self, values: Mapping[str, Any], record: Any | None) -> str:
        return " ".join(str(values[name]) for name in ("owner", "contact") if values.get(name))

    def write(self, run: Run, record: Any | None, values: Mapping[str, Any], new: bool) -> Any:
        given = _plain_fields(values, ("role", "priority"))
        if record is None:
            for name in ("owner", "contact"):
                if not values.get(name):
                    raise Invalid("a member is a contact of an owner", {name: "must not be blank"})
            given["contact_hid"] = run.contact(values["contact"]).hid
            return owners.add_member(
                run.db, run.context, run.owner(values["owner"]).hid, _new(given)
            )
        for name in ("owner", "contact"):
            if name not in values:
                continue
            named = run.owner(values[name]) if name == "owner" else run.contact(values[name])
            if named.hid != getattr(record, f"{name}_hid"):
                raise Invalid(
                    "a member stays with its owner and its contact",
                    {name: "remove this member and add the other"},
                )
        return owners.update_member(
            run.db, run.context, record.owner_hid, record.hid, record.row_version, given
        )

    def read(self, db: Session, found: list[Any], own: bool = True) -> list[dict[str, Any]]:
        its_owners = _by_hid(db, Owner, {member.owner_hid for member in found})
        people = _by_hid(db, Contact, {member.contact_hid for member in found})
        named = contacts.reference_texts(db, list(people.values()))
        return [
            {
                **_kept(member),
                "owner": items.name_or_hid(its_owners[member.owner_hid].label, member.owner_hid),
                "contact": named[member.contact_hid],
                "role": member.role,
                "priority": member.priority,
            }
            for member in found
        ]


class CatalogEntries(Entity):
    """Catalog entries."""

    name = "catalog_entries"
    record_type = "catalog_entry"
    model = CatalogEntry
    listing = fields.CATALOG_ENTRIES
    _discount = Column("stack_discount_pct", "number", inherits=True)
    columns = (
        HID,
        Column("vendor"),
        Column("pid", limit=100),
        Column("model_name"),
        Column("kind", limit=20),
        Column("type", limit=40),
        Column("function", limit=40),
        Column("description", limit=LONG),
        *(Column(name, "date") for name in catalog.DATES),
        Column("est_value", "money"),
        Column("support_weight", "number"),
        Column("annual_support_cost", "money"),
        _discount,
        Column("successor_vendor"),
        Column("successor_pid", limit=100),
        REVIEW,
        STATUS,
        TAGS,
        *_sources((_discount,)),
        *BOOKKEEPING,
    )
    renamed: ClassVar[Mapping[str, str]] = {
        "vendor_hid": "vendor",
        "successor_hid": "successor_pid",
    }
    _direct = (
        "pid",
        "model_name",
        "kind",
        "type",
        "function",
        "description",
        *catalog.DATES,
        *catalog.AMOUNTS,
        "stack_discount_pct",
        "review_status",
        "tags",
    )

    def find(self, run: Run, values: Mapping[str, Any]) -> Any | None:
        vendor, pid = values.get("vendor"), values.get("pid")
        if not vendor or not pid:
            return None
        return run.entry(vendor, pid)

    def key(self, values: Mapping[str, Any], record: Any | None) -> str:
        named = " ".join(part for part in (values.get("vendor"), values.get("pid")) if part)
        return named or (record.pid if record is not None else "")

    def _successor(
        self, run: Run, record: Any | None, values: Mapping[str, Any], vendor: Vendor | None
    ) -> dict[str, Any]:
        if "successor_pid" not in values and "successor_vendor" not in values:
            return {}
        current = (
            run.db.get(CatalogEntry, record.successor_hid)
            if record is not None and record.successor_hid
            else None
        )
        pid = values.get("successor_pid", current.pid if current is not None else None)
        if pid is None:
            if values.get("successor_vendor"):
                raise Invalid(
                    "the successor is not acceptable",
                    {"successor_pid": "a successor is named by its PID"},
                )
            return {"successor_hid": None}
        maker = values.get("successor_vendor")
        if maker is None:
            # Left blank, the successor is a model of the same vendor.
            if vendor is None:
                raise Invalid(
                    "the successor is not acceptable",
                    {"successor_vendor": "name the vendor of the successor"},
                )
            maker = vendor.hid
        successor = run.entry(maker, pid, create=True)
        assert successor is not None  # noqa: S101 - made when it was not there
        return {"successor_hid": successor.hid}

    def write(self, run: Run, record: Any | None, values: Mapping[str, Any], new: bool) -> Any:
        given = {**_plain_fields(values, self._direct), **_status(values, record)}
        vendor = run.db.get(Vendor, record.vendor_hid) if record is not None else None
        if values.get("vendor"):
            vendor = run.vendor(values["vendor"], create=True)
            assert vendor is not None  # noqa: S101 - made when it was not there
            given["vendor_hid"] = vendor.hid
        elif "vendor" in values:
            given["vendor_hid"] = None
        given.update(self._successor(run, record, values, vendor))
        if given.get("tags", _MISSING) is None:
            given["tags"] = []
        discount = given.get("stack_discount_pct")
        if (
            discount is not None
            and (record is None or record.stack_discount_pct is None)
            and discount == Decimal(str(settings.value(run.db, "stack_discount_pct")))
        ):
            # An import does not turn an inherited value into an override: the entry
            # has no discount of its own, and the row holds the very one it inherits.
            del given["stack_discount_pct"]
        run.renamed()
        if record is None:
            return catalog.create_entry(run.db, run.context, _new(given))
        if new and "review_status" not in given:
            # An earlier row made this entry for a reference, to be reviewed. This row
            # describes it, so it is as reviewed as any entry a file creates.
            given["review_status"] = "reviewed"
        return catalog.update_entry(run.db, run.context, record.hid, record.row_version, given)

    def read(self, db: Session, found: list[Any], own: bool = True) -> list[dict[str, Any]]:
        vendors = _by_hid(db, Vendor, {entry.vendor_hid for entry in found})
        successors = _by_hid(db, CatalogEntry, {entry.successor_hid for entry in found})
        vendors.update(
            _by_hid(db, Vendor, {entry.vendor_hid for entry in successors.values()} - set(vendors))
        )
        labels = tags.labels_of(db, self.record_type, [entry.hid for entry in found])
        discount = Decimal(str(settings.value(db, "stack_discount_pct")))
        rows = []
        for entry in found:
            successor = successors.get(entry.successor_hid) if entry.successor_hid else None
            in_force = inheritance.of_catalog_entry(entry, discount)["stack_discount_pct"]
            row = {
                **_kept(entry),
                "vendor": vendors[entry.vendor_hid].name,
                **{name: getattr(entry, name) for name in self._direct if name != "tags"},
                "successor_vendor": vendors[successor.vendor_hid].name if successor else None,
                "successor_pid": successor.pid if successor else None,
                "record_status": entry.record_status,
                "tags": labels[entry.hid],
                "stack_discount_pct_source": in_force.source,
            }
            if not own:
                row["stack_discount_pct"] = in_force.value
            rows.append(row)
        return rows


class Items(Entity):
    """Items."""

    name = "items"
    record_type = "item"
    model = Item
    listing = fields.ITEMS
    # What a minor item has from the item it is in, when it has none of its own.
    _OWNER = Column("owner", inherits=True)
    _LOCATION = Column("location", limit=LONG, inherits=True)
    _OPERATOR = Column("operator", limit=254, inherits=True)
    _STANDING = (
        Column("lifecycle_state", limit=20, inherits=True),
        Column("disposition", limit=12, inherits=True),
        Column("expected_online", "boolean", inherits=True),
    )
    columns = (
        HID,
        Column("vendor"),
        Column("pid", limit=100),
        Column("serial_number", limit=100),
        Column("asset_tag", limit=100),
        Column("name"),
        Column("hostname", limit=255),
        Column("fqdn", limit=255),
        Column("mac_address", limit=40),
        Column("parent"),
        Column("position", limit=100),
        Column("description", limit=LONG),
        Column("comments", limit=LONG),
        Column("quantity", "integer"),
        *_STANDING,
        Column("state_reason", limit=40),
        Column("condition", limit=40),
        *OBSERVATION,
        _OWNER,
        _OPERATOR,
        _LOCATION,
        *MANAGEMENT,
        *(Column(name, "date") for name in items.DAYS),
        *AMOUNTS,
        *DATES,
        STATUS,
        TAGS,
        Column("model_name", settable=False),
        Column("kind", settable=False),
        Column("type", settable=False),
        Column("function", settable=False),
        Column("state_changed_at", "timestamp", settable=False),
        Column("is_major", "boolean", settable=False),
        Column("depth", "integer", settable=False),
        Column("health", limit=12, settable=False),
        Column("site", settable=False),
        Column("region", settable=False),
        Column("owner_exception", "boolean", settable=False),
        Column("owner_exception_reason", limit=LONG, settable=False),
        *_sources((_OWNER, _OPERATOR, _LOCATION, *_STANDING, *AMOUNTS, *DATES)),
        *BOOKKEEPING,
    )
    aliases: ClassVar[Mapping[str, str]] = {
        "catalog.vendor": "vendor",
        "catalog.pid": "pid",
        "catalog.model_name": "model_name",
        "catalog.kind": "kind",
        "catalog.type": "type",
        "catalog.function": "function",
        "owner.label": "owner",
        "parent_item_hid": "parent",
        "parent.name": "parent",
        **{f"effective.{name}": name for name in inheritance.ITEM_FIELDS},
        "effective.owner_hid": "owner",
        "location_hid": "location",
        "effective.location_hid": "location",
        "location.name": "location",
        "operator_hid": "operator",
        "effective.operator_hid": "operator",
        "operator.name": "operator",
        "operator.email": "operator",
        "site_hid": "site",
        "region_hid": "region",
        **{f"effective.{name}": name for name in inheritance.STANDING},
        **MGMT_SPELLINGS,
    }
    by_the_clock = frozenset({"observed_at"})
    restated = frozenset({"mgmt_address"})
    renamed: ClassVar[Mapping[str, str]] = {
        "catalog_entry_hid": "pid",
        "owner_hid": "owner",
        "operator_hid": "operator",
        "location_hid": "location",
        "parent_item_hid": "parent",
        "address": "mgmt_address",
        "network_hid": "mgmt_network",
        # A move names its state and its reason otherwise than a file does.
        "to": "lifecycle_state",
        "reason": "state_reason",
    }
    not_in_bulk = frozenset(
        {"serial_number", "asset_tag", "mac_address", "name", "hostname", "fqdn", *MGMT}
    )
    _direct = (
        *items.TEXTS,
        "mac_address",
        "position",
        "quantity",
        "condition",
        "observed_status",
        "observed_at",
        *items.DAYS,
        "tags",
    )

    def find(self, run: Run, values: Mapping[str, Any]) -> Any | None:
        """Match a row to an item. The first rule that applies decides.

        The order is on the data model page under "Identity and matching": the vendor,
        PID and serial number; then the asset tag; then, for a row with neither a serial
        number nor an asset tag, the name or the host name, among the items that are
        not retired. More than one candidate is an error, never a guess.
        """
        db = run.db
        vendor, pid = values.get("vendor"), values.get("pid")
        serial, tag = values.get("serial_number"), values.get("asset_tag")
        if vendor and pid and serial:
            entry = run.entry(vendor, pid)
            if entry is None:
                return None
            return db.scalar(
                select(Item).where(
                    Item.catalog_entry_hid == entry.hid, Item.serial_key == records.key(serial)
                )
            )
        if tag:
            return db.scalar(select(Item).where(Item.asset_tag_key == records.key(tag)))
        if serial:
            return None
        # By what it is called: its name, or its host name where it has no name, and
        # for a row that gives only a host name, its host name. The item that answers
        # may have a serial number of its own: a site's file of host names finds the
        # switches it has.
        called: Any = func.coalesce(Item.name, Item.hostname)
        host: Any = Item.hostname
        for given, column in (
            (values.get("name"), called),
            (values.get("hostname"), host),
        ):
            if not given:
                continue
            named = list(
                db.scalars(
                    select(Item)
                    .where(
                        dialect.equals_text(column, given.strip()),
                        Item.record_status != "retired",
                    )
                    .limit(2)
                )
            )
            if len(named) > 1:
                field = "name" if column is called else "hostname"
                raise Invalid(
                    f"more than one item is called {given}",
                    {field: "more than one item answers to this; give the HID of the one meant"},
                )
            if named:
                return named[0]
        return None

    def key(self, values: Mapping[str, Any], record: Any | None) -> str:
        for names in (("vendor", "pid", "serial_number"), ("asset_tag",), ("name",), ("hostname",)):
            if all(values.get(name) for name in names):
                return " ".join(str(values[name]) for name in names)
        if record is None:
            return values.get("serial_number") or ""
        return record.name or record.hostname or record.serial_number or record.asset_tag or ""

    def _entry(
        self, run: Run, record: Any | None, values: Mapping[str, Any]
    ) -> CatalogEntry | None:
        """Return the catalog entry the item will have, made if the row names a new one."""
        current = (
            run.db.get(CatalogEntry, record.catalog_entry_hid)
            if record is not None and record.catalog_entry_hid
            else None
        )
        if "vendor" not in values and "pid" not in values:
            return current
        vendor = values.get("vendor", current.vendor_hid if current is not None else None)
        pid = values.get("pid", current.pid if current is not None else None)
        if vendor is None and pid is None:
            return None
        if vendor is None or pid is None:
            missing = "vendor" if vendor is None else "pid"
            raise Invalid(
                "a catalog entry is named by its vendor and its PID",
                {missing: "a catalog entry is named by its vendor and its PID together"},
            )
        return run.entry(vendor, pid, create=True)

    @staticmethod
    def _overrides(
        record: Any | None,
        before: CatalogEntry | None,
        entry: CatalogEntry | None,
        values: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Return the values of the fields that inherit, as the row sets them.

        An import does not turn an inherited value into an override. Where the item has
        no value of its own, a row that holds the very value it inherits says nothing
        new, and the field is left to inherit. That holds for what it inherits from the
        model the row gives it, and for what it inherited from the model it had: a row
        of an export in which only the model was changed still holds the old model's
        values, and they are not the item's own.
        """
        given: dict[str, Any] = {}
        for name in inheritance.ITEM_FIELDS:
            if name not in values:
                continue
            value = values[name]
            own = getattr(record, name) if record is not None else None
            inherited = {getattr(model, name) for model in (before, entry) if model is not None}
            if value is not None and own is None and value in inherited:
                continue
            given[name] = value
        return given

    def order(self, run: Run, rows: Sequence[Mapping[str, Any]]) -> list[int]:
        """Work an item before the minor items that are in it, wherever its row stands.

        What a row means for a minor item depends on what the item above it holds: a
        row with the very owner or state it would inherit leaves it inheriting. So when
        one file, or one bulk edit, changes an item and its minor items, the item is
        changed first, and what its minor items are compared with is what it will hold.
        A row that makes a new item keeps its place among the rows of its depth.
        """
        db = run.db
        plain = list(range(1, len(rows) + 1))
        uses_parents = any("parent" in row for row in rows)
        if (
            not uses_parents
            and db.scalar(select(Item.hid).where(Item.parent_item_hid.is_not(None)).limit(1))
            is None
        ):
            return plain
        named: dict[int, Item | None] = {}
        for number, row in zip(plain, rows, strict=True):
            try:
                named[number] = db.get(Item, row["hid"]) if row.get("hid") else self.find(run, row)
            except DomainError:
                named[number] = None
        lines = items.lines_above(db, [item for item in named.values() if item is not None])
        depths: dict[int, int] = {}
        for number, row in zip(plain, rows, strict=True):
            item = named[number]
            parent = row.get("parent", _MISSING)
            if parent is None:
                depths[number] = 0
            elif parent is not _MISSING:
                # In the item the row names: one deeper than it, or last if it is one
                # that an earlier row of this file is still to make.
                above = items.known_as(db, str(parent), limit=1)
                depths[number] = (
                    len(items.ancestors(db, above[0])) + 1 if above else items.MAX_DEPTH + 1
                )
            else:
                depths[number] = len(lines[item.hid]) if item is not None else 0
        run.let_go()
        return sorted(plain, key=lambda number: (depths[number], number))

    @staticmethod
    def _above(run: Run, record: Any | None, given: Mapping[str, Any]) -> list[Item]:
        """Return the items the item will be in, the nearest first."""
        current = record.parent_item_hid if record is not None else None
        parent = run.db.get(Item, given.get("parent_item_hid", current) or "")
        return [] if parent is None else [parent, *items.ancestors(run.db, parent)]

    @staticmethod
    def _operator_above(
        run: Run, record: Any | None, given: Mapping[str, Any], above: list[Item]
    ) -> str | None:
        """Return the operator an item has with none of its own: that of the item above
        it, or that of a group the item at the top of the line is a member of."""
        if record is None and not above:
            return None
        line = above if record is None else [record, *above]
        held = next((one.operator_hid for one in above if one.operator_hid), None)
        if held is not None:
            return held
        top = line[-1].hid
        return operators.from_groups(run.db, [top])[top].value

    @staticmethod
    def _standing(
        record: Any | None, above: list[Item], standing: dict[str, Any]
    ) -> dict[str, Any]:
        """Return the lifecycle fields a row sets, without what a minor item has anyway.

        An import does not turn an inherited value into an override. A minor item with
        no state of its own has the state, disposition and intent of the item above it,
        and a row that holds those very three says nothing new.
        """
        holder = next((one for one in above if one.lifecycle_state is not None), None)
        if holder is None or (record is not None and record.lifecycle_state is not None):
            return standing
        named = {name: standing[name] for name in inheritance.STANDING if name in standing}
        if not named or any(value is None for value in named.values()):
            return standing
        spelled = {
            "lifecycle_state": lifecycle.state_name,
            "disposition": lifecycle.disposition_name,
            "expected_online": bool,
        }
        try:
            if any(spelled[name](value) != getattr(holder, name) for name, value in named.items()):
                return standing
        except Invalid:
            return standing
        return {name: value for name, value in standing.items() if name not in named}

    def write(self, run: Run, record: Any | None, values: Mapping[str, Any], new: bool) -> Any:
        db, context = run.db, run.context
        given = {**_plain_fields(values, self._direct), **_status(values, record)}
        before = (
            run.db.get(CatalogEntry, record.catalog_entry_hid)
            if record is not None and record.catalog_entry_hid
            else None
        )
        entry = self._entry(run, record, values)
        if "vendor" in values or "pid" in values:
            given["catalog_entry_hid"] = entry.hid if entry is not None else None
        if "parent" in values:
            parent = values["parent"]
            given["parent_item_hid"] = (
                run.item(parent, "parent").hid if parent is not None else None
            )
        above = self._above(run, record, given)
        if "owner" in values:
            named = values["owner"]
            owner_hid = run.owner(named).hid if named is not None else None
            inherited = next((one.owner_hid for one in above if one.owner_hid), None)
            own = record.owner_hid if record is not None else None
            if owner_hid is None or own is not None or owner_hid != inherited:
                # Otherwise the row holds the owner the item has from the item above.
                given["owner_hid"] = owner_hid
        if "operator" in values:
            named = values["operator"]
            operator_hid = run.contact(named, "operator").hid if named is not None else None
            own = record.operator_hid if record is not None else None
            if (
                operator_hid is None
                or own is not None
                or operator_hid != self._operator_above(run, record, given, above)
            ):
                # Otherwise the row names the operator the item has anyway, from above.
                given["operator_hid"] = operator_hid
        if "location" in values:
            named = values["location"]
            location_hid = (
                run.place(named, "location", geography.LOCATION).hid if named is not None else None
            )
            inherited = next((one.location_hid for one in above if one.location_hid), None)
            own = record.location_hid if record is not None else None
            if location_hid is None or own is not None or location_hid != inherited:
                # Otherwise the row says where the item is anyway, with the item above.
                given["location_hid"] = location_hid
        given.update(self._overrides(record, before, entry, values))
        if given.get("tags", _MISSING) is None:
            given["tags"] = []
        standing = self._standing(record, above, _plain_fields(values, items.STANDING))
        if record is None:
            record = items.create_item(db, context, _new({**given, **standing}))
            _management(run, "item_hid", record.hid, values)
            return record

        state = standing.get("lifecycle_state", _MISSING)
        clearing = state is None and record.lifecycle_state is not None
        if clearing and not above:
            raise Invalid(
                "a lifecycle state is not cleared",
                {"lifecycle_state": "an item leaves a state by moving to another"},
            )
        moving = (
            state is not _MISSING
            and state is not None
            and lifecycle.state_name(state) != record.lifecycle_state
        )
        reason = standing.get("state_reason", _MISSING)
        if not moving and not clearing:
            if reason is not _MISSING and reason != record.state_reason:
                raise Invalid(
                    "a reason is given with a move",
                    {"state_reason": "a reason is taken with a move to another lifecycle state"},
                )
            for name in ("disposition", "expected_online"):
                if name in standing and standing[name] != getattr(record, name):
                    given[name] = standing[name]
        items.update_item(db, context, record.hid, record.row_version, given)
        if moving or clearing:
            # A change of state is a transition, so that it records who, when and why.
            # To no state, a minor item has the standing of the item above it again.
            items.transition(
                db,
                context,
                record.hid,
                record.row_version,
                to=state,
                role=run.role,
                reason=None if reason is _MISSING else reason,
                disposition=standing.get("disposition", UNSET),
                expected_online=standing.get("expected_online", UNSET),
            )
        _management(run, "item_hid", record.hid, values)
        return record

    def read(self, db: Session, found: list[Any], own: bool = True) -> list[dict[str, Any]]:
        hids = [item.hid for item in found]
        lines = items.lines_above(db, found)
        entries = _by_hid(db, CatalogEntry, {item.catalog_entry_hid for item in found})
        vendors = _by_hid(db, Vendor, {entry.vendor_hid for entry in entries.values()})
        its_owners = _by_hid(
            db,
            Owner,
            {item.owner_hid for item in found}
            | {one.owner_hid for line in lines.values() for one in line},
        )
        labels = tags.labels_of(db, self.record_type, hids)
        primaries = _primaries(db, "item_hid", hids)
        parents = items.reference_texts(db, [line[0] for line in lines.values() if line])
        atlas = geography.Atlas(db)
        atlas.read_locations(
            {item.location_hid for item in found}
            | {one.location_hid for line in lines.values() for one in line}
        )
        looked_after = operators.of_items(db, found, lines)
        people = _by_hid(
            db,
            Contact,
            {item.operator_hid for item in found} | {one.value for one in looked_after.values()},
        )
        called = contacts.reference_texts(db, list(people.values()))
        rows = []
        for item in found:
            entry = entries.get(item.catalog_entry_hid) if item.catalog_entry_hid else None
            line = lines[item.hid]
            in_force = inheritance.of_item(item, entry, line)
            where = atlas.location(in_force["location_hid"].value or "")
            site = atlas.site(where.site_hid) if where is not None else None
            owner_in_force = its_owners.get(in_force["owner_hid"].value or "")
            outside = owner_in_force is not None and owner_in_force.is_external
            row: dict[str, Any] = {
                **_kept(item),
                "vendor": vendors[entry.vendor_hid].name if entry else None,
                "pid": entry.pid if entry else None,
                **{name: getattr(item, name) for name in self._direct if name != "tags"},
                "parent": parents[line[0].hid] if line else None,
                "state_reason": item.state_reason,
                **primaries.get(item.hid, NO_MGMT),
                "record_status": item.record_status,
                "tags": labels[item.hid],
                "model_name": entry.model_name if entry else None,
                "kind": entry.kind if entry else None,
                "type": entry.type if entry else None,
                "function": entry.function if entry else None,
                "state_changed_at": item.state_changed_at,
                "is_major": item.parent_item_hid is None,
                "depth": len(line),
                "health": health.of_item(
                    item.condition, item.observed_status, in_force["expected_online"].value
                ).value,
                "site": site.name if site is not None else None,
                "region": atlas.regions[site.region_hid].name if site is not None else None,
                "owner_exception": outside,
                "owner_exception_reason": owner_in_force.exception_reason if outside else None,
            }
            operator = item.operator_hid if own else looked_after[item.hid].value
            row["operator"] = called[operator] if operator else None
            row["operator_source"] = looked_after[item.hid].source
            for name, effective in in_force.items():
                column = {"owner_hid": "owner", "location_hid": "location"}.get(name, name)
                value = getattr(item, name) if own else effective.value
                if name == "owner_hid":
                    value = items.name_or_hid(its_owners[value].label, value) if value else None
                elif name == "location_hid":
                    value = atlas.location_path(value) if value else None
                row[column] = value
                row[f"{column}_source"] = effective.source
            rows.append(row)
        return rows


class Networks(Entity):
    """Networks."""

    name = "networks"
    record_type = "network"
    model = Network
    listing = fields.NETWORKS
    columns = (HID, Column("label", limit=100), Column("kind", limit=10), *BOOKKEEPING)

    def find(self, run: Run, values: Mapping[str, Any]) -> Any | None:
        label = values.get("label")
        if not label:
            return None
        return run.db.scalar(select(Network).where(Network.label_key == records.key(label)))

    def key(self, values: Mapping[str, Any], record: Any | None) -> str:
        return values.get("label") or (record.label if record is not None else "")

    def write(self, run: Run, record: Any | None, values: Mapping[str, Any], new: bool) -> Any:
        given = _plain_fields(values, ("label", "kind"))
        if record is None:
            return addresses.create_network(run.db, run.context, _new(given))
        return addresses.update_network(run.db, run.context, record.hid, record.row_version, given)

    def read(self, db: Session, found: list[Any], own: bool = True) -> list[dict[str, Any]]:
        return [
            {**_kept(network), "label": network.label, "kind": network.kind} for network in found
        ]


class DeviceGroups(Entity):
    """Device groups."""

    name = "device_groups"
    record_type = "device_group"
    model = DeviceGroup
    listing = fields.DEVICE_GROUPS
    columns = (
        HID,
        Column("name"),
        Column("type", limit=20),
        Column("hostname", limit=255),
        Column("fqdn", limit=255),
        Column("parent"),
        Column("owner"),
        Column("operator", limit=254),
        Column("location", limit=LONG),
        Column("managed_as", limit=20),
        Column("expected_members", "integer"),
        *OBSERVATION,
        *MANAGEMENT,
        STATUS,
        TAGS,
        Column("serial_number", settable=False),
        Column("members", "integer", settable=False),
        Column("health", limit=12, settable=False),
        *BOOKKEEPING,
    )
    by_the_clock = frozenset({"observed_at"})
    restated = frozenset({"mgmt_address"})
    _direct = (
        "name",
        "type",
        "hostname",
        "fqdn",
        "managed_as",
        "expected_members",
        "observed_status",
        "observed_at",
        "tags",
    )
    aliases: ClassVar[Mapping[str, str]] = {
        "owner.label": "owner",
        "owner_hid": "owner",
        "location_hid": "location",
        "location.name": "location",
        "operator_hid": "operator",
        "operator.name": "operator",
        "operator.email": "operator",
        "parent.name": "parent",
        "parent_group_hid": "parent",
        **MGMT_SPELLINGS,
    }
    renamed: ClassVar[Mapping[str, str]] = {
        "owner_hid": "owner",
        "operator_hid": "operator",
        "location_hid": "location",
        "parent_group_hid": "parent",
        "address": "mgmt_address",
        "network_hid": "mgmt_network",
    }

    def find(self, run: Run, values: Mapping[str, Any]) -> Any | None:
        name = values.get("name")
        return groups.find_group(run.db, name) if name else None

    def order(self, run: Run, rows: Sequence[Mapping[str, Any]]) -> list[int]:
        """Work a group before the groups of the same file that are within it."""
        named = {
            records.key(row["name"]): number
            for number, row in enumerate(rows, start=1)
            if isinstance(row.get("name"), str)
        }

        def level(number: int, seen: frozenset[int] = frozenset()) -> int:
            parent = rows[number - 1].get("parent")
            above = named.get(records.key(parent)) if isinstance(parent, str) else None
            if above is None or above in seen or above == number:
                return 0
            return level(above, seen | {number}) + 1

        return sorted(range(1, len(rows) + 1), key=lambda number: (level(number), number))

    def key(self, values: Mapping[str, Any], record: Any | None) -> str:
        return values.get("name") or (record.name if record is not None else "")

    def write(self, run: Run, record: Any | None, values: Mapping[str, Any], new: bool) -> Any:
        given = {**_plain_fields(values, self._direct), **_status(values, record)}
        if "parent" in values:
            parent = values["parent"]
            given["parent_group_hid"] = (
                run.group(parent, "parent").hid if parent is not None else None
            )
        if "owner" in values:
            owner = values["owner"]
            given["owner_hid"] = run.owner(owner).hid if owner is not None else None
        if "operator" in values:
            named = values["operator"]
            given["operator_hid"] = (
                run.contact(named, "operator").hid if named is not None else None
            )
        if "location" in values:
            place = values["location"]
            given["location_hid"] = (
                run.place(place, "location", geography.LOCATION).hid if place is not None else None
            )
        if given.get("tags", _MISSING) is None:
            given["tags"] = []
        if record is None:
            record = groups.create_group(run.db, run.context, _new(given))
        else:
            groups.update_group(run.db, run.context, record.hid, record.row_version, given)
        _management(run, "group_hid", record.hid, values)
        return record

    def read(self, db: Session, found: list[Any], own: bool = True) -> list[dict[str, Any]]:
        hids = [group.hid for group in found]
        its_owners = _by_hid(db, Owner, {group.owner_hid for group in found})
        parents = _by_hid(db, DeviceGroup, {group.parent_group_hid for group in found})
        labels = tags.labels_of(db, self.record_type, hids)
        primaries = _primaries(db, "group_hid", hids)
        counts = groups.member_counts(db, hids)
        masters = groups.masters(db, [group.hid for group in found if group.type == "stack"])
        seen = groups.observed_masters(db, found)
        healths = groups.health_of(db, found)
        atlas = geography.Atlas(db)
        atlas.read_locations(group.location_hid for group in found)
        people = _by_hid(db, Contact, {group.operator_hid for group in found})
        called = contacts.reference_texts(db, list(people.values()))
        rows = []
        for group in found:
            master = seen.get(group.hid) or masters.get(group.hid)
            its_health = healths[group.hid]
            rows.append(
                {
                    **_kept(group),
                    "name": group.name,
                    "type": group.type,
                    "hostname": group.hostname,
                    "fqdn": group.fqdn,
                    "parent": items.name_or_hid(
                        parents[group.parent_group_hid].name, group.parent_group_hid
                    )
                    if group.parent_group_hid
                    else None,
                    "owner": items.name_or_hid(its_owners[group.owner_hid].label, group.owner_hid)
                    if group.owner_hid
                    else None,
                    "operator": called[group.operator_hid] if group.operator_hid else None,
                    "location": atlas.location_path(group.location_hid) or None,
                    "managed_as": group.managed_as,
                    "expected_members": group.expected_members,
                    "observed_status": group.observed_status,
                    "observed_at": group.observed_at,
                    **primaries.get(group.hid, NO_MGMT),
                    "record_status": group.record_status,
                    "tags": labels[group.hid],
                    "serial_number": master.serial_number if master is not None else None,
                    "members": counts[group.hid],
                    "health": its_health.value if its_health is not None else None,
                }
            )
        return rows


class DeviceGroupMembers(Entity):
    """The memberships of device groups, the ones that have ended among them."""

    name = "device_group_members"
    record_type = "device_group_member"
    model = DeviceGroupMember
    listing = fields.DEVICE_GROUP_MEMBERS
    columns = (
        HID,
        Column("group"),
        Column("item"),
        Column("role", limit=20),
        Column("position", "integer"),
        Column("joined_on", "date"),
        Column("left_on", "date"),
        # Which member of a stack is seen to be master, and when it was seen. It is
        # kept on the stack, and travels on the row of the member.
        Column("observed_master", "boolean"),
        Column("master_observed_at", "timestamp"),
        *BOOKKEEPING,
    )
    by_the_clock = frozenset({"master_observed_at"})
    aliases: ClassVar[Mapping[str, str]] = {
        "group.name": "group",
        "group_hid": "group",
        "item.name": "item",
        "item_hid": "item",
    }
    renamed: ClassVar[Mapping[str, str]] = {
        "group_hid": "group",
        "item_hid": "item",
        "members": "",
        "observed_master_hid": "observed_master",
    }
    _direct = ("role", "position", "joined_on", "left_on")

    def find(self, run: Run, values: Mapping[str, Any]) -> Any | None:
        """Match a row to a membership: by its group, its item and the day it joined.

        With no `joined_on` it is the current membership of that item in that group.
        """
        group, item = values.get("group"), values.get("item")
        if not group or not item:
            return None
        query = select(DeviceGroupMember).where(
            DeviceGroupMember.group_hid == run.group(group).hid,
            DeviceGroupMember.item_hid == run.item(item, "item").hid,
        )
        joined = values.get("joined_on")
        if joined is not None:
            query = query.where(DeviceGroupMember.joined_on == joined)
        else:
            query = query.where(DeviceGroupMember.left_on.is_(None))
        found = list(run.db.scalars(query.limit(2)))
        if len(found) > 1:
            raise Invalid(
                "more than one membership answers to this row",
                {"joined_on": "the item joined this group twice that day; give the HID"},
            )
        return found[0] if found else None

    def key(self, values: Mapping[str, Any], record: Any | None) -> str:
        return " ".join(str(values[name]) for name in ("group", "item") if values.get(name))

    def write(self, run: Run, record: Any | None, values: Mapping[str, Any], new: bool) -> Any:
        db, context = run.db, run.context
        given = _plain_fields(values, self._direct)
        if record is None:
            for name in ("group", "item"):
                if not values.get(name):
                    raise Invalid(
                        "a membership is of an item in a group", {name: "must not be blank"}
                    )
            group = run.group(values["group"])
            item = run.item(values["item"], "item")
            self._marks(run, group, given, values)
            made = groups.add_members(
                db, context, group.hid, [{"item_hid": item.hid, **_new(given)}]
            )[0]
            self._seen_as_master(run, made, values)
            return made
        for name, model in (("group", DeviceGroup), ("item", Item)):
            if name not in values:
                continue
            named = (
                run.group(values[name]) if model is DeviceGroup else run.item(values[name], name)
            )
            if named.hid != getattr(record, f"{name}_hid"):
                raise Invalid(
                    "a membership stays with its group and its item",
                    {name: "end this membership and add the other"},
                )
        if given.get("role", _MISSING) is None:
            del given["role"]
        if given.get("joined_on", _MISSING) is None:
            raise Invalid("a membership has a day it began", {"joined_on": "is not cleared"})
        self._marks(run, groups.get_group(db, record.group_hid), given, values)
        changed = groups.update_member(
            db, context, record.group_hid, record.hid, record.row_version, given
        )
        self._seen_as_master(run, changed, values)
        return changed

    @staticmethod
    def _marks(run: Run, group: Any, given: Mapping[str, Any], values: Mapping[str, Any]) -> None:
        """Refuse a second row of the file that names a master of the same stack."""
        if group.type != "stack" or values.get("left_on") is not None:
            return
        role = given.get("role")
        if isinstance(role, str) and records.key(role) == groups.MASTER:
            run.names_master(group.hid, "intended", "role")
        if values.get("observed_master"):
            run.names_master(group.hid, "observed", "observed_master")

    @staticmethod
    def _seen_as_master(run: Run, member: Any, values: Mapping[str, Any]) -> None:
        """Record on the stack that this member is seen to be its master, or no longer is."""
        if "observed_master" not in values and "master_observed_at" not in values:
            return
        group = groups.get_group(run.db, member.group_hid)
        seen = values.get("observed_master", group.observed_master_hid == member.item_hid)
        # A member that has left is not seen as master, whatever its row still says.
        seen = bool(seen) and member.left_on is None
        fields: dict[str, Any]
        if seen:
            fields = {"observed_master_hid": member.item_hid}
            if values.get("master_observed_at") is not None:
                fields["master_observed_at"] = values["master_observed_at"]
        elif values.get("master_observed_at") is not None and member.left_on is None:
            raise Invalid(
                "no master is observed at that moment",
                {"master_observed_at": "give observed_master with it"},
            )
        elif group.observed_master_hid != member.item_hid:
            return
        else:
            fields = {"observed_master_hid": None}
        groups.update_group(run.db, run.context, group.hid, group.row_version, fields)

    def read(self, db: Session, found: list[Any], own: bool = True) -> list[dict[str, Any]]:
        its_groups = _by_hid(db, DeviceGroup, {member.group_hid for member in found})
        its_items = _by_hid(db, Item, {member.item_hid for member in found})
        named = items.reference_texts(db, list(its_items.values()))
        rows = []
        for member in found:
            group = its_groups[member.group_hid]
            seen = member.left_on is None and group.observed_master_hid == member.item_hid
            rows.append(
                {
                    **_kept(member),
                    "group": items.name_or_hid(group.name, member.group_hid),
                    "item": named[member.item_hid],
                    **{name: getattr(member, name) for name in self._direct},
                    "observed_master": seen,
                    "master_observed_at": group.master_observed_at if seen else None,
                }
            )
        return rows


class Addresses(Entity):
    """The addresses of items and of device groups."""

    name = "addresses"
    record_type = "address"
    model = Address
    listing = fields.ADDRESSES
    columns = (
        HID,
        Column("item"),
        Column("group"),
        Column("address", limit=45),
        Column("network", limit=100),
        Column("role", limit=12),
        Column("is_primary", "boolean"),
        Column("family", "integer", settable=False),
        *BOOKKEEPING,
    )
    aliases: ClassVar[Mapping[str, str]] = {
        "item.name": "item",
        "item_hid": "item",
        "group.name": "group",
        "group_hid": "group",
        "network.label": "network",
        "network_hid": "network",
    }
    renamed: ClassVar[Mapping[str, str]] = {
        "item_hid": "item",
        "group_hid": "group",
        "network_hid": "network",
    }

    @staticmethod
    def _holder(run: Run, values: Mapping[str, Any]) -> dict[str, str | None]:
        item, group = values.get("item"), values.get("group")
        return {
            "item_hid": run.item(item, "item").hid if item else None,
            "group_hid": run.group(group).hid if group else None,
        }

    def find(self, run: Run, values: Mapping[str, Any]) -> Any | None:
        """Match a row to an address: by whose it is, the address and its network."""
        try:
            address = addresses.canonical(values.get("address"))
        except ValueError:
            return None
        holder = self._holder(run, values)
        if sum(1 for hid in holder.values() if hid) != 1:
            return None
        network = values.get("network")
        found = list(
            run.db.scalars(
                select(Address)
                .where(
                    Address.item_hid == holder["item_hid"]
                    if holder["item_hid"]
                    else Address.group_hid == holder["group_hid"],
                    Address.address == address,
                    Address.network_hid == run.network(network).hid
                    if network
                    else Address.network_hid.is_(None),
                )
                .limit(2)
            )
        )
        if len(found) > 1:
            raise Invalid(
                "more than one address answers to this row",
                {"address": "this record has the address twice under this network; give the HID"},
            )
        return found[0] if found else None

    def key(self, values: Mapping[str, Any], record: Any | None) -> str:
        named = [values.get(name) for name in ("item", "group", "address", "network")]
        return " ".join(str(part) for part in named if part) or (
            record.address if record is not None else ""
        )

    def write(self, run: Run, record: Any | None, values: Mapping[str, Any], new: bool) -> Any:
        given = _plain_fields(values, ("address", "role", "is_primary"))
        if "network" in values:
            network = values["network"]
            given["network_hid"] = run.network(network).hid if network is not None else None
        if given.get("is_primary", _MISSING) is None:
            given["is_primary"] = False
        if record is None:
            given.update(self._holder(run, values))
            return addresses.create_address(run.db, run.context, _new(given))
        if "item" in values or "group" in values:
            given.update(self._holder(run, values))
        return addresses.update_address(run.db, run.context, record.hid, record.row_version, given)

    def read(self, db: Session, found: list[Any], own: bool = True) -> list[dict[str, Any]]:
        its_items = _by_hid(db, Item, {address.item_hid for address in found})
        its_groups = _by_hid(db, DeviceGroup, {address.group_hid for address in found})
        networks = _by_hid(db, Network, {address.network_hid for address in found})
        named = items.reference_texts(db, list(its_items.values()))
        return [
            {
                **_kept(address),
                "item": named[address.item_hid] if address.item_hid else None,
                "group": items.name_or_hid(its_groups[address.group_hid].name, address.group_hid)
                if address.group_hid
                else None,
                "address": address.address,
                "network": items.name_or_hid(
                    networks[address.network_hid].label, address.network_hid
                )
                if address.network_hid
                else None,
                "role": address.role,
                "is_primary": address.is_primary,
                "family": addresses.family(address.address),
            }
            for address in found
        ]


ENTITIES: Mapping[str, Entity] = {
    entity.name: entity
    for entity in (
        Tags(),
        Vendors(),
        CatalogEntries(),
        Regions(),
        Sites(),
        Locations(),
        Contacts(),
        ContactAssignments(),
        Owners(),
        OwnerMembers(),
        Networks(),
        Items(),
        DeviceGroups(),
        DeviceGroupMembers(),
        Addresses(),
    )
}
# The order in which files are loaded into an empty database: a record after the ones it
# names. Addresses come last, because a group has addresses too.
LOAD_ORDER = (
    "tags",
    "vendors",
    "catalog_entries",
    "regions",
    "sites",
    "locations",
    "contacts",
    "contact_assignments",
    "owners",
    "owner_members",
    "networks",
    "items",
    "device_groups",
    "device_group_members",
    "addresses",
)


def entity(name: Any) -> Entity:
    """Return the entity with a name, written with underscores or with hyphens."""
    wanted = records.key(name).replace("-", "_") if isinstance(name, str) else ""
    found = ENTITIES.get(wanted)
    if found is None:
        raise Invalid("there is no such entity", {"entity": f"one of {', '.join(LOAD_ORDER)}"})
    return found
