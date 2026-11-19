"""Previewing and applying a change to many records: a file, or a bulk edit.

A preview is made by doing the work for real, through the same functions as any other
change, where none of it is kept: in a savepoint that is then undone, or for a large
file on a copy of the database, so that nobody waits for it. What it reports is
therefore what an apply will do, and no rule is written twice.

An apply is worked in the background by the server's worker (`hirdir.io.background`),
one job at a time, 50 rows to a batch and each batch a transaction of its own (D-185).
It works every row again, compares it with what was previewed, and keeps each row that
agrees. A row whose record has moved on since the preview is left out as stale, and the
rest go on.
"""

import hashlib
import logging
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from sqlalchemy import case, func, insert, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from hirdir import clock
from hirdir.auth.roles import Role
from hirdir.db import dialect, engine
from hirdir.db.models import AuditEvent, ImportJob, ImportRow, User
from hirdir.domain import accounts, audit, deleted, items, records, systems
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Conflict, Deleted, Invalid, NotAllowed, NotFound
from hirdir.io import columns as cells
from hirdir.io import files
from hirdir.io.entities import Entity, Run, entity
from hirdir.io.files import Row, reason

OUTCOMES = ("create", "update", "unchanged", "rejected")
# What an apply did with a row: as previewed, or not, because it was stale or refused.
APPLIED_OUTCOMES = ("create", "update", "unchanged", "stale", "rejected")
COUNTED = {"create": "created", "update": "updated", "unchanged": "unchanged"}
SOURCES = ("file", "bulk")
# The jobs that are being applied, or wait to be.
BUSY = ("queued", "applying")
# Every so many rows the session lets go of the records it has worked on, so that a
# large file costs no more for each row than a small one.
LET_GO_EVERY = 500
# A preview of more rows than this is worked on a copy of the database, so that it
# holds nobody up while it works. See `engine.trial`.
IN_PLACE_UP_TO = 100
# An apply in the background works this many rows to a transaction (D-185).
BATCH_ROWS = 50
# Between two batches the one writer's place is left free this long, in seconds. A
# change that waits for it is told by SQLite to try again every tenth of a second at
# the longest, so in this time it is sure to try, and gets the place. It is fixed: it
# is what keeps a sign-in from waiting behind a large file.
PAUSE_BETWEEN_BATCHES = 0.12
REFUSALS = (Invalid, Conflict, NotFound, NotAllowed)
log = logging.getLogger("hirdir")


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


# The kinds of record that an Admin deletes, as a refusal names one (P-227).
DELETED_KINDS = {"item": "item", "device_group": "device group"}


def _no_record(db: Session, which: Entity, hid: str) -> str:
    """Say that a row's HID names no record: or, where an Admin deleted it, when and by
    whom, as its 404 says."""
    what = DELETED_KINDS.get(which.record_type)
    if what is not None:
        gone = deleted.missing(db, which.record_type, hid, what)
        if isinstance(gone, Deleted):
            return str(gone)
    return f"there is no record {hid}"


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
    """Return what a row changed, in the columns of the file, and then what the entity
    tells beside them: the status of a registration a row brings back or makes."""
    changes = []
    for column in which.settable:
        old = None if before is None else cells.plain(column, before[column.name])
        new = cells.plain(column, after[column.name])
        if before is None and new in (None, [], ""):
            continue
        if old != new:
            changes.append(change(column.name, old, new))
    for name in which.told:
        if name not in after:
            continue
        old = None if before is None else before.get(name)
        if old != after[name]:
            changes.append(change(name, old, after[name]))
    return changes


def _one(run: Run, which: Entity, values: dict[str, Any], result: Result) -> None:
    """Work one row: find its record, write it, and say in result what that changed.

    The result is filled in as the row goes, so that a row which is refused part-way
    still says which record it was about.
    """
    db = run.db
    hid = values.get("hid")
    if hid:
        record = db.get(which.model, hid)
        if record is None:
            raise Invalid("there is no such record", {"hid": _no_record(db, which, hid)})
    else:
        record = which.find(run, values)
    result.key = which.key(values, record)
    # A record that an earlier row made for a reference is this row's to describe.
    claimed = record is not None and record.hid in run.stubs
    if record is not None and not claimed:
        result.record_hid, result.row_version = record.hid, record.row_version
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
        before = which.read_for(run, [record])[0]
    if claimed:
        run.claim(record.hid)
    record = which.write(run, record, values, new)
    db.flush()
    result.changes = [
        change
        for change in _differences(which, before, which.read_for(run, [record])[0])
        if change["field"] not in which.restated
        and (change["field"] not in which.by_the_clock or values.get(change["field"]) is not None)
    ]
    if not new:
        changed = result.changes or record.row_version != result.row_version
        result.outcome = "update" if changed else "unchanged"
    else:
        result.record_hid = record.hid
    result.notes = list(run.notes)
    run.seen[record.hid] = result.row


