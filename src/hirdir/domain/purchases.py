"""Purchase requests, their lines, and receiving.

A request and its lines are not inventory: a line is a model and a number, before any
serial number is known. Receiving a line says which items arrived, and creates them.
How many have arrived on a line is the number of items that name it, counted when it
is read and stored nowhere, so it cannot drift from the items.

A line keeps the part number and the description that procurement gave it. One with
no model is not tracked (D-172): cable ties, a monitor. It takes no item, is in no
count, and is not waited for. Its model is corrected at any time (D-171): where items
have arrived on it, the change says whether they follow it (D-186).
"""

from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import Session

from hirdir import clock, ids
from hirdir.db import dialect
from hirdir.db.models import CatalogEntry, Item, Location, PurchaseLine, PurchaseRequest, Site
from hirdir.domain import items, records, settings
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Conflict, Existing, Invalid, NotFound

RECORD_TYPE = "purchase_request"
LINE_TYPE = "purchase_line"
STATUSES = ("draft", "pending", "ordered", "received", "cancelled")
PENDING = STATUSES[1]
NOT_RECEIVING = items.NOT_RECEIVING
MAX_LINES = 1000
# The longest number of a line that is looked for: no request has a line beyond it.
MAX_LINE_DIGITS = 6
FIELDS = ("reference", "requested_on", "status", "notes")
LINE_FIELDS = (
    "request_hid",
    "line",
    "catalog_entry_hid",
    "part_number",
    "description",
    "quantity",
    "destination_site_hid",
    "expected_on",
    "notes",
)
SEPARATOR = "/"
# The longest part number a line keeps: as long as a PID.
PART_NUMBER = 100
MAX_QUANTITY = 100_000
RECEIVED_AS = "Delivered"
# What becomes of the items that arrived on a line whose model is corrected: they are
# given the corrected model too, or they stay as they are and are then reported.
FOLLOW, STAY = "follow", "stay"
ON_A_CORRECTION = (FOLLOW, STAY)
# What tells one item that arrived from another, and what else a receipt may say of it.
IDENTITY = ("serial_number", "asset_tag", "name")
RECEIVABLE = (*IDENTITY, "hostname", "mac_address", "comments")


# --- requests ------------------------------------------------------------------------


def get_request(db: Session, hid: str) -> PurchaseRequest:
    """Return the purchase request with hid."""
    request = db.get(PurchaseRequest, hid)
    if request is None:
        raise NotFound(f"there is no purchase request {hid}")
    return request


def find_request(db: Session, text: str) -> PurchaseRequest | None:
    """Return the request that text names: by its HID or by its reference."""
    text = text.strip()
    if ids.is_hid(text):
        found = db.get(PurchaseRequest, text)
        if found is not None:
            return found
    return db.scalar(
        select(PurchaseRequest).where(PurchaseRequest.reference_key == records.key(text))
    )


def the_request(db: Session, text: str, field: str) -> PurchaseRequest:
    """Return the request text names, or refuse a reference that there is not."""
    found = find_request(db, text)
    if found is None:
        raise Invalid(
            "there is no such purchase request", {field: f"there is no purchase request {text}"}
        )
    return found


