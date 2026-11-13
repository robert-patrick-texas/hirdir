"""The records a file can carry: their columns, how a row finds its record, and how a
row is written.

Nothing here decides whether a value is acceptable. A row is written by the same
functions in `domain/` that the routes call, so a file goes through the rules that
every other door goes through. What is here is what belongs to files alone: the names
of the columns, the keys a row is matched by, and references written as people write
them, such as a vendor's name for a vendor.
"""

from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any, ClassVar, Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hirdir import ids
from hirdir.auth.roles import Role
from hirdir.db import dialect
from hirdir.db.models import CatalogEntry, Item, Owner, Tag, Vendor
from hirdir.domain import catalog, inheritance, items, lifecycle, owners, records, settings, tags
from hirdir.domain.audit import AuditContext
from hirdir.domain.errors import Invalid
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
        # The session lets go of a record that nothing else holds. These are held, so
        # that the vendor of a thousand rows is read once and not a thousand times.
        self._held: dict[str, Any] = {}

    def start_row(self) -> None:
        """Begin a row: nothing noted yet, nothing to forget."""
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
            **_plain_fields(values, ("label", "organization", "is_external", "exception_reason")),
            **_status(values, record),
        }
        if given.get("is_external", _MISSING) is None:
            given["is_external"] = False
        if record is None:
            return owners.create_owner(run.db, run.context, _new(given))
        return owners.update_owner(run.db, run.context, record.hid, record.row_version, given)

    def read(self, db: Session, found: list[Any], own: bool = True) -> list[dict[str, Any]]:
        return [
            {
                **_kept(owner),
                "label": owner.label,
                "organization": owner.organization,
                "is_external": owner.is_external,
                "exception_reason": owner.exception_reason,
                "record_status": owner.record_status,
            }
            for owner in found
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
        Column("description", limit=LONG),
        Column("comments", limit=LONG),
        Column("quantity", "integer"),
        Column("lifecycle_state", limit=20),
        Column("disposition", limit=12),
        Column("expected_online", "boolean"),
        Column("state_reason", limit=40),
        Column("owner"),
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
        *_sources((*AMOUNTS, *DATES)),
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
        **{f"effective.{name}": name for name in inheritance.ITEM_FIELDS},
    }
    renamed: ClassVar[Mapping[str, str]] = {
        "catalog_entry_hid": "pid",
        "owner_hid": "owner",
        # A move names its state and its reason otherwise than a file does.
        "to": "lifecycle_state",
        "reason": "state_reason",
    }
    not_in_bulk = frozenset(
        {"serial_number", "asset_tag", "mac_address", "name", "hostname", "fqdn"}
    )
    _direct = (*items.TEXTS, "mac_address", "quantity", *items.DAYS, "tags")

    def find(self, run: Run, values: Mapping[str, Any]) -> Any | None:
        """Match a row to an item. The first rule that applies decides.

        The order is on the data model page under "Identity and matching": the vendor,
        PID and serial number; then the asset tag; then, for a row with neither a serial
        number nor an asset tag, the name, among the items that are not retired. More
        than one candidate is an error, never a guess.
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
        name = values.get("name") or values.get("hostname")
        if serial or not name:
            return None
        named = list(
            db.scalars(
                select(Item)
                .where(
                    dialect.equals_text(func.coalesce(Item.name, Item.hostname), name.strip()),
                    Item.serial_key.is_(None),
                    Item.record_status != "retired",
                )
                .limit(2)
            )
        )
        if len(named) > 1:
            raise Invalid(
                f"more than one item is called {name}",
                {"name": "more than one item has this name; give the HID of the one meant"},
            )
        return named[0] if named else None

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
        if "owner" in values:
            owner = values["owner"]
            given["owner_hid"] = run.owner(owner).hid if owner is not None else None
        given.update(self._overrides(record, before, entry, values))
        if given.get("tags", _MISSING) is None:
            given["tags"] = []
        standing = _plain_fields(values, items.STANDING)
        if record is None:
            return items.create_item(db, context, _new({**given, **standing}))

        state = standing.get("lifecycle_state", _MISSING)
        if state is None and record.lifecycle_state is not None:
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
        if not moving:
            if reason is not _MISSING and reason != record.state_reason:
                raise Invalid(
                    "a reason is given with a move",
                    {"state_reason": "a reason is taken with a move to another lifecycle state"},
                )
            for name in ("disposition", "expected_online"):
                if name in standing and standing[name] != getattr(record, name):
                    given[name] = standing[name]
        items.update_item(db, context, record.hid, record.row_version, given)
        if moving:
            # A change of state is a transition, so that it records who, when and why.
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
        return record

    def read(self, db: Session, found: list[Any], own: bool = True) -> list[dict[str, Any]]:
        entries = _by_hid(db, CatalogEntry, {item.catalog_entry_hid for item in found})
        vendors = _by_hid(db, Vendor, {entry.vendor_hid for entry in entries.values()})
        its_owners = _by_hid(db, Owner, {item.owner_hid for item in found})
        labels = tags.labels_of(db, self.record_type, [item.hid for item in found])
        rows = []
        for item in found:
            entry = entries.get(item.catalog_entry_hid) if item.catalog_entry_hid else None
            owner = its_owners.get(item.owner_hid) if item.owner_hid else None
            in_force = inheritance.of_item(item, entry)
            row: dict[str, Any] = {
                **_kept(item),
                "vendor": vendors[entry.vendor_hid].name if entry else None,
                "pid": entry.pid if entry else None,
                **{name: getattr(item, name) for name in self._direct if name != "tags"},
                **{name: getattr(item, name) for name in items.STANDING},
                "owner": owner.label if owner else None,
                "record_status": item.record_status,
                "tags": labels[item.hid],
                "model_name": entry.model_name if entry else None,
                "kind": entry.kind if entry else None,
                "type": entry.type if entry else None,
                "function": entry.function if entry else None,
                "state_changed_at": item.state_changed_at,
            }
            for name, effective in in_force.items():
                row[name] = getattr(item, name) if own else effective.value
                row[f"{name}_source"] = effective.source
            rows.append(row)
        return rows


ENTITIES: Mapping[str, Entity] = {
    entity.name: entity for entity in (Tags(), Vendors(), CatalogEntries(), Owners(), Items())
}
# The order in which files are loaded into an empty database.
LOAD_ORDER = ("tags", "vendors", "catalog_entries", "owners", "items")


def entity(name: Any) -> Entity:
    """Return the entity with a name, written with underscores or with hyphens."""
    wanted = records.key(name).replace("-", "_") if isinstance(name, str) else ""
    found = ENTITIES.get(wanted)
    if found is None:
        raise Invalid("there is no such entity", {"entity": f"one of {', '.join(LOAD_ORDER)}"})
    return found
