"""The routes of references (P-158 to P-162): files kept by hirdir and links to files
kept elsewhere, the records each is on, and what a record lists.

An upload sends the file itself as the body of the request, as an import does (D-80),
and is written into the store as it arrives. A download is the content, byte for byte,
served so that a browser downloads it and runs nothing of it.
"""

from typing import Annotated, Any, cast
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from hirdir.api import lists
from hirdir.api import reference_schemas as s
from hirdir.api.deps import Audit, Db, Inventory, Viewer
from hirdir.api.idempotent import IdempotentRoute
from hirdir.api.schemas import Page
from hirdir.db import dialect
from hirdir.db.models import ReferenceFile, User
from hirdir.domain import idempotency
from hirdir.domain import references as refs
from hirdir.domain.references import Holder, Listed
from hirdir.io import files, tables
from hirdir.io.store import Incoming, OverLimit, Store

# An upload takes no Idempotency-Key: content that a record has already is refused
# there, so an upload sent twice makes no second record (P-160).


def _no_key(request: Request) -> None:
    if idempotency.HEADER in request.headers:
        raise idempotency.refuse(
            "an upload does not take it: a file that a record has already is refused there"
        )


references = APIRouter(prefix="/reference-files", tags=["References"], route_class=IdempotentRoute)
uploads = APIRouter(prefix="/reference-files", tags=["References"], dependencies=[Depends(_no_key)])
holders = APIRouter()

# What the content of a download says of itself, so that nothing of it runs (P-159).
CONTENT_POLICY = "sandbox; default-src 'none'"
UPLOAD_BODY = {
    "requestBody": {
        "required": True,
        "description": "The file itself, as it is: its extension, in `file_name`, says what it is.",
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    }
}
DOWNLOAD: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "The content, byte for byte, as an attachment with its file name.",
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    }
}


def _store(request: Request) -> Store:
    return request.app.state.store


async def _received(request: Request) -> Incoming:
    """Write the body of an upload into the store's incoming directory as it arrives,
    and refuse one over the limit: the rest of it is read and thrown away, so that the
    proxy in front, still sending, is answered rather than cut off."""
    limit = request.app.state.config.max_reference_bytes
    content = await run_in_threadpool(_store(request).receive, limit)
    try:
        async for piece in request.stream():
            await run_in_threadpool(content.write, piece)
    except OverLimit:
        async for _ in request.stream():
            pass
        raise files.TooLarge(
            f"a reference file is at most {limit // (1024 * 1024)} MB", {"file": "too large"}
        ) from None
    except BaseException:
        content.discard()
        raise
    return content


def _username(db: Db, hid: str | None) -> str | None:
    user = db.get(User, hid) if hid else None
    return user.username if user else None


def _record(db: Db, store: Store, reference: ReferenceFile) -> dict[str, Any]:
    return {
        "hid": reference.hid,
        "title": reference.title,
        "kind": reference.kind,
        "form": refs.form(reference),
        "notes": reference.notes,
        "url": reference.url,
        "file_name": reference.file_name,
        "media_type": reference.media_type,
        "size_bytes": reference.size_bytes,
        "sha256": reference.sha256,
        "shown_in_page": refs.shown_in_page(reference),
        "content_missing": refs.content_missing(store, reference),
        "attachments": [
            s.ReferenceRecord(
                hid=attachment.hid,
                record_type=cast(s.HolderKind, holder.kind),
                record_hid=holder.hid,
                label=label,
            )
            for attachment, holder, label in refs.attachments(db, reference)
        ],
        "attachment_count": len(reference.attachments),
        "row_version": reference.row_version,
        "created_at": reference.created_at,
        "created_by": reference.created_by,
        "created_by_name": _username(db, reference.created_by),
        "updated_at": reference.updated_at,
        "updated_by": reference.updated_by,
        "updated_by_name": _username(db, reference.updated_by),
    }


def reference_out(db: Db, store: Store, reference: ReferenceFile) -> s.ReferenceFileOut:
    """Return a reference as the API answers it."""
    db.flush()
    return s.ReferenceFileOut(**_record(db, store, reference))


def listed_out(db: Db, store: Store, one: Listed) -> s.ListedReference:
    """Return a reference as a record lists it."""
    return s.ListedReference(
        **_record(db, store, one.reference),
        attachment_hid=one.attachment_hid,
        source=cast(s.ReferenceSource, one.source),
        source_hid=one.source_hid,
        source_label=one.source_label,
    )