def _checked(
    db: Session, fields: dict[str, Any], request: PurchaseRequest | None
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if "reference" in fields:
        reference = records.clean(fields["reference"])
        if reference is None or SEPARATOR in reference or ";" in reference:
            raise Invalid(
                "the reference is not acceptable",
                {"reference": f"not blank, with no {SEPARATOR}, which names a line of it"},
            )
        taken = db.scalar(
            select(PurchaseRequest).where(PurchaseRequest.reference_key == records.key(reference))
        )
        if taken is not None and (request is None or taken.hid != request.hid):
            raise Conflict(
                f"there is already a purchase request {taken.reference}",
                {"reference": "another purchase request has this reference"},
                Existing(RECORD_TYPE, taken.hid, taken.reference),
            )
        values["reference"] = reference
        values["reference_key"] = records.key(reference)
    if "requested_on" in fields:
        values["requested_on"] = records.checked_day("requested_on", fields["requested_on"])
    if "status" in fields:
        values["status"] = records.checked_choice(fields["status"] or PENDING, STATUSES, "status")
    if "notes" in fields:
        values["notes"] = records.clean(fields["notes"])
    return values


def create_request(db: Session, context: AuditContext, fields: dict[str, Any]) -> PurchaseRequest:
    """Create a purchase request. Its lines are added to it."""
    request = PurchaseRequest(**_checked(db, {"reference": None, **fields}, None))
    records.created(db, context, RECORD_TYPE, request, FIELDS)
    return request


def update_request(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> PurchaseRequest:
    """Change a purchase request. Its status is what a person says of it."""
    request = get_request(db, hid)
    records.apply(db, context, RECORD_TYPE, request, row_version, _checked(db, fields, request))
    return request


# --- lines ---------------------------------------------------------------------------


def get_line(db: Session, hid: str) -> PurchaseLine:
    """Return the purchase line with hid."""
    line = db.get(PurchaseLine, hid)
    if line is None:
        raise NotFound(f"there is no purchase line {hid}")
    return line


def line_name(request: PurchaseRequest, line: PurchaseLine) -> str:
    """Return how a line is named: the reference of its request, and its number there."""
    return f"{request.reference}{SEPARATOR}{line.line}"


def find_line(db: Session, text: str) -> PurchaseLine | None:
    """Return the line that text names: by its HID, or as `RITM0012345/2`."""
    text = text.strip()
    if ids.is_hid(text):
        found = db.get(PurchaseLine, text)
        if found is not None:
            return found
    reference, separator, number = text.rpartition(SEPARATOR)
    number = number.strip()
    if not separator or not number.isascii() or not number.isdigit():
        return None
    if len(number) > MAX_LINE_DIGITS:
        return None
    request = find_request(db, reference)
    if request is None:
        return None
    return db.scalar(
        select(PurchaseLine).where(
            PurchaseLine.request_hid == request.hid, PurchaseLine.line == int(number)
        )
    )


def the_line(db: Session, text: str, field: str) -> PurchaseLine:
    """Return the line text names, or refuse a name that there is not."""
    found = find_line(db, text)
    if found is None:
        raise Invalid(
            "there is no such purchase line",
            {field: f"there is no purchase line {text}; a line is named as RITM0012345/2"},
        )
    return found


def part_key(text: str) -> str:
    """Return a part number as it is matched to a PID: without case, surrounding space,
    or the `=` that ends the part number of a spare."""
    return records.key(records.key(text).removesuffix("="))


def models_of_part(db: Session, text: str, vendor_hid: str | None) -> list[CatalogEntry]:
    """Return the models whose PID is the part number text, among the models of a
    vendor where one is named and among all where none is (D-186). An exact PID is
    looked for first; only where none matches exactly is the `=` of a spare left out,
    on either side, so that a model and its spare twin each find their own."""
    exact = records.key(text)
    wanted = part_key(text)
    if not wanted:
        return []

    def among(keys: list[str]) -> list[CatalogEntry]:
        query = select(CatalogEntry).where(CatalogEntry.pid_key.in_(keys))
        if vendor_hid is not None:
            query = query.where(CatalogEntry.vendor_hid == vendor_hid)
        return list(db.scalars(query.order_by(CatalogEntry.vendor_hid, CatalogEntry.pid_key)))

    return among([exact]) or among([wanted, f"{wanted}="])


def tracked(line: PurchaseLine) -> bool:
    """Say whether a line is tracked: whether it has a model (D-172)."""
    return line.catalog_entry_hid is not None


def pending(line: PurchaseLine, arrived: int) -> int:
    """Return what is still to come on a line: nothing on one that is not tracked,
    which is not waited for."""
    return line.quantity - arrived if tracked(line) else 0


def of_another_model(item_model: str | None, line_model: str | None) -> bool:
    """Say whether an item on a line is of another model than the line's: what 0.6.0
    let in (D-161), or an item left as it was when its line was corrected (D-171). An
    item with no model is of another. `another_model` is the same test as SQL."""
    return line_model is not None and item_model != line_model


def another_model(item: Any, line: Any) -> ColumnElement[bool]:
    """Return the test that an item on a line is of another model than the line's."""
    return and_(
        line.catalog_entry_hid.is_not(None),
        or_(item.catalog_entry_hid.is_(None), item.catalog_entry_hid != line.catalog_entry_hid),
    )


def received(db: Session, line_hids: Sequence[str]) -> dict[str, int]:
    """Return how many items name each line: what has arrived on it."""
    counts = dict.fromkeys(line_hids, 0)
    if line_hids:
        counted = db.execute(
            select(Item.purchase_line_hid, func.count())
            .where(Item.purchase_line_hid.in_(line_hids))
            .group_by(Item.purchase_line_hid)
        )
        for hid, count in counted:
            if hid is not None:
                counts[hid] = count
    return counts


def lines_of(db: Session, request_hids: Sequence[str]) -> dict[str, list[PurchaseLine]]:
    """Return the lines of each request, by their numbers."""
    found: dict[str, list[PurchaseLine]] = {hid: [] for hid in request_hids}
    if request_hids:
        for line in db.scalars(
            select(PurchaseLine)
            .where(PurchaseLine.request_hid.in_(request_hids))
            .order_by(PurchaseLine.line)
        ):
            found[line.request_hid].append(line)
    return found


def _whole(name: str, value: Any, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise Invalid(f"{name} is not acceptable", {name: f"a whole number from {low} to {high}"})
    return value


def _checked_model(
    db: Session, value: Any, line: PurchaseLine | None, on_it: Any
) -> tuple[str | None, str | None]:
    """Return the model a line is given, and what becomes of the items that have
    arrived on it: None where nothing has arrived or the model stays as it is."""
    name = "catalog_entry_hid"
    hid = records.linked(db, CatalogEntry, name, value, line, "catalog entry", kept=True)
    if line is None or hid == line.catalog_entry_hid:
        return hid, None
    arrived = received(db, [line.hid])[line.hid]
    if not arrived:
        return hid, None
    if hid is None:
        raise Invalid(
            "items have arrived on this line",
            {name: f"{arrived} items have arrived on this line, which keeps a model"},
        )
    if on_it not in ON_A_CORRECTION:
        raise Invalid(
            "items have arrived on this line",
            {
                "items": f"{arrived} items have arrived on this line: say whether they are "
                f"given the corrected model too, {FOLLOW}, or stay as they are, {STAY}"
            },
        )
    return hid, on_it


def _checked_line(
    db: Session, fields: dict[str, Any], line: PurchaseLine | None, request_hid: str
) -> tuple[dict[str, Any], str | None]:
    """Return the values of a line as they are to be stored, and what becomes of the
    items on it where its model is corrected after they arrived."""
    values: dict[str, Any] = {}
    corrected = None
    if "catalog_entry_hid" in fields:
        values["catalog_entry_hid"], corrected = _checked_model(
            db, fields["catalog_entry_hid"], line, fields.get("items")
        )
    for name in ("part_number", "description"):
        if name in fields:
            values[name] = records.clean(fields[name])
    if len(values.get("part_number") or "") > PART_NUMBER:
        raise Invalid(
            "the part number is not acceptable",
            {"part_number": f"at most {PART_NUMBER} characters"},
        )
    if "quantity" in fields:
        quantity = _whole("quantity", fields["quantity"], 0, MAX_QUANTITY)
        arrived = received(db, [line.hid])[line.hid] if line is not None else 0
        least = max(arrived, 0 if line is not None else 1)
        if quantity < least or (line is None and quantity < 1):
            raise Invalid(
                "the quantity is not acceptable",
                {
                    "quantity": f"{arrived} have arrived on this line; not fewer than that"
                    if arrived
                    else "1 or more for a new line"
                },
            )
        values["quantity"] = quantity
    if "destination_site_hid" in fields:
        values["destination_site_hid"] = records.linked(
            db,
            Site,
            "destination_site_hid",
            fields["destination_site_hid"],
            line,
            "site",
            kept=True,
        )
    if "expected_on" in fields:
        values["expected_on"] = records.checked_day("expected_on", fields["expected_on"])
    if "notes" in fields:
        values["notes"] = records.clean(fields["notes"])
    if fields.get("line") is not None:
        number = _whole("line", fields["line"], 1, MAX_QUANTITY)
        if line is None or number != line.line:
            taken = db.scalar(
                select(PurchaseLine).where(
                    PurchaseLine.request_hid == request_hid, PurchaseLine.line == number
                )
            )
            if taken is not None:
                raise Conflict(
                    f"the request already has a line {number}",
                    {"line": "another line of this request has this number"},
                )
        values["line"] = number

    def final(name: str) -> Any:
        return values.get(name, getattr(line, name) if line is not None else None)

    if final("catalog_entry_hid") is None and final("part_number") is None:
        raise Invalid(
            "a line has a model or a part number",
            {
                "catalog_entry_hid": "a model of the catalog, or a part_number as procurement "
                "gave it for what this inventory does not track"
            },
        )
    return values, corrected


def add_line(
    db: Session, context: AuditContext, request_hid: str, fields: dict[str, Any]
) -> PurchaseLine:
    """Add a line to a request: a model or a part number, and how many. Left out, its
    number is the next. A line with no model is not tracked."""
    # The next number is read and then taken, so nobody else may be taking it meanwhile.
    dialect.hold_other_writers(db)
    request = get_request(db, request_hid)
    values, _ = _checked_line(
        db, {"catalog_entry_hid": None, "quantity": None, **fields}, None, request.hid
    )
    held = db.scalar(
        select(func.count())
        .select_from(PurchaseLine)
        .where(PurchaseLine.request_hid == request.hid)
    )
    if (held or 0) >= MAX_LINES:
        raise Invalid(
            "the request has too many lines", {"line": f"at most {MAX_LINES} lines to a request"}
        )
    if "line" not in values:
        highest = db.scalar(
            select(func.max(PurchaseLine.line)).where(PurchaseLine.request_hid == request.hid)
        )
        values["line"] = (highest or 0) + 1
    line = PurchaseLine(request_hid=request.hid, **values)
    records.created(db, context, LINE_TYPE, line, LINE_FIELDS)
    return line


def update_line(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> PurchaseLine:
    """Change a line. Its quantity is never below what has arrived on it: a line is
    taken back by lowering it to that.

    Its model is corrected at any time. Where items have arrived on it, `items` says
    what becomes of them: `follow` gives each that is not retired the corrected model,
    in the same change and each with its audit event, and `stay` leaves them as they
    are, to be reported as of another model than their line's. A line keeps a model
    while anything has arrived on it.
    """
    dialect.hold_other_writers(db)
    line = get_line(db, hid)
    if "request_hid" in fields and fields["request_hid"] != line.request_hid:
        raise Invalid(
            "a line stays with its request", {"request_hid": "add a line to the other request"}
        )
    if fields.get("items") is not None and fields["items"] not in ON_A_CORRECTION:
        raise Invalid(
            "what becomes of the items is not acceptable", {"items": f"{FOLLOW} or {STAY}"}
        )
    plain = {name: value for name, value in fields.items() if name != "request_hid"}
    values, corrected = _checked_line(db, plain, line, line.request_hid)
    given_model = values.get("catalog_entry_hid", line.catalog_entry_hid)
    if (
        line.catalog_entry_hid is not None
        and given_model != line.catalog_entry_hid
        and line.part_number is None
        and values.get("part_number") is None
    ):
        # A line with no part number of its own, one of 0.6.0 or one made by hand, keeps
        # the PID of the model it is corrected from as the part number procurement gave
        # it: loading procurement's file again then finds it unchanged and leaves the
        # correction as it is (the owner's answer of 2026-11-15).
        was = db.get(CatalogEntry, line.catalog_entry_hid)
        if was is not None:
            values["part_number"] = was.pid
    records.apply(db, context, LINE_TYPE, line, row_version, values)
    db.flush()
    if corrected == FOLLOW:
        _follow(db, context, line)
    # Lowered to what has arrived, or no longer tracked, the line is waited for no more.
    items.settle_request(db, context, line.request_hid)
    return line


def _follow(db: Session, context: AuditContext, line: PurchaseLine) -> None:
    """Give each item on a line that is not retired the line's model, each by a change
    of its own. What an item holds as its own stays its own, and what it inherited it
    has from the corrected model from then on: nothing inherited is held by an item."""
    astray = db.scalars(
        select(Item)
        .where(
            Item.purchase_line_hid == line.hid,
            Item.record_status != "retired",
            or_(
                Item.catalog_entry_hid.is_(None),
                Item.catalog_entry_hid != line.catalog_entry_hid,
            ),
        )
        .order_by(Item.hid)
    ).all()
    for item in astray:
        items.update_item(
            db, context, item.hid, item.row_version, {"catalog_entry_hid": line.catalog_entry_hid}
        )


def receive(
    db: Session,
    context: AuditContext,
    line_hid: str,
    row_version: int,
    arrived: Sequence[dict[str, Any]],
    quantity: int = 0,
    delivered_on: date | None = None,
    location_hid: str | None = None,
) -> tuple[PurchaseLine, list[Item]]:
    """Receive items on a line: create each in Delivered, of the line's model, naming
    the line. Either all of them are created or none is.

    `arrived` is the items that are known by something, a serial number, an asset tag
    or a name. `quantity` is how many more arrived that nothing is known of yet: each
    is given a name made from its line and its place on it, to be known by until it
    has a serial number.
    """
    dialect.hold_other_writers(db)
    line = get_line(db, line_hid)
    request = get_request(db, line.request_hid)
    if request.status in NOT_RECEIVING:
        raise Invalid(
            f"the request is {request.status}",
            {"status": f"a request that is {request.status} receives nothing"},
        )
    if not tracked(line):
        raise Invalid(
            "the line is not tracked",
            {"items": "a line with no model takes no item: match it to a model first"},
        )
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
        raise Invalid("the quantity is not acceptable", {"quantity": "a whole number, 0 or more"})
    count = len(arrived) + quantity
    if not count:
        raise Invalid(
            "nothing to receive", {"items": "say which items arrived, or how many, as quantity"}
        )
    settings.check_items(db, count, "items")
    records.checked_day("delivered_on", delivered_on)
    if location_hid is not None:
        records.linked(db, Location, "location_hid", location_hid, None, "location")
    before = received(db, [line.hid])[line.hid]
    if before + count > line.quantity:
        left = line.quantity - before
        raise Invalid(
            "more than the line has still to come",
            {"items": f"{left} of {line.quantity} are still to come; raise the quantity first"},
        )
    if line.row_version != row_version:
        records.touch(line, context, row_version)
    day = delivered_on or clock.today(settings.time_zone(db))
    known: list[dict[str, Any]] = []
    for place, one in enumerate(arrived):
        given = {name: one[name] for name in RECEIVABLE if one.get(name) not in (None, "")}
        if not any(name in given for name in IDENTITY):
            raise Invalid(
                "an item needs something to know it by",
                {f"items.{place}.serial_number": "a serial number, an asset tag or a name"},
            )
        known.append(given)
    # What nothing is known of yet is named for its line and its place on it: the
    # places go on from the highest that was ever given, so that an item which was
    # taken off the line, and still has its name, is not named a second time.
    named = line_name(request, line)
    last = before + len(arrived)
    if quantity:
        for name in db.scalars(
            select(Item.name).where(Item.name.startswith(f"{named}-", autoescape=True))
        ):
            place_ = (name or "").removeprefix(f"{named}-")
            if place_.isdecimal() and len(place_) <= MAX_LINE_DIGITS + 3:
                last = max(last, int(place_))
    known += [{"name": f"{named}-{last + place:03d}"} for place in range(1, quantity + 1)]
    made: list[Item] = []
    for place, given in enumerate(known):
        try:
            made.append(
                items.create_item(
                    db,
                    context,
                    {
                        **given,
                        "catalog_entry_hid": line.catalog_entry_hid,
                        "lifecycle_state": RECEIVED_AS,
                        "delivered_on": day,
                        "location_hid": location_hid,
                        "purchase_line_hid": line.hid,
                    },
                )
            )
        except (Invalid, Conflict) as error:
            # Told with the place of the item it is about, among those that arrived.
            fields = {f"items.{place}.{name}": why for name, why in error.fields.items()}
            raise type(error)(str(error), fields) from None
    records.apply(
        db,
        context,
        LINE_TYPE,
        line,
        None,
        {},
        [change("received_quantity", before, before + len(made))],
        action="receive",
    )
    return line, made