def _work(
    db: Session,
    context: AuditContext,
    role: Role | None,
    which: Entity,
    mode: str,
    rows: Sequence[Row],
    skip: frozenset[int] = frozenset(),
    system_hid: str | None = None,
) -> list[Result]:
    """Work every row, each in a savepoint of its own, and report them in the file's order.

    A row that is refused leaves nothing behind and is reported as rejected. The rows
    numbered in `skip` are not worked at all. `system_hid` is the external system a file
    of items was read from (P-248).
    """
    run = Run(db, context, role, mode)
    run.system_hid = system_hid
    results: list[Result] = []
    workable = [
        number for number, row in enumerate(rows, start=1) if number not in skip and not row.reasons
    ]
    for number, row in enumerate(rows, start=1):
        if number not in skip and row.reasons:
            results.append(
                Result(
                    row=number,
                    outcome="rejected",
                    key=which.key(row.values, None),
                    reasons=row.reasons,
                )
            )
    # Most files are worked in their own order. An entity whose rows lean on one another
    # says in which order they are to be worked: an item before what is in it.
    typed = {number: _typed(which, rows[number - 1].values) for number in workable}
    places = which.order(run, [typed[number] for number in workable])
    for worked, place in enumerate(places, start=1):
        number = workable[place - 1]
        row = rows[number - 1]
        run.start_row(number)
        result = Result(row=number, outcome="create", key=which.key(row.values, None))
        savepoint = db.begin_nested()
        try:
            _one(run, which, typed[number], result)
            savepoint.commit()
        except REFUSALS as error:
            savepoint.rollback()
            run.forget_row()
            # What the row would have done is undone. Which record it named is kept.
            result.outcome, result.changes, result.notes = "rejected", [], []
            result.reasons = _reasons(which, error)
        results.append(result)
        if worked % LET_GO_EVERY == 0:
            run.let_go()
    results.sort(key=lambda result: result.row)
    # What is right or wrong only once every row is in: the members of a stack.
    wrong = which.finish(run)
    for result in results:
        if result.row in wrong and result.outcome != "rejected":
            result.outcome, result.changes, result.notes = "rejected", [], []
            result.reasons = wrong[result.row]
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
    system_hid: str | None = None,
    complete: bool = False,
) -> ImportJob:
    """Work the rows without keeping anything, and store what they would do.

    A file read from an external system that is everything it reports counts how many
    items its apply would mark `not_reported`: none where a row is rejected (P-248).
    """
    working = replace(context, via="import") if source == "file" else context
    with engine.trial(db, in_place=len(rows) <= IN_PLACE_UP_TO) as trying:
        results = _work(trying, working, role, which, mode, rows, system_hid=system_hid)
    marks = 0
    if (
        complete
        and system_hid is not None
        and not any(result.outcome == "rejected" for result in results)
    ):
        named = {result.record_hid for result in results if result.row_version is not None}
        marks = len(systems.not_named(db, system_hid, {hid for hid in named if hid}))
    job = ImportJob(
        source=source,
        entity=which.name,
        mode=mode,
        file_name=file_name,
        file_sha256=file_sha256,
        status="previewed",
        row_count=len(rows),
        created_by=context.actor_hid,
        system_hid=system_hid,
        complete=complete if system_hid is not None else None,
        not_reported=marks,
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
                    # A record made while trying is gone again, and so is its HID.
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
    max_bytes: int = files.MAX_BYTES,
    system: str | None = None,
    complete: bool = False,
) -> ImportJob:
    """Read a file, work out what importing it would do, and store that as a preview.

    A file of items may name `system`, the external system it was read from, by whose
    identifier its rows are matched first, and be `complete`, everything that system
    reports (P-248).
    """
    parsed = files.read(
        data, format_=format_, entity_name=entity_name, mode=mode, max_bytes=max_bytes
    )
    name = records.clean(file_name)
    if name is not None and len(name) > 255:
        raise Invalid("the file name is too long", {"file_name": "at most 255 characters"})
    system_hid = _read_from(db, parsed, records.clean(system), complete)
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
        system_hid=system_hid,
        complete=complete,
    )


