"""The routes of files: importing with a preview, and exporting a list."""

from itertools import chain
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from hirdir.api import records as r
from hirdir.api import shapes
from hirdir.api.deps import Audit, Db, Inventory, Viewer
from hirdir.api.idempotent import IdempotentRoute, limited_body
from hirdir.api.lists import Limit, Offset
from hirdir.api.problems import problem
from hirdir.api.schemas import Page, Problem
from hirdir.domain.errors import Invalid
from hirdir.io import exports, imports

imports_ = APIRouter(prefix="/imports", tags=["Files"], route_class=IdempotentRoute)
exports_ = APIRouter(prefix="/exports", tags=["Files"])

FILE_TYPES = {"text/csv": "csv", "application/json": "json"}
SkipRejected = Annotated[
    bool, Query(description="Apply the rows that are not rejected, and leave the rest.")
]
OUT_OF_DATE: dict[int | str, dict[str, Any]] = {
    409: {"model": Problem, "description": "A record changed after the preview was made."}
}


def _format(request: Request, file_name: str | None) -> str:
    """Say which format a file is in, by its content type or else by its name."""
    declared = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    if declared in FILE_TYPES:
        return FILE_TYPES[declared]
    extension = (file_name or "").rpartition(".")[2].lower()
    if extension in FILE_TYPES.values():
        return extension
    raise Invalid(
        "the format of the file is not known",
        {"Content-Type": "send the file as text/csv or as application/json"},
    )


def applied(db: Db, done: imports.Applied) -> Any:
    """Return the job of an apply, or a conflict that names the rows in the way."""
    if not done.problems:
        return shapes.job_out(db, done.job)
    return problem(
        409,
        "Preview out of date",
        done.job.failure or "",
        {entry["field"]: entry["message"] for entry in done.problems},
    )


@imports_.post(
    "/preview",
    status_code=201,
    openapi_extra={
        "requestBody": {
            "required": True,
            "description": "The file itself: CSV with a header row, or JSON in its envelope.",
            "content": {
                "text/csv": {"schema": {"type": "string"}},
                "application/json": {"schema": r.ImportEnvelope.model_json_schema()},
            },
        }
    },
)
async def preview_import(
    request: Request,
    principal: Inventory,
    context: Audit,
    db: Db,
    entity: Annotated[
        r.EntityName | None,
        Query(description="The records the file holds. A JSON file may name it instead."),
    ] = None,
    mode: Annotated[
        Literal["create", "upsert"] | None,
        Query(description="Left out, `upsert`, or what a JSON file says."),
    ] = None,
    file_name: Annotated[str | None, Query(max_length=255)] = None,
) -> r.ImportPreview:
    """Work out what importing a file would do, and store that as a preview.

    Nothing is changed. Each row comes back as `create`, `update` with the fields it
    changes, `unchanged`, or `rejected` with the reasons.
    """
    data = await limited_body(request)
    job = await run_in_threadpool(
        imports.preview,
        db,
        context,
        principal.role,
        data=data,
        format_=_format(request, file_name),
        entity_name=entity,
        mode=mode,
        file_name=file_name,
    )
    return shapes.preview_out(db, job)


@imports_.post("/{hid}/apply", responses=OUT_OF_DATE)
def apply_import(
    hid: str,
    principal: Inventory,
    context: Audit,
    db: Db,
    skip_rejected: SkipRejected = False,
) -> r.ImportJobOut:
    """Apply a preview exactly as it was shown, in one transaction, or not at all.

    Anybody with the Inventory role may apply it, whoever made it. If a record it would touch has
    changed since, nothing is applied and the answer is a `409`.
    """
    done = imports.apply(
        db, context, principal.role, hid, source="file", skip_rejected=skip_rejected
    )
    return applied(db, done)


@imports_.get("")
def list_imports(
    _: Viewer,
    db: Db,
    source: Annotated[
        Literal["file", "bulk"], Query(description="Imports of files, or bulk edits.")
    ] = "file",
    limit: Limit = 100,
    offset: Offset = 0,
) -> Page[r.ImportJobOut]:
    """List the stored previews and what became of them, newest first."""
    page, total = imports.list_jobs(db, source, limit, offset)
    return Page(
        items=[shapes.job_out(db, job) for job in page], total=total, limit=limit, offset=offset
    )


@imports_.get("/{hid}")
def get_import(hid: str, _: Viewer, db: Db) -> r.ImportJobOut:
    """Return one stored preview, of an import or of a bulk edit."""
    return shapes.job_out(db, imports.get_job(db, hid))


@imports_.get("/{hid}/rows")
def list_import_rows(
    hid: str,
    _: Viewer,
    db: Db,
    outcome: Annotated[r.Outcome | None, Query(description="Only rows of this kind.")] = None,
    limit: Limit = 100,
    offset: Offset = 0,
) -> Page[r.ImportRowOut]:
    """List the rows of a preview in the order of the file."""
    page, total = imports.list_rows(db, hid, outcome, limit, offset)
    return Page(
        items=[shapes.row_out(row) for row in page], total=total, limit=limit, offset=offset
    )


@exports_.post(
    "",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "The file, as an attachment.",
            "content": {"text/csv": {}, "application/json": {}},
        }
    },
)
def export(body: r.ExportRequest, _: Viewer, request: Request, db: Db) -> StreamingResponse:
    """Export a list as CSV or JSON, with the filter and the sort that the list takes."""
    wanted = exports.plan(
        body.entity,
        format_=body.format,
        filter_=body.filter,
        sort=body.sort,
        columns=body.columns,
        hids=body.hids,
        include_sources=body.include_sources,
        own_values=body.own_values,
        include_archived=body.include_archived,
        include_drafts=body.include_drafts,
    )
    name = exports.file_name(db, wanted)
    pieces = exports.stream(request.app.state.sessions, wanted)
    # The rows are chosen before the answer begins, so that a filter that cannot be run
    # is refused like any other and not half-way through a file.
    first = next(pieces)
    return StreamingResponse(
        chain([first], pieces),
        media_type=exports.MEDIA_TYPES[wanted.format],
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


ROUTERS = (imports_, exports_)
