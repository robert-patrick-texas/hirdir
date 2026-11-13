"""Previewing and applying a change to many records: a file, or a bulk edit.

A preview is made by doing the work for real, through the same functions as any other
change, inside a savepoint that is then undone. What it reports is therefore what an
apply will do, and no rule is written twice. Apply does the same work again, compares
every row with what was previewed, and keeps the result only when they all agree.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

from hirdir import clock
from hirdir.auth.roles import Role
from hirdir.db.models import ImportJob, ImportRow
from hirdir.domain import audit, records
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Conflict, Invalid, NotAllowed, NotFound
from hirdir.io import columns as cells
from hirdir.io import files
from hirdir.io.entities import Entity, Run, entity
from hirdir.io.files import Row, reason

OUTCOMES = ("create", "update", "unchanged", "rejected")
COUNTED = {"create": "created", "update": "updated", "unchanged": "unchanged"}
SOURCES = ("file", "bulk")
# Every so many rows the session lets go of the records it has worked on, so that a
# large file costs no more for each row than a small one.
LET_GO_EVERY = 500
MAX_PROBLEMS = 50
REFUSALS = (Invalid, Conflict, NotFound, NotAllowed)


@dataclass
class Result:
    """What one row does, or why it is rejected."""

    row: int
    outcome: str
    key: str = ""
    record_hid: str | None = None
    row_version: int | None = None
    changes: list[dict[str, Any]] = field(default_factory=list)
    reasons: list[dict[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _reasons(which: Entity, error: Exception) -> list[dict[str, str]]:
    """Return why a row is rejected, with each field named as the file names it."""
    named = getattr(error, "fields", None) or {}
    if not named:
        return [reason("", str(error))]
    return [reason(which.renamed.get(name, name), message) for name, message in named.items()]


def _typed(which: Entity, values: dict[str, Any]) -> dict[str, Any]:
    typed = {}
    for name, value in values.items():
        column = which.column(name)
        assert column is not None  # noqa: S101 - reading the file checked every name
        typed[name] = cells.typed(column, value)
    return typed


def _differences(
    which: Entity, before: dict[str, Any] | None, after: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return what a row changed, in the columns of the file."""
    changes = []
    for column in which.settable:
        old = None if before is None else cells.plain(column, before[column.name])
        new = cells.plain(column, after[column.name])
        if before is None and new in (None, [], ""):
            continue
        if old != new:
            changes.append(change(column.name, old, new))
    return changes


def _one(run: Run, which: Entity, number: int, values: dict[str, Any]) -> Result:
    """Work one row: find its record, write it, and say what that changed."""
    db = run.db
    hid = values.get("hid")
    if hid:
        record = db.get(which.model, hid)
        if record is None:
            raise Invalid("there is no such record", {"hid": f"there is no record {hid}"})
    else:
        record = which.find(run, values)
    result = Result(row=number, outcome="create", key=which.key(values, record))
    # A record that an earlier row made for a reference is this row's to describe.
    claimed = record is not None and record.hid in run.stubs
    if record is not None:
        if record.hid in run.seen:
            raise Invalid(
                f"row {run.seen[record.hid]} names the same record",
                {"": f"row {run.seen[record.hid]} of the file names the same record"},
            )
        if run.mode == "create" and not claimed:
            raise Conflict(
                "the record exists already",
                {"": "this record exists already, and the mode is create"},
            )
    elif run.mode == "update":
        raise Invalid("there is no such record", {"hid": "a bulk edit changes records that exist"})
    new = record is None or claimed
    before = None
    if record is not None and not claimed:
        result.record_hid, result.row_version = record.hid, record.row_version
        before = which.read(db, [record])[0]
    if claimed:
        run.claim(record.hid)
    record = which.write(run, record, values, new)
    db.flush()
    result.changes = _differences(which, before, which.read(db, [record])[0])
    if not new:
        changed = result.changes or record.row_version != result.row_version
        result.outcome = "update" if changed else "unchanged"
    else:
        result.record_hid = record.hid
    result.notes = list(run.notes)
    run.seen[record.hid] = number
    return result