def _read_from(db: Session, parsed: files.Parsed, system: str | None, complete: bool) -> str | None:
    """Return the external system a file was read from, refusing what cannot be one: a
    system that is not there or is retired, a file of another entity than items, a file
    that is everything a system reports and names none, and a file that gives a system's
    identifiers and names no system (P-248)."""
    if system is None:
        if complete:
            raise Invalid(
                "a file that is everything a system reports names the system",
                {"complete": "give system, the external system the file was read from"},
            )
        if parsed.entity.name == "items" and any(
            row.values.get("external_id") for row in parsed.rows
        ):
            raise Invalid(
                "a file of a system's identifiers names the system",
                {
                    "external_id": "give system, the external system whose identifiers "
                    "these are, or leave the column blank"
                },
            )
        return None
    if parsed.entity.name != "items":
        raise Invalid(
            "only a file of items is read from an external system",
            {"system": "a file of items only"},
        )
    if complete and not parsed.rows:
        # A report that came out empty is no report: it would mark everything (P-248).
        raise Invalid(
            "a file that is everything a system reports names at least one thing",
            {"complete": "a file that is everything a system reports names at least one thing"},
        )
    found = systems.the_one(db, system, "system")
    if found.record_status == "retired":
        raise Invalid("the system is retired", {"system": f"{found.name} is retired"})
    return found.hid


# Why a file that is everything its system reports marks nothing (P-248): a row the
# preview or the apply rejected, a rejected row left out by `skip_rejected`, or a row
# left out as stale. Each is named as the outcome of such a row is.
Held = Literal["rejected", "skipped", "stale"]


def not_reported_held(job: ImportJob) -> Held | None:
    """Say why a `complete` import marks, or will mark, nothing: one of `Held`, or None
    where nothing holds it. A preview is held by a rejected row; an apply by a row
    refused when it was applied, a row left out as stale, or rejected rows left out."""
    if not job.complete or job.system_hid is None:
        return None
    if job.status == "previewed":
        return "rejected" if job.rejected else None
    left_out = job.rejected if job.skip_rejected else 0
    if job.rows_done - job.applied - job.stale - left_out > 0:
        return "rejected"
    if job.stale:
        return "stale"
    if left_out:
        return "skipped"
    return None


# The most items a preview names that a file would mark `not_reported`.
FIRST_NOT_REPORTED = 10


def not_reported_first(db: Session, job: ImportJob) -> list[tuple[str, str]]:
    """Return the first items a `complete` import that is not applied yet would mark
    `not_reported`, each by its HID and label, by name (P-248): read now, from the
    rows the preview matched. None where a row is rejected, as its apply marks none."""
    if not job.complete or job.system_hid is None or job.status != "previewed" or job.rejected:
        return []
    named = set(
        db.scalars(
            select(ImportRow.record_hid).where(
                ImportRow.job_hid == job.hid, ImportRow.record_hid.is_not(None)
            )
        )
    )
    left = systems.not_named(db, job.system_hid, {hid for hid in named if hid})
    return [(item.hid, items.shown_name(item)) for _, item in left[:FIRST_NOT_REPORTED]]


def get_job(db: Session, hid: str, source: str | None = None) -> ImportJob:
    """Return the stored preview with hid."""
    job = db.get(ImportJob, hid)
    if job is None or (source is not None and job.source != source):
        raise NotFound(f"there is no {'bulk edit' if source == 'bulk' else 'import'} {hid}")
    return job