# --- the references ------------------------------------------------------------------


@references.get("")
def list_references(
    request: Request,
    _: Viewer,
    db: Db,
    kind: Annotated[str | None, Query(max_length=40)] = None,
    form: s.ReferenceForm | None = None,
    title: Annotated[
        str | None, Query(max_length=200, description="What the title holds, without case.")
    ] = None,
    sort: Annotated[list[str] | None, lists.sort_of(tables.REFERENCE_FILES)] = None,
    limit: lists.Limit = lists.DEFAULT_LIMIT,
    offset: lists.Offset = 0,
) -> Page[s.ReferenceFileOut]:
    """List every reference, by title unless a sort says otherwise."""
    query = refs.matching(kind=kind, form_=form, title=title)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    arrange = tables.arrange(tables.REFERENCE_FILES, sort)
    if arrange is not None:
        query = arrange(query)
    page = db.scalars(
        query.order_by(dialect.folded(ReferenceFile.title), ReferenceFile.hid)
        .limit(limit)
        .offset(offset)
    )
    store = _store(request)
    return Page(
        items=[s.ReferenceFileOut(**_record(db, store, one)) for one in page],
        total=total,
        limit=limit,
        offset=offset,
    )


@uploads.post("", status_code=201, openapi_extra=UPLOAD_BODY)
async def upload_reference(
    request: Request,
    _: Inventory,
    context: Audit,
    db: Db,
    title: Annotated[str, Query(max_length=200)],
    kind: Annotated[str, Query(max_length=40, description="A value of `reference_kind`.")],
    file_name: Annotated[
        str, Query(max_length=255, description="Its name, whose extension says what it is.")
    ],
    attach_to: Annotated[
        list[str],
        Query(
            max_length=1000,
            description="The HID of a record it goes on, once for each: a catalog entry, a "
            "region, a site, a location, a circuit or an item.",
        ),
    ],
    notes: Annotated[str | None, Query(max_length=10_000)] = None,
) -> s.ReferenceFileOut:
    """Upload a file and put it on the records it is for.

    The file is the body of the request. Its extension must be one that the setting
    `reference_file_types` takes, and its content what the extension says; a file over
    `max_reference_megabytes` is a `413`. Content that one of the records has already,
    under any reference, is a `409` that names that reference.
    """
    store = _store(request)
    content = await _received(request)
    try:
        reference = await run_in_threadpool(
            refs.upload,
            db,
            context,
            store,
            content,
            title=title,
            kind=kind,
            file_name=file_name,
            attach_to=attach_to,
            notes=notes,
        )
    finally:
        content.discard()
    return reference_out(db, store, reference)


@references.post("/links", status_code=201)
def make_link(
    request: Request, body: s.ReferenceLinkNew, _: Inventory, context: Audit, db: Db
) -> s.ReferenceFileOut:
    """Make a link to a file that is kept elsewhere, and put it on the records it is for."""
    reference = refs.make_link(db, context, **body.model_dump())
    return reference_out(db, _store(request), reference)


@references.get("/{hid}")
def get_reference(request: Request, hid: str, _: Viewer, db: Db) -> s.ReferenceFileOut:
    """Return one reference, with the records it is on."""
    return s.ReferenceFileOut(**_record(db, _store(request), refs.get(db, hid)))


@references.patch("/{hid}")
def update_reference(
    request: Request, hid: str, body: s.ReferencePatch, _: Inventory, context: Audit, db: Db
) -> s.ReferenceFileOut:
    """Change the title, the kind or the notes of a reference, or the address of a link."""
    fields = body.model_dump(exclude={"row_version"}, exclude_unset=True)
    reference = refs.update(db, context, hid, fields, body.row_version)
    return reference_out(db, _store(request), reference)