def _work(
    db: Session,
    context: AuditContext,
    role: Role | None,
    which: Entity,
    mode: str,
    rows: Sequence[Row],
    skip: frozenset[int] = frozenset(),
) -> list[Result]:
    """Work every row in order, each in a savepoint of its own.

    A row that is refused leaves nothing behind and is reported as rejected. The rows
    numbered in `skip` are not worked at all.
    """
    run = Run(db, context, role, mode)
    results: list[Result] = []
    for number, row in enumerate(rows, start=1):
        if number in skip:
            continue
        if row.reasons:
            results.append(
                Result(
                    row=number,
                    outcome="rejected",
                    key=which.key(row.values, None),
                    reasons=row.reasons,
                )
            )
            continue
        run.start_row()
        savepoint = db.begin_nested()
        try:
            result = _one(run, which, number, _typed(which, row.values))
            savepoint.commit()
        except REFUSALS as error:
            savepoint.rollback()
            run.forget_row()
            result = Result(
                row=number,
                outcome="rejected",
                key=which.key(row.values, None),
                reasons=_reasons(which, error),
            )
        results.append(result)
        if number % LET_GO_EVERY == 0:
            run.let_go()
    run.let_go()
    return results


def _count(results: Sequence[Any]) -> dict[str, int]:
    counts = {"created": 0, "updated": 0, "unchanged": 0, "rejected": 0}
    for result in results:
        counts[COUNTED.get(result.outcome, "rejected")] += 1
    return counts


def preview_rows(
    db: Session,
    context: AuditContext,
    role: Role | None,
    *,
    source: str,
    which: Entity,
    mode: str,
    rows: Sequence[Row],
    file_name: str | None = None,
    file_sha256: str | None = None,
) -> ImportJob:
    """Work the rows without keeping anything, and store what they would do."""
    working = replace(context, via="import") if source == "file" else context
    undone = db.begin_nested()
    try:
        results = _work(db, working, role, which, mode, rows)
    finally:
        undone.rollback()
    job = ImportJob(
        source=source,
        entity=which.name,
        mode=mode,
        file_name=file_name,
        file_sha256=file_sha256,
        status="previewed",
        row_count=len(rows),
        created_by=context.actor_hid,
        **_count(results),
    )
    db.add(job)
    db.flush()
    if results:
        db.execute(
            insert(ImportRow),
            [
                {
                    "job_hid": job.hid,
                    "row": result.row,
                    "outcome": result.outcome,
                    "record_hid": result.record_hid if result.row_version is not None else None,
                    "row_version": result.row_version,
                    "key": result.key,
                    "values": rows[result.row - 1].values,
                    "changes": result.changes,
                    "reasons": result.reasons,
                    "notes": result.notes,
                }
                for result in results
            ],
        )
    audit.record(
        db,
        context,
        "preview",
        "import_job",
        job.hid,
        [change(name, None, getattr(job, name)) for name in ("source", "entity", "row_count")],
    )
    return job


def preview(
    db: Session,
    context: AuditContext,
    role: Role | None,
    *,
    data: bytes,
    format_: str,
    entity_name: str | None = None,
    mode: str | None = None,
    file_name: str | None = None,
) -> ImportJob:
    """Read a file, work out what importing it would do, and store that as a preview."""
    parsed = files.read(data, format_=format_, entity_name=entity_name, mode=mode)
    name = records.clean(file_name)
    if name is not None and len(name) > 255:
        raise Invalid("the file name is too long", {"file_name": "at most 255 characters"})
    return preview_rows(
        db,
        context,
        role,
        source="file",
        which=parsed.entity,
        mode=parsed.mode,
        rows=parsed.rows,
        file_name=name,
        file_sha256=hashlib.sha256(data).hexdigest(),
    )


def get_job(db: Session, hid: str, source: str | None = None) -> ImportJob:
    """Return the stored preview with hid."""
    job = db.get(ImportJob, hid)
    if job is None or (source is not None and job.source != source):
        raise NotFound(f"there is no {'bulk edit' if source == 'bulk' else 'import'} {hid}")
    return job