def list_jobs(
    db: Session, source: str, limit: int, offset: int, arrange: records.Arrange | None = None
) -> tuple[list[ImportJob], int]:
    """Return the stored previews of one source, newest first, and how many there are.

    `arrange` sorts them as was asked for, and the newest first settles what that
    leaves tied.
    """
    query = select(ImportJob).where(ImportJob.source == source)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    if arrange is not None:
        query = arrange(query)
    page = db.scalars(
        query.order_by(ImportJob.created_at.desc(), ImportJob.hid.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(page), total


def list_rows(
    db: Session,
    hid: str,
    outcome: str | None,
    limit: int,
    offset: int,
    arrange: records.Arrange | None = None,
    applied_outcome: str | None = None,
) -> tuple[list[ImportRow], int]:
    """Return a page of the rows of a preview in the order of the file, and their number.

    `outcome` keeps to the rows the preview found so, and `applied_outcome` to those
    the apply did so with. `arrange` sorts them as was asked for, and the order of the
    file settles what that leaves tied.
    """
    get_job(db, hid)
    query = select(ImportRow).where(ImportRow.job_hid == hid)
    if outcome:
        if outcome not in OUTCOMES:
            raise Invalid(
                "the outcome is not acceptable", {"outcome": f"one of {', '.join(OUTCOMES)}"}
            )
        query = query.where(ImportRow.outcome == outcome)
    if applied_outcome:
        if applied_outcome not in APPLIED_OUTCOMES:
            raise Invalid(
                "the outcome is not acceptable",
                {"applied_outcome": f"one of {', '.join(APPLIED_OUTCOMES)}"},
            )
        query = query.where(ImportRow.applied_outcome == applied_outcome)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    if arrange is not None:
        query = arrange(query)
    return list(db.scalars(query.order_by(ImportRow.row).limit(limit).offset(offset))), total


# --- an apply in the background (D-185) -----------------------------------------------


def _being_applied(db: Session, hid: str) -> bool:
    """Say whether another job than hid is being applied, or waits to be."""
    other = select(ImportJob.hid).where(ImportJob.status.in_(BUSY), ImportJob.hid != hid)
    return db.scalar(other.limit(1)) is not None


def begin_apply(
    db: Session, context: AuditContext, hid: str, *, source: str, skip_rejected: bool = False
) -> ImportJob:
    """Ask for a preview to be applied in the background, or for a stopped apply to go on.

    Anybody who may change the inventory may ask, whoever made the preview, and it is
    applied once. The job is `applying` at once, or `queued` while another is applied:
    one job is applied at a time, in the order they were asked for, by the worker of
    the server (`work_job`). A stopped job goes on as it was begun.
    """
    # Of two that ask at the same moment, the second sees what the first stored: the
    # job taken, or another job ahead of it.
    dialect.hold_other_writers(db)
    job = get_job(db, hid, source)
    db.refresh(job)
    if job.status in BUSY:
        raise Conflict(
            "this preview is being applied already", {"status": "wait for it to be applied"}
        )
    if job.status not in ("previewed", "stopped"):
        raise Conflict(
            f"this preview is {job.status} already", {"status": "make a new preview to go on"}
        )
    resuming = job.status == "stopped"
    if not resuming and job.rejected and not skip_rejected:
        raise Invalid(
            f"{job.rejected} of the rows are rejected",
            {"skip_rejected": "correct them and preview again, or apply the rest without them"},
        )
    before = job.status
    job.status = "queued" if _being_applied(db, hid) else "applying"
    job.applied_at, job.applied_by, job.failure = clock.now(), context.actor_hid, None
    if not resuming:
        job.skip_rejected = skip_rejected
        # What the preview rejected is left out, and says so with the preview's reasons.
        db.execute(
            update(ImportRow)
            .where(ImportRow.job_hid == hid, ImportRow.outcome == "rejected")
            .values(applied_outcome="rejected", applied_reasons=ImportRow.reasons)
        )
        job.rows_done = job.rejected
    audit.record(
        db,
        context,
        "apply_resumed" if resuming else "apply_started",
        "import_job",
        hid,
        [
            change("status", before, job.status),
            *([] if resuming else [change("skip_rejected", None, skip_rejected)]),
        ],
    )
    db.flush()
    return job


def recover(db: Session) -> list[str]:
    """Mark stopped every job that was being applied when the server stopped.

    It is called as the server starts, before its worker does anything. A job that
    waited, `queued`, waits still, and is applied in its turn. Return the jobs stopped.
    """
    found = list(db.scalars(select(ImportJob.hid).where(ImportJob.status == "applying")))
    for hid in found:
        _stop(db, hid, "the server stopped while it was being applied; apply it again to resume")
    return found


def next_job(db: Session) -> str | None:
    """Return the job to apply next: the one applying, else the one that has waited longest."""
    return db.scalar(
        select(ImportJob.hid)
        .where(ImportJob.status.in_(BUSY))
        .order_by(
            case((ImportJob.status == "applying", 0), else_=1),
            ImportJob.applied_at,
            ImportJob.hid,
        )
        .limit(1)
    )


def _context(db: Session, hid: str) -> AuditContext:
    """Return who asked for a job to be applied, through which door, in which request.

    That is the event that began it, or that resumed it last. Every batch of the job is
    worked under its request ID, and as the person who asked.
    """
    event = db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.record_type == "import_job",
            AuditEvent.record_hid == hid,
            AuditEvent.action.in_(("apply_started", "apply_resumed")),
        )
        .order_by(AuditEvent.at.desc(), AuditEvent.hid.desc())
        .limit(1)
    ).first()
    if event is None:
        return AuditContext(actor_hid=None, via="system")
    return AuditContext(actor_hid=event.actor_hid, via=event.via, request_id=event.request_id)