@uploads.put("/{hid}/content", openapi_extra=UPLOAD_BODY)
async def replace_content(
    request: Request,
    hid: str,
    _: Inventory,
    context: Audit,
    db: Db,
    file_name: Annotated[str, Query(max_length=255)],
    row_version: int,
) -> s.ReferenceFileOut:
    """Put a new edition of a file in place of the one it had, on every record it is on.

    The reference keeps its HID, title, kind and records. The content it had is erased,
    unless another reference holds the same. It is checked as an upload is.
    """
    store = _store(request)
    content = await _received(request)
    try:
        reference = await run_in_threadpool(
            refs.replace_content,
            db,
            context,
            store,
            hid,
            content,
            file_name=file_name,
            row_version=row_version,
        )
    finally:
        content.discard()
    return reference_out(db, store, reference)


@references.get("/{hid}/content", response_class=FileResponse, responses=DOWNLOAD)
def download_reference(request: Request, hid: str, _: Viewer, context: Audit, db: Db) -> Any:
    """Download a file, byte for byte. It is an audit event, `download`.

    It comes as an attachment with its file name, with `X-Content-Type-Options: nosniff`
    and a content security policy that lets nothing of it run. A link has no content,
    a `422`; content missing after a restore is a `404` that says so.
    """
    store = _store(request)
    reference = refs.opened(db, context, store, hid)
    name = reference.file_name or "file"
    fallback = name.encode("ascii", "replace").decode().replace('"', "'").replace("?", "_")
    return FileResponse(
        store.path_of(reference.sha256 or ""),
        media_type=reference.media_type,
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name)}"
            ),
            "Content-Security-Policy": CONTENT_POLICY,
        },
    )


@references.delete("/{hid}", status_code=204)
def erase_reference(request: Request, hid: str, _: Inventory, context: Audit, db: Db) -> None:
    """Erase a reference from every record it is on, and its content with it unless
    another reference holds the same. The backups on the server keep a copy until they
    are rotated out. The audit event holds what it was."""
    refs.erase(db, context, _store(request), hid)


@references.post("/{hid}/attachments")
def attach_reference(
    request: Request, hid: str, body: s.ReferenceAttach, _: Inventory, context: Audit, db: Db
) -> s.ReferenceFileOut:
    """Put a reference on more records. A record that has it already is passed over; one
    that has the same content under another reference is a `409`."""
    reference = refs.attach(db, context, hid, body.records)
    return reference_out(db, _store(request), reference)


@references.delete("/{hid}/attachments/{attachment_hid}")
def detach_reference(
    request: Request, hid: str, attachment_hid: str, _: Inventory, context: Audit, db: Db
) -> s.Detached:
    """Take a reference off one record. Taken off the last record it is on, it is erased
    with its content, and the answer says so."""
    return s.Detached(erased=refs.detach(db, context, _store(request), hid, attachment_hid))


# --- what a record lists -------------------------------------------------------------

HOLDERS = (
    ("/catalog-entries", "catalog_entry", "Catalog", "its own"),
    ("/regions", "region", "Geography", "its own, then those of each region above it"),
    (
        "/sites",
        "site",
        "Geography",
        "its own, then those of its region and of each region above it",
    ),
    (
        "/locations",
        "location",
        "Geography",
        "its own, then those of the locations above it, of its site and of each region outward",
    ),
    ("/circuits", "circuit", "Circuits", "its own"),
    (
        "/items",
        "item",
        "Items",
        "its own, then those of its model, then those of the location it is at in force "
        "and of each place above it",
    ),
)


def _lister(kind: str, lists_what: str) -> Any:
    def list_of_record(
        request: Request,
        hid: str,
        _: Viewer,
        db: Db,
        limit: lists.Limit = lists.DEFAULT_LIMIT,
        offset: lists.Offset = 0,
    ) -> Page[s.ListedReference]:
        holder: Holder = refs.get_holder(db, kind, hid)
        found = refs.listing(db, holder)
        store = _store(request)
        return Page(
            items=[listed_out(db, store, one) for one in found[offset : offset + limit]],
            total=len(found),
            limit=limit,
            offset=offset,
        )

    list_of_record.__doc__ = (
        f"List the references a {kind.replace('_', ' ')} has: {lists_what}, nearest "
        "first, each once, and by title within a level."
    )
    list_of_record.__name__ = f"list_references_of_{kind}"
    return list_of_record


for prefix, kind, tag, lists_what in HOLDERS:
    holders.add_api_route(
        f"{prefix}/{{hid}}/references",
        _lister(kind, lists_what),
        methods=["GET"],
        tags=[tag],
        response_model=Page[s.ListedReference],
    )

ROUTERS = (uploads, references, holders)