def list_jobs(db: Session, source: str, limit: int, offset: int) -> tuple[list[ImportJob], int]:
    """Return the stored previews of one source, newest first, and how many there are."""
    query = select(ImportJob).where(ImportJob.source == source)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    page = db.scalars(
        query.order_by(ImportJob.created_at.desc(), ImportJob.hid.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(page), total


def list_rows(
    db: Session, hid: str, outcome: str | None, limit: int, offset: int
) -> tuple[list[ImportRow], int]:
    """Return a page of the rows of a preview in the order of the file, and their number."""
    get_job(db, hid)
    query = select(ImportRow).where(ImportRow.job_hid == hid)
    if outcome:
        if outcome not in OUTCOMES:
            raise Invalid(
                "the outcome is not acceptable", {"outcome": f"one of {', '.join(OUTCOMES)}"}
            )
        query = query.where(ImportRow.outcome == outcome)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    return list(db.scalars(query.order_by(ImportRow.row).limit(limit).offset(offset))), total


@dataclass
class Applied:
    """The end of an apply: the job, and for one that failed, the rows that stood in the way."""

    job: ImportJob
    problems: list[dict[str, str]] = field(default_factory=list)


def _disagreements(stored: Sequence[ImportRow], results: Sequence[Result]) -> list[dict[str, str]]:
    """Return the rows that no longer come out as they were previewed."""
    problems = []
    for was, now in zip(stored, results, strict=True):
        name = f"row {was.row}" + (f", {was.key}" if was.key else "")
        if was.record_hid is not None and (
            now.record_hid != was.record_hid or now.row_version != was.row_version
        ):
            problems.append(reason(f"rows.{was.row}", f"{name}: changed since the preview"))
        elif now.outcome != was.outcome or now.changes != was.changes:
            problems.append(
                reason(f"rows.{was.row}", f"{name}: would no longer do what was previewed")
            )
    return problems


def apply(
    db: Session,
    context: AuditContext,
    role: Role | None,
    hid: str,
    *,
    source: str,
    skip_rejected: bool = False,
) -> Applied:
    """Apply a preview exactly as it was shown, or not at all.

    Only the one who made the preview may apply it, and once. Every row is worked
    again. If each comes out as previewed, and each record a row matched is at the
    version it was previewed at, the work is kept. Otherwise it is undone, the job is
    marked failed, and the rows in the way are returned.
    """
    job = get_job(db, hid, source)
    if job.created_by != context.actor_hid:
        raise NotAllowed("a preview is applied by the one who made it")
    if job.status != "previewed":
        raise Conflict(
            f"this preview is {job.status} already", {"status": "make a new preview to go on"}
        )
    if job.rejected and not skip_rejected:
        raise Invalid(
            f"{job.rejected} of the rows are rejected",
            {"skip_rejected": "correct them and preview again, or apply the rest without them"},
        )
    which = entity(job.entity)
    stored = list(
        db.scalars(select(ImportRow).where(ImportRow.job_hid == hid).order_by(ImportRow.row))
    )
    wanted = [row for row in stored if row.outcome != "rejected"]
    skip = frozenset(row.row for row in stored if row.outcome == "rejected")
    rows = [Row(values=row.values) for row in stored]
    working = replace(context, via="import") if source == "file" else context

    attempt = db.begin_nested()
    results = _work(db, working, role, which, job.mode, rows, skip)
    problems = _disagreements(wanted, results)
    if problems:
        attempt.rollback()
        job = get_job(db, hid)
        job.status = "failed"
        job.failure = (
            f"{len(problems)} of the rows changed after the preview was made; preview again"
        )
        audit.record(
            db,
            context,
            "apply_failed",
            "import_job",
            hid,
            [change("status", "previewed", "failed")],
        )
        return Applied(job, problems[:MAX_PROBLEMS])
    attempt.commit()
    made = [
        {"job_hid": hid, "row": result.row, "record_hid": result.record_hid}
        for result in results
        if result.outcome == "create"
    ]
    if made:
        # The rows that made a record now say which.
        db.execute(update(ImportRow), made)
    job = get_job(db, hid)
    job.status = "applied"
    job.skip_rejected = skip_rejected
    job.applied_at = clock.now()
    counts = _count(results)
    audit.record(
        db,
        context,
        "apply",
        "import_job",
        hid,
        [
            change("status", "previewed", "applied"),
            *(change(name, None, counts[name]) for name in ("created", "updated", "unchanged")),
        ],
    )
    return Applied(job)