APPLY_BEGINS = ("apply_started", "apply_resumed")
APPLY_ENDS = ("apply_stopped", "apply")


@dataclass(frozen=True)
class _Applying:
    """One time a job was asked to be applied, until that apply stopped or ended."""

    job_hid: str
    request_id: str
    actor_hid: str | None
    begun: Any
    ended: Any

    def holds(self, event: AuditEvent) -> bool:
        return (
            event.request_id == self.request_id
            and event.actor_hid == self.actor_hid
            and self.begun <= event.at
            and (self.ended is None or event.at <= self.ended)
        )


def _applying(db: Session, requests: set[str]) -> list[_Applying]:
    """Return each time a job of those requests was asked to be applied, the earliest
    first, with when that apply stopped or ended, or None while it goes on."""
    events = db.execute(
        select(
            AuditEvent.record_hid,
            AuditEvent.action,
            AuditEvent.request_id,
            AuditEvent.actor_hid,
            AuditEvent.at,
        )
        .where(
            AuditEvent.record_type == "import_job",
            AuditEvent.action.in_(APPLY_BEGINS + APPLY_ENDS),
            AuditEvent.request_id.in_(requests),
        )
        .order_by(AuditEvent.at, AuditEvent.hid)
    )
    found: list[_Applying] = []
    open_: dict[str, int] = {}
    for job_hid, action, request_id, actor_hid, at in events:
        if action in APPLY_BEGINS:
            open_[job_hid or ""] = len(found)
            found.append(_Applying(job_hid or "", request_id, actor_hid, at, None))
        elif (job_hid or "") in open_:
            place = open_.pop(job_hid or "")
            found[place] = replace(found[place], ended=at)
    return found


def _stubs_made(db: Session, hid: str) -> set[str]:
    """Return the vendors and catalog entries that the batches a job has applied made
    only because a row named them, and that no row has described since.

    They are the events of the request that began or resumed the job's apply, made by
    whoever asked, in the time until that apply stopped or ended. Two applies may share
    a request ID, as the jobs of `hirdir admin load-examples` once did and as a caller
    that sends one `X-Request-Id` twice does, and one may be asked for while another is
    applied. One job is applied at a time, in the order asked: an event that falls
    within the times of two is of the one asked for first.
    """
    requests = set(
        db.scalars(
            select(AuditEvent.request_id).where(
                AuditEvent.record_type == "import_job",
                AuditEvent.record_hid == hid,
                AuditEvent.action.in_(APPLY_BEGINS),
            )
        )
    )
    times = _applying(db, requests)
    made = select(AuditEvent).where(
        AuditEvent.request_id.in_(requests),
        AuditEvent.record_type.in_(("vendor", "catalog_entry")),
        AuditEvent.action.in_(("create", "update")),
    )
    created, described = set(), set()
    for event in db.scalars(made):
        within = next((one for one in times if one.holds(event)), None)
        if within is None or within.job_hid != hid:
            continue
        (created if event.action == "create" else described).add(event.record_hid)
    own = set(
        db.scalars(
            select(ImportRow.record_hid).where(
                ImportRow.job_hid == hid, ImportRow.applied_outcome == "create"
            )
        )
    )
    return {one for one in created - described - own if one is not None}


def _stop(db: Session, hid: str, why: str) -> None:
    """Mark a job stopped, with why, to be resumed. The rows it applied stay applied."""
    dialect.hold_other_writers(db)
    job = db.get_one(ImportJob, hid)
    db.refresh(job)
    before = job.status
    job.status, job.failure = "stopped", why
    # Nobody stopped it: the server did, in the course of the apply that was asked for.
    asked = _context(db, hid)
    by_the_server = AuditContext(actor_hid=None, via="system", request_id=asked.request_id)
    audit.record(
        db,
        by_the_server,
        "apply_stopped",
        "import_job",
        hid,
        [change("status", before, "stopped"), change("failure", None, why)],
    )


@dataclass
class _Stored:
    """One row of a job that is still to be applied, as it was previewed."""

    row: int
    outcome: str
    record_hid: str | None
    row_version: int | None
    key: str
    changes: list[dict[str, Any]]
    notes: list[str]


@dataclass
class _Done:
    """What the apply did with one row."""

    outcome: str
    reasons: list[dict[str, str]] = field(default_factory=list)
    record_hid: str | None = None


def _stale(was: _Stored, now: Result) -> str | None:
    """Say why a row no longer comes out as it was previewed, or None when it does."""
    if was.record_hid is not None and (
        now.record_hid != was.record_hid or now.row_version != was.row_version
    ):
        return "changed since the preview: preview it again"
    if (now.outcome, now.changes, now.notes) != (was.outcome, was.changes, was.notes):
        return "would no longer do what was previewed: preview it again"
    return None


