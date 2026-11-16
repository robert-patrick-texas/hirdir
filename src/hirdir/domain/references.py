"""References: files kept by hirdir and links to files kept elsewhere (P-158 to P-162).

A reference has a title and a kind, and is on one record or more: a catalog entry, a
region, a site, a location, a circuit or an item. A record lists its own, and those of
the records it stands under, worked out when it is read and copied nowhere: a place
those of the places above it, an item those of its model and of where it is.

A file's content is kept by `hirdir.io.store`, under its checksum, once whatever the
number of references that hold it. A reference is erased, with its content, when it
comes off the last record it is on, or when it is erased from all of them at once
(P-160): the one way, beside `hirdir admin reset`, that a record of the inventory is
deleted.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db import dialect
from hirdir.db.models import (
    ATTACHABLE,
    CatalogEntry,
    Circuit,
    Item,
    Location,
    ReferenceAttachment,
    ReferenceFile,
    Region,
    Site,
    Vendor,
)
from hirdir.domain import audit, choices, descent, file_kinds, items, records, settings
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Conflict, Invalid, NotFound
from hirdir.domain.geography import Atlas, Place
from hirdir.io import store as stores
from hirdir.io.store import Incoming, Store

# How many records one request may put a reference on (P-162), and one upload, whose
# records are named in its address, which a proxy holds to a few kilobytes.
MAX_ATTACHMENTS = 1000
MAX_UPLOAD_RECORDS = 100
KIND_LIST = "reference_kind"
TYPES_SETTING = "reference_file_types"
MAX_TITLE = 200
MAX_FILE_NAME = 255
MAX_NOTES = 10_000
RECORD = "reference_file"
FILE, LINK = "file", "link"

# The records a reference may be on: the name of each kind, its column on an
# attachment, and its table.
KINDS: dict[str, tuple[str, Any]] = {
    "catalog_entry": ("catalog_entry_hid", CatalogEntry),
    "region": ("region_hid", Region),
    "site": ("site_hid", Site),
    "location": ("location_hid", Location),
    "circuit": ("circuit_hid", Circuit),
    "item": ("item_hid", Item),
}
if tuple(column for column, _ in KINDS.values()) != ATTACHABLE:
    raise RuntimeError("the kinds of record a reference is on are not those of the table")
# Where a reference that a record lists comes from (P-158).
OWN, CATALOG = "own", "catalog"


# --- the parts of a reference ---------------------------------------------------------


def _title(value: Any) -> str:
    title = records.clean(value)
    if (
        not isinstance(title, str)
        or len(title) > MAX_TITLE
        or any(mark in title for mark in records.LINK_MARKS)
    ):
        raise Invalid(
            "the title is not acceptable",
            {"title": f"a title of 1 to {MAX_TITLE} characters, with neither < nor >"},
        )
    return title


def _notes(value: Any) -> str | None:
    notes = records.clean(value)
    if notes is not None and (not isinstance(notes, str) or len(notes) > MAX_NOTES):
        raise Invalid(
            "the notes are not acceptable", {"notes": f"at most {MAX_NOTES:,} characters"}
        )
    return notes


def _url(value: Any) -> str:
    url = records.checked_url("url", value)
    if url is None:
        raise Invalid("a link needs an address", {"url": "an address that begins with https://"})
    return url


def taken_types(db: Session) -> list[str]:
    """Return the extensions of the files a reference may be, as the setting has them."""
    return list(settings.value(db, TYPES_SETTING))


def checked_file_name(db: Session, value: Any) -> tuple[str, str]:
    """Return a file's name, without any directory it was sent with, and its extension,
    or refuse a name whose extension is not taken (P-159)."""
    name = records.clean(value)
    if isinstance(name, str):
        name = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if (
        not isinstance(name, str)
        or not name
        or len(name) > MAX_FILE_NAME
        or any(ord(character) < 32 or ord(character) == 127 for character in name)
        or name in (".", "..")
    ):
        raise Invalid(
            "the name of the file is not acceptable",
            {"file_name": f"the name of the file, of at most {MAX_FILE_NAME} characters"},
        )
    extension = file_kinds.extension_of(name)
    if extension in file_kinds.REFUSED:
        raise Invalid(
            f"a file of the kind {extension} is never taken",
            {
                "file_name": f"{extension} is a web page, a script or a program, "
                "which is never taken"
            },
        )
    taken = taken_types(db)
    if extension not in taken:
        raise Invalid(
            f"a file of the kind {extension or 'with no extension'} is not taken",
            {
                "file_name": f"the kinds of file taken are {', '.join(taken)}; "
                f"{TYPES_SETTING} says which"
            },
        )
    return name, extension


def _checked_content(upload: Incoming, extension: str) -> None:
    if upload.size == 0:
        raise Invalid("the file is empty", {"file": "a file of at least one byte"})
    wrong = file_kinds.wrong_content(extension, upload.head)
    if wrong:
        raise Invalid(f"the file is refused: {wrong}", {"file": wrong})


# --- the records a reference is on ----------------------------------------------------


@dataclass(frozen=True)
class Holder:
    """A record that a reference may be on: its kind and the record itself."""

    kind: str
    record: Any

    @property
    def hid(self) -> str:
        return self.record.hid

    @property
    def column(self) -> str:
        return KINDS[self.kind][0]


def find_holder(db: Session, hid: Any, field: str = "attach_to") -> Holder:
    """Return the record with hid, of any of the six kinds that take references."""
    if isinstance(hid, str):
        for kind, (_, model) in KINDS.items():
            found = db.get(model, hid.strip())
            if found is not None:
                return Holder(kind, found)
    raise Invalid(
        "there is no such record to put a reference on",
        {
            field: f"{hid} is no catalog entry, region, site, location, circuit or item",
        },
    )


def get_holder(db: Session, kind: str, hid: str) -> Holder:
    """Return a record of one kind, or say there is none."""
    model = KINDS[kind][1]
    found = db.get(model, hid)
    if found is None:
        raise NotFound(f"there is no {kind.replace('_', ' ')} {hid}")
    return Holder(kind, found)


def _holders(db: Session, hids: Any, field: str, most: int = MAX_ATTACHMENTS) -> list[Holder]:
    if isinstance(hids, str):
        hids = [hids]
    if not isinstance(hids, list | tuple) or not hids:
        raise Invalid("a reference goes on a record", {field: "the HID of one record or more"})
    if len(hids) > most:
        raise Invalid(
            "too many records for one request",
            {field: f"at most {most:,} records; put it on more with its attachments"},
        )
    found: dict[str, Holder] = {}
    for hid in hids:
        holder = find_holder(db, hid, field)
        found.setdefault(holder.hid, holder)
    return list(found.values())


def _item_label(item: Item) -> str:
    return item.hostname or item.name or item.asset_tag or item.serial_number or item.hid


def label(db: Session, atlas: Atlas, holder: Holder) -> str:
    """Return how a record is named to a person: a place by its path, a model by its
    vendor and PID, a circuit and an item by their names."""
    record = holder.record
    if holder.kind == "region":
        return atlas.region_path(record.hid)
    if holder.kind == "site":
        atlas.take([record])
        return atlas.site_path(record.hid)
    if holder.kind == "location":
        atlas.take([record])
        return atlas.location_path(record.hid)
    if holder.kind == "catalog_entry":
        vendor = db.get(Vendor, record.vendor_hid)
        return f"{vendor.name} {record.pid}" if vendor else record.pid
    if holder.kind == "circuit":
        return record.enterprise_circuit_id or record.name
    return _item_label(record)


def holder_of(db: Session, attachment: ReferenceAttachment) -> Holder:
    """Return the record an attachment is on."""
    for kind, (column, model) in KINDS.items():
        hid = getattr(attachment, column)
        if hid is not None:
            return Holder(kind, db.get(model, hid))
    raise ValueError(f"the attachment {attachment.hid} is on no record")


def _attached(reference: ReferenceFile, holder: Holder) -> ReferenceAttachment | None:
    return next(
        (one for one in reference.attachments if getattr(one, holder.column) == holder.hid),
        None,
    )


def _content_on(db: Session, holder: Holder, sha256: str, other_than: str | None = None) -> Any:
    """Return a reference on a record that holds content with this checksum, if any."""
    query = (
        select(ReferenceFile)
        .join(ReferenceAttachment, ReferenceAttachment.reference_file_hid == ReferenceFile.hid)
        .where(
            getattr(ReferenceAttachment, holder.column) == holder.hid,
            ReferenceFile.sha256 == sha256,
        )
    )
    if other_than is not None:
        query = query.where(ReferenceFile.hid != other_than)
    return db.scalars(query.limit(1)).first()


def _refuse_twice(
    db: Session, holders: Iterable[Holder], sha256: str, other_than: str | None = None
) -> None:
    for holder in holders:
        there = _content_on(db, holder, sha256, other_than)
        if there is not None:
            raise Conflict(
                f"this file is on that record already, as {there.title}",
                {"file": f"the same content is reference {there.hid}, {there.title}"},
            )


def _attachment(holder: Holder, context: AuditContext) -> ReferenceAttachment:
    return ReferenceAttachment(
        **{holder.column: holder.hid}, created_by=context.actor_hid, updated_by=context.actor_hid
    )


def _where(db: Session, reference: ReferenceFile) -> list[dict[str, Any]]:
    atlas = Atlas(db)
    found = []
    for attachment in reference.attachments:
        holder = holder_of(db, attachment)
        found.append(
            {
                "record_type": holder.kind,
                "record_hid": holder.hid,
                "label": label(db, atlas, holder),
            }
        )
    return found


def _what_it_is(db: Session, reference: ReferenceFile) -> list[dict[str, Any]]:
    """The fields of a reference, for the audit event that says what it was."""
    return [
        change(name, getattr(reference, name), None)
        for name in (
            "title",
            "kind",
            "notes",
            "url",
            "file_name",
            "media_type",
            "size_bytes",
            "sha256",
        )
        if getattr(reference, name) is not None
    ] + [change("records", _where(db, reference), None)]


# --- reading --------------------------------------------------------------------------


def get(db: Session, hid: str) -> ReferenceFile:
    """Return the reference with hid."""
    reference = db.get(ReferenceFile, hid)
    if reference is None:
        raise NotFound(f"there is no reference {hid}")
    return reference


def form(reference: ReferenceFile) -> str:
    """Say whether a reference is a file or a link."""
    return LINK if reference.url is not None else FILE


def shown_in_page(reference: ReferenceFile) -> bool:
    """Say whether a reference is a picture that the web UI shows in the page."""
    return reference.file_name is not None and file_kinds.shown(
        file_kinds.extension_of(reference.file_name)
    )


def content_missing(store: Store, reference: ReferenceFile) -> bool:
    """Say whether a file's content is missing from the store, as after a restore that
    was told to go on without it."""
    return reference.sha256 is not None and not store.has(reference.sha256)


def attachments(
    db: Session, reference: ReferenceFile
) -> list[tuple[ReferenceAttachment, Holder, str]]:
    """Return each record a reference is on, with how it is named."""
    atlas = Atlas(db)
    found = []
    for attachment in sorted(reference.attachments, key=lambda one: one.created_at):
        holder = holder_of(db, attachment)
        found.append((attachment, holder, label(db, atlas, holder)))
    return found


@dataclass(frozen=True)
class Listed:
    """A reference as a record lists it: where it is attached, and how near."""

    reference: ReferenceFile
    attachment_hid: str
    source: str
    source_hid: str
    source_label: str


def _levels(db: Session, holder: Holder) -> list[tuple[str, Holder]]:
    """Return the records whose references a record lists, nearest first, each with the
    source it gives them (P-158)."""
    found: list[tuple[str, Holder]] = [(OWN, holder)]
    atlas = Atlas(db)
    if holder.kind in ("region", "site", "location"):
        place = Place(holder.kind, holder.record)
        found += [(one.level, Holder(one.level, one.record)) for one in atlas.chain(place)[1:]]
    elif holder.kind == "item":
        item = holder.record
        entry = db.get(CatalogEntry, item.catalog_entry_hid) if item.catalog_entry_hid else None
        if entry is not None:
            found.append((CATALOG, Holder("catalog_entry", entry)))
        lines = {item.hid: items.ancestors(db, item)}
        where = descent.of_items(db, [item], lines, "location_hid")[item.hid].value
        location = db.get(Location, where) if where else None
        if location is not None:
            for one in atlas.chain(Place("location", location)):
                found.append((one.level, Holder(one.level, one.record)))
    return found


def listing(db: Session, holder: Holder) -> list[Listed]:
    """Return what a record lists: its own references, then those of each record it
    stands under, nearest first, each once, at the nearest level that has it, and by
    title within a level."""
    atlas = Atlas(db)
    seen: set[str] = set()
    found: list[Listed] = []
    for source, level in _levels(db, holder):
        column = getattr(ReferenceAttachment, level.column)
        rows = db.execute(
            select(ReferenceAttachment, ReferenceFile)
            .join(ReferenceFile, ReferenceFile.hid == ReferenceAttachment.reference_file_hid)
            .where(column == level.hid)
        ).all()
        named = label(db, atlas, level)
        for attachment, reference in sorted(
            rows, key=lambda row: (records.key(row[1].title), row[1].hid)
        ):
            if reference.hid in seen:
                continue
            seen.add(reference.hid)
            found.append(Listed(reference, attachment.hid, source, level.hid, named))
    return found


# --- making a reference ---------------------------------------------------------------


def upload(
    db: Session,
    context: AuditContext,
    store: Store,
    content: Incoming,
    *,
    title: Any,
    kind: Any,
    file_name: Any,
    attach_to: Any,
    notes: Any = None,
) -> ReferenceFile:
    """Keep a file that was uploaded, and put it on the records it is for (P-158).

    The content was received already, and is checked here: its extension is one that
    is taken, and it is what its extension says. It is refused where a record it goes
    on has the same content already. The content is put in place and the record stored
    under the store's lock, so that what the database names is there.
    """
    name, extension = checked_file_name(db, file_name)
    values = {
        "title": _title(title),
        "kind": choices.checked(db, KIND_LIST, kind if isinstance(kind, str) else "", "kind"),
        "notes": _notes(notes),
    }
    _checked_content(content, extension)
    sha256 = content.finish()
    dialect.hold_other_writers(db)
    holders = _holders(db, attach_to, "attach_to", MAX_UPLOAD_RECORDS)
    _refuse_twice(db, holders, sha256)
    reference = ReferenceFile(
        **values,
        file_name=name,
        media_type=file_kinds.media_type(extension),
        size_bytes=content.size,
        sha256=sha256,
        created_by=context.actor_hid,
        updated_by=context.actor_hid,
    )
    reference.attachments = [_attachment(holder, context) for holder in holders]
    db.add(reference)
    db.flush()
    audit.record(
        db,
        context,
        "create",
        RECORD,
        reference.hid,
        [
            change(field, None, getattr(reference, field))
            for field in (
                "title",
                "kind",
                "notes",
                "file_name",
                "media_type",
                "size_bytes",
                "sha256",
            )
            if getattr(reference, field) is not None
        ]
        + [change("records", None, _where(db, reference))],
    )
    with stores.LOCK:
        store.keep(content)
        db.commit()
    return reference


def make_link(
    db: Session,
    context: AuditContext,
    *,
    title: Any,
    kind: Any,
    url: Any,
    attach_to: Any,
    notes: Any = None,
) -> ReferenceFile:
    """Make a link to a file kept elsewhere, and put it on the records it is for."""
    values = {
        "title": _title(title),
        "kind": choices.checked(db, KIND_LIST, kind if isinstance(kind, str) else "", "kind"),
        "notes": _notes(notes),
        "url": _url(url),
    }
    dialect.hold_other_writers(db)
    holders = _holders(db, attach_to, "attach_to")
    reference = ReferenceFile(**values, created_by=context.actor_hid, updated_by=context.actor_hid)
    reference.attachments = [_attachment(holder, context) for holder in holders]
    db.add(reference)
    db.flush()
    audit.record(
        db,
        context,
        "create",
        RECORD,
        reference.hid,
        [change(field, None, value) for field, value in values.items() if value is not None]
        + [change("records", None, _where(db, reference))],
    )
    return reference


# --- changing one ---------------------------------------------------------------------

EDITABLE = ("title", "kind", "notes", "url")


def update(
    db: Session, context: AuditContext, hid: str, fields: dict[str, Any], row_version: int
) -> ReferenceFile:
    """Change the title, the kind or the notes of a reference, and the address of a link."""
    reference = get(db, hid)
    values: dict[str, Any] = {}
    if "title" in fields:
        values["title"] = _title(fields["title"])
    if "kind" in fields:
        kind = fields["kind"] if isinstance(fields["kind"], str) else ""
        # A kind made inactive since stays on a reference that has it, as it does on a
        # circuit: only a new value is held to what the list offers.
        same = records.key(kind) == records.key(reference.kind)
        values["kind"] = reference.kind if same else choices.checked(db, KIND_LIST, kind, "kind")
    if "notes" in fields:
        values["notes"] = _notes(fields["notes"])
    if "url" in fields:
        if reference.url is None:
            raise Invalid(
                "a file has no address", {"url": "a file is changed by a new edition of it"}
            )
        values["url"] = _url(fields["url"])
    changes = records.differences(reference, values)
    if changes:
        records.touch(reference, context, row_version)
        for name, value in values.items():
            setattr(reference, name, value)
        audit.record(db, context, "update", RECORD, reference.hid, changes)
    elif reference.row_version != row_version:
        records.touch(reference, context, row_version)
    return reference


def replace_content(
    db: Session,
    context: AuditContext,
    store: Store,
    hid: str,
    content: Incoming,
    *,
    file_name: Any,
    row_version: int,
) -> ReferenceFile:
    """Put a new edition of a file in place of the one it had, on every record it is on
    (P-160). The content it had is erased unless another reference holds it too."""
    # The writer's place first, and the reference as it is stored now, so that a stale
    # edition is refused before its content is put in place.
    dialect.hold_other_writers(db)
    reference = get(db, hid)
    db.refresh(reference)
    if reference.sha256 is None:
        raise Invalid("a link has no content", {"file": "a link is changed by its url"})
    name, extension = checked_file_name(db, file_name)
    _checked_content(content, extension)
    sha256 = content.finish()
    holders = [holder_of(db, attachment) for attachment in reference.attachments]
    _refuse_twice(db, holders, sha256, other_than=reference.hid)
    old = reference.sha256
    values = {
        "file_name": name,
        "media_type": file_kinds.media_type(extension),
        "size_bytes": content.size,
        "sha256": sha256,
    }
    changes = records.differences(reference, values)
    if not changes:
        # The same edition again: nothing changes, but a stale version is still refused.
        content.discard()
        if reference.row_version != row_version:
            records.touch(reference, context, row_version)
        return reference
    records.touch(reference, context, row_version)
    for field, value in values.items():
        setattr(reference, field, value)
    audit.record(db, context, "replace_content", RECORD, reference.hid, changes)
    # Stored before the content is put in place: a change that collides is refused here.
    db.flush()
    with stores.LOCK:
        store.keep(content)
        db.commit()
    if old != sha256:
        store.remove_unnamed(db, [old])
    return reference


def attach(db: Session, context: AuditContext, hid: str, hids: Any) -> ReferenceFile:
    """Put a reference on more records. A record that has it already is passed over."""
    reference = get(db, hid)
    dialect.hold_other_writers(db)
    holders = _holders(db, hids, "records")
    added = [holder for holder in holders if _attached(reference, holder) is None]
    if reference.sha256 is not None:
        _refuse_twice(db, added, reference.sha256, other_than=reference.hid)
    if not added:
        return reference
    atlas = Atlas(db)
    for holder in added:
        reference.attachments.append(_attachment(holder, context))
    audit.record(
        db,
        context,
        "attach",
        RECORD,
        reference.hid,
        [
            change(
                "records",
                None,
                [
                    {"record_type": h.kind, "record_hid": h.hid, "label": label(db, atlas, h)}
                    for h in added
                ],
            )
        ],
    )
    db.flush()
    return reference


def detach(db: Session, context: AuditContext, store: Store, hid: str, attachment_hid: str) -> bool:
    """Take a reference off one record. Taken off the last record it is on, it is erased
    with its content (P-160); return whether it was."""
    reference = get(db, hid)
    dialect.hold_other_writers(db)
    attachment = next((one for one in reference.attachments if one.hid == attachment_hid), None)
    if attachment is None:
        raise NotFound(f"the reference {hid} has no attachment {attachment_hid}")
    if len(reference.attachments) == 1:
        erase(db, context, store, hid)
        return True
    holder = holder_of(db, attachment)
    audit.record(
        db,
        context,
        "detach",
        RECORD,
        reference.hid,
        [
            change(
                "records",
                [
                    {
                        "record_type": holder.kind,
                        "record_hid": holder.hid,
                        "label": label(db, Atlas(db), holder),
                    }
                ],
                None,
            )
        ],
    )
    reference.attachments.remove(attachment)
    db.flush()
    return False


def erase(db: Session, context: AuditContext, store: Store, hid: str) -> None:
    """Erase a reference from every record at once, and its content with it unless
    another reference holds the same (P-160). The audit event says what it was."""
    reference = get(db, hid)
    dialect.hold_other_writers(db)
    audit.record(db, context, "erase", RECORD, reference.hid, _what_it_is(db, reference))
    sha256 = reference.sha256
    db.delete(reference)
    db.commit()
    if sha256 is not None:
        store.remove_unnamed(db, [sha256])


def opened(db: Session, context: AuditContext, store: Store, hid: str) -> ReferenceFile:
    """Return a file to download, and record that it was (P-162). A link has no
    content, and content that is missing from the store says so."""
    reference = get(db, hid)
    if reference.sha256 is None:
        raise Invalid(
            "a link has no content to download", {"url": f"its address is {reference.url}"}
        )
    if not store.has(reference.sha256):
        raise NotFound(
            f"the content of {reference.title} is missing from the store: it was not "
            "restored with the backup it came from"
        )
    audit.record(
        db,
        context,
        "download",
        RECORD,
        reference.hid,
        [change("file_name", None, reference.file_name)],
    )
    return reference


def matching(*, kind: str | None = None, form_: str | None = None, title: str | None = None) -> Any:
    """Return the statement of every reference a list asks for, before its order."""
    query = select(ReferenceFile)
    if kind:
        query = query.where(ReferenceFile.kind == kind)
    if form_ == FILE:
        query = query.where(ReferenceFile.sha256.is_not(None))
    elif form_ == LINK:
        query = query.where(ReferenceFile.url.is_not(None))
    if title:
        query = query.where(
            dialect.folded(ReferenceFile.title).contains(records.key(title), autoescape=True)
        )
    return query