def _apply_row(run: Run, which: Entity, was: _Stored, values: dict[str, Any]) -> _Done:
    """Work one row again as it was previewed, and keep it only when it comes out so.

    A row whose record is not at the version previewed, or that would no longer do what
    was previewed, leaves nothing behind and is stale. One that the rules refuse now,
    such as a minor item in an item that a stale row did not make, is rejected.
    """
    run.start_row(was.row)
    result = Result(row=was.row, outcome="create", key=was.key)
    savepoint = run.db.begin_nested()
    try:
        _one(run, which, values, result)
    except REFUSALS as error:
        savepoint.rollback()
        run.forget_row()
        # Refused now: stale when its record has moved on, and otherwise rejected.
        moved = _stale(
            was, replace(result, outcome=was.outcome, changes=was.changes, notes=was.notes)
        )
        if moved is None and was.outcome == "create" and isinstance(error, Conflict):
            # What the row would make has been made since the preview, by somebody else.
            moved = "a record it would make was made since the preview: preview it again"
        if moved is not None:
            return _Done("stale", [reason("", moved)])
        return _Done("rejected", _reasons(which, error))
    why = _stale(was, result)
    if why is not None:
        savepoint.rollback()
        run.forget_row()
        if result.record_hid is not None and run.seen.get(result.record_hid) == was.row:
            del run.seen[result.record_hid]
        return _Done("stale", [reason("", why)])
    savepoint.commit()
    return _Done(result.outcome, record_hid=result.record_hid)


class RoleLost(Exception):
    """Whoever asked for a job to be applied no longer holds the Inventory role."""


def _apply_batch(
    db: Session,
    run: Run,
    which: Entity,
    hid: str,
    batch: Sequence[_Stored],
    typed: Mapping[int, dict[str, Any]],
) -> dict[int, _Done]:
    """Apply one batch of rows as a transaction of its own, with its audit events.

    The batch takes the one writer's place before it looks and lets it go when it is
    stored. What it did with each row is stored with it, so that a job resumed after a
    stop never applies a row twice. Rows that cannot stand together once all of them
    are in, as `finish` says, are rejected, and the batch is worked again without them.
    """
    numbers = {was.row for was in batch}
    refused: dict[int, list[dict[str, str]]] = {}
    while True:
        run.start_batch()
        try:
            dialect.hold_other_writers(db)
            # The role of whoever asked is asked of once the batch holds the writer's
            # place, so that no change of it can come between the asking and the batch: a
            # role that is lost stops the job, and one that changed is the one used.
            now = run.given_role or _role(db, run.context)
            if now is None or not now.allows(Role.INVENTORY):
                raise RoleLost
            run.role = now
            done = {
                was.row: _Done("rejected", refused[was.row])
                if was.row in refused
                else _apply_row(run, which, was, typed[was.row])
                for was in batch
            }
            wrong = {
                number: why
                for number, why in which.finish(run).items()
                if number in numbers and done[number].outcome in COUNTED
            }
            if not wrong:
                _store_batch(db, hid, batch, done)
                break
        except BaseException:
            _undo_batch(db, run, numbers)
            raise
        _undo_batch(db, run, numbers)
        refused.update(wrong)
    run.let_go()
    return done


def _undo_batch(db: Session, run: Run, numbers: set[int]) -> None:
    """Undo a batch that was not stored, and forget what its rows taught the run."""
    db.rollback()
    run.forget_batch()
    for record_hid, number in list(run.seen.items()):
        if number in numbers:
            del run.seen[record_hid]


def _store_batch(
    db: Session, hid: str, batch: Sequence[_Stored], done: Mapping[int, _Done]
) -> None:
    """Store what a batch did with each of its rows, and how far the job has got."""
    stored = {was.row: was for was in batch}
    db.execute(
        update(ImportRow),
        [
            {
                "job_hid": hid,
                "row": number,
                "applied_outcome": what.outcome,
                "applied_reasons": what.reasons,
                # A row that made a record now says which.
                "record_hid": what.record_hid
                if what.outcome == "create"
                else stored[number].record_hid,
            }
            for number, what in done.items()
        ],
    )
    applied = sum(1 for what in done.values() if what.outcome in COUNTED)
    stale = sum(1 for what in done.values() if what.outcome == "stale")
    db.execute(
        update(ImportJob)
        .where(ImportJob.hid == hid)
        .values(
            rows_done=ImportJob.rows_done + len(done),
            applied=ImportJob.applied + applied,
            stale=ImportJob.stale + stale,
        )
    )
    db.commit()


def batches(numbers: Sequence[int], together: Mapping[int, Any]) -> list[list[int]]:
    """Cut the rows, in the order they are worked, into batches of BATCH_ROWS.

    A batch is a run of rows in that order. It never splits the rows that are checked
    together: a batch that holds one of them goes on to the last of them, however many
    rows that makes.
    """
    last: dict[Any, int] = {}
    for place, number in enumerate(numbers):
        if together.get(number) is not None:
            last[together[number]] = place
    cut: list[list[int]] = []
    start = 0
    while start < len(numbers):
        end = min(start + BATCH_ROWS, len(numbers))
        place = start
        while place < end:
            key = together.get(numbers[place])
            if key is not None:
                end = max(end, last[key] + 1)
            place += 1
        cut.append(list(numbers[start:end]))
        start = end
    return cut


def _plan(
    db: Session, hid: str, run: Run, which: Entity
) -> tuple[list[list[_Stored]], dict[int, dict[str, Any]]]:
    """Return the batches of the rows still to be applied, and each row's values typed.

    The order the rows are worked in is worked out once, for every row still to be
    applied, so that an item is worked before what is in it whichever batch each is in.
    """
    found = db.execute(
        select(
            ImportRow.row,
            ImportRow.outcome,
            ImportRow.record_hid,
            ImportRow.row_version,
            ImportRow.key,
            ImportRow.changes,
            ImportRow.notes,
            ImportRow.values,
        )
        .where(ImportRow.job_hid == hid, ImportRow.applied_outcome.is_(None))
        .order_by(ImportRow.row)
    ).all()
    waiting = [_Stored(*row[:7]) for row in found]
    typed = {row.row: _typed(which, row.values) for row in found}
    values = [typed[was.row] for was in waiting]
    places = which.order(run, values)
    keys = which.together(run, values)
    ordered = [waiting[place - 1].row for place in places]
    together = {was.row: key for was, key in zip(waiting, keys, strict=True)}
    by_number = {was.row: was for was in waiting}
    # Working out the order read what is stored, and wrote nothing.
    db.rollback()
    return [[by_number[number] for number in batch] for batch in batches(ordered, together)], typed


def _mark_not_reported(
    db: Session, job: ImportJob, context: AuditContext, counts: Mapping[str | None, int]
) -> int:
    """Mark `not_reported` what the system of a file that is everything it reports did
    not name, once the file is applied whole (P-248); and nothing where a row was
    rejected, left out or stale. Return how many were marked."""
    if not job.complete or job.system_hid is None:
        return 0
    if counts.get("rejected", 0) or counts.get("stale", 0):
        return 0
    named = set(
        db.scalars(
            select(ImportRow.record_hid).where(
                ImportRow.job_hid == job.hid, ImportRow.record_hid.is_not(None)
            )
        )
    )
    # Each change is the import's, as the changes of its rows are, and names the job.
    by_the_import = audit.because(replace(context, via="import"), "import", None, job.hid)
    return systems.mark_not_reported(
        db, by_the_import, job.system_hid, {hid for hid in named if hid}
    )


def _confirmed(db: Session, job: ImportJob) -> int:
    """Return how many registrations an applied file read from a system confirmed and
    changed in nothing else (P-248): its rows applied with an identifier whose changes do
    not make or bring back a registration, nor give it another identifier. Each such
    confirmation has no event of its own; the job's event of its apply counts them."""
    if job.system_hid is None:
        return 0
    rows = db.execute(
        select(ImportRow.values, ImportRow.changes).where(
            ImportRow.job_hid == job.hid, ImportRow.applied_outcome.in_(list(COUNTED))
        )
    )
    return sum(
        1
        for values, changes in rows
        if (values or {}).get("external_id")
        and not any(
            entry.get("field") in ("registration", "external_id") for entry in changes or []
        )
    )


def _complete(db: Session, hid: str, context: AuditContext) -> None:
    """Mark a job applied, now that every row is worked, with the counts of what it did.

    A file that is everything its system reports marks what it did not name here, once,
    at the end of its apply, however often it stopped and was resumed (P-248).
    """
    dialect.hold_other_writers(db)
    job = db.get_one(ImportJob, hid)
    db.refresh(job)
    by_outcome = (
        select(ImportRow.applied_outcome, func.count())
        .where(ImportRow.job_hid == hid)
        .group_by(ImportRow.applied_outcome)
    )
    counts: dict[str | None, int] = dict(db.execute(by_outcome).all())
    marked = _mark_not_reported(db, job, context, counts)
    confirmed = _confirmed(db, job)
    if job.complete:
        job.not_reported = marked
    before = job.status
    job.status = "applied"
    audit.record(
        db,
        context,
        "apply",
        "import_job",
        hid,
        [
            change("status", before, "applied"),
            *(change(name, None, counts.get(outcome, 0)) for outcome, name in COUNTED.items()),
            change("stale", None, counts.get("stale", 0)),
            change("rejected", None, counts.get("rejected", 0)),
            *([change("not_reported", None, marked)] if job.complete else []),
            *(
                [change("system", None, job.system_hid), change("confirmed", None, confirmed)]
                if job.system_hid is not None
                else []
            ),
        ],
    )
    db.commit()


def _role(db: Session, context: AuditContext) -> Role | None:
    """Return the role that the person who asked for an apply holds now."""
    user = db.get(User, context.actor_hid) if context.actor_hid else None
    if user is None or user.disabled:
        return None
    return accounts.effective_role(db, user)


def _take(db: Session, hid: str) -> ImportJob | None:
    """Take a job that is to be applied, as the one that is applying. None if it is not."""
    dialect.hold_other_writers(db)
    job = db.get(ImportJob, hid)
    if job is not None:
        db.refresh(job)
    if job is None or job.status not in BUSY:
        db.rollback()
        return None
    job.status = "applying"
    db.commit()
    return job


def work_job(
    db: Session,
    hid: str,
    stop: threading.Event | None = None,
    *,
    as_role: Role | None = None,
) -> str:
    """Apply a job a batch at a time, until every row is worked or it stops.

    This is the worker's part, beside the requests. Between two batches the one
    writer's place is let go for long enough that a change which waits for it gets it.
    When `stop` is set, the job stops after the batch it is in, to be resumed. An error
    nobody foresaw undoes the batch it happened in, keeps the batches before it, and
    stops the job. Return the status the job ends in, or "" when it was not to apply.

    `as_role` is given by a command of the server that applies a job of its own, which
    no account asked for, and is the role every batch is worked with. The worker of the
    server gives none, and works each batch with the role that whoever asked holds then.
    """
    stop = stop or threading.Event()
    job = _take(db, hid)
    if job is None:
        return ""
    try:
        context = _context(db, hid)
        role = as_role or _role(db, context)
        if role is None or not role.allows(Role.INVENTORY):
            _stop(
                db,
                hid,
                "who asked for it to be applied no longer holds the Inventory role; "
                "anybody who does may apply it again to resume it",
            )
            db.commit()
            return "stopped"
        which = entity(job.entity)
        working = replace(context, via="import") if job.source == "file" else context
        run = Run(db, working, role, job.mode)
        run.given_role = as_role
        run.system_hid = job.system_hid
        # A job that is resumed knows again what its earlier batches made only for a
        # reference, so that a row that describes one of them is worked as previewed.
        run.stubs |= _stubs_made(db, hid)
        cut, typed = _plan(db, hid, run, which)
        for number, batch in enumerate(cut):
            if number and stop.wait(PAUSE_BETWEEN_BATCHES):
                _stop(
                    db,
                    hid,
                    "the server stopped while it was being applied; apply it again to resume",
                )
                db.commit()
                return "stopped"
            try:
                _apply_waiting(db, run, which, hid, batch, typed, stop)
            except RoleLost:
                db.rollback()
                _stop(
                    db,
                    hid,
                    "who asked for it to be applied no longer holds the Inventory role; "
                    "anybody who does may apply it again to resume it",
                )
                db.commit()
                return "stopped"
        _complete(db, hid, context)
        return "applied"
    except Exception as error:
        db.rollback()
        log.exception("the apply of %s stopped", hid)
        _stop(
            db,
            hid,
            f"an error nobody foresaw stopped it ({type(error).__name__}); the request ID "
            f"is {_context(db, hid).request_id}; apply it again to resume",
        )
        db.commit()
        return "stopped"


def _apply_waiting(
    db: Session,
    run: Run,
    which: Entity,
    hid: str,
    batch: Sequence[_Stored],
    typed: Mapping[int, dict[str, Any]],
    stop: threading.Event,
) -> None:
    """Apply a batch, and when another change holds the writer's place too long, wait and
    try it again from the start: nothing of a batch that waited was kept."""
    while True:
        try:
            _apply_batch(db, run, which, hid, batch, typed)
        except OperationalError as error:
            if not dialect.is_busy(error) or stop.wait(PAUSE_BETWEEN_BATCHES):
                raise
        else:
            return
