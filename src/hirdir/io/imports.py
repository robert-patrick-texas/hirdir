"""Previewing and applying a change to many records: a file, or a bulk edit.

A preview is made by doing the work for real, through the same functions as any other
change, where none of it is kept: in a savepoint that is then undone, or for a large
file on a copy of the database, so that nobody waits for it. What it reports is
therefore what an apply will do, and no rule is written twice.

A preview of more than a hundred rows that a request asks for is worked in the
background (P-325): the request reads and checks what it is sent and stores the job as
previewing, with its rows, and the worker works it out on a copy of the database, as the
request would have, and stores what each row would do once every row is worked.

An apply is asked for by a request, which stores the job as queued, and worked in the
background by the worker (`hirdir.io.background`), which takes it up as applying,
one job at a time, 50 rows to a batch and each batch a transaction of its own (D-185).
It works every row again, compares it with what was previewed, and keeps each row that
agrees. A row whose record has moved on since the preview is left out as stale, and the
rest go on.
"""

import hashlib
import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from sqlalchemy import case, delete, func, insert, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from hirdir import clock, ids
from hirdir.auth.roles import Role
from hirdir.db import dialect, engine
from hirdir.db.models import AuditEvent, ImportJob, ImportRow, User
from hirdir.domain import accounts, audit, deleted, held, items, records, systems
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Conflict, Deleted, Existing, Invalid, NotAllowed, NotFound
from hirdir.io import columns as cells
from hirdir.io import files
from hirdir.io.entities import LISTS, Entity, Run, entity, says_retired
from hirdir.io.files import Row, reason

OUTCOMES = ("create", "update", "unchanged", "rejected")
# What a row that makes its record retired says of it (P-311).
MADE_RETIRED = "makes the record retired"
# What an apply did with a row: as previewed, or not, because it was stale or refused.
APPLIED_OUTCOMES = ("create", "update", "unchanged", "stale", "rejected")
COUNTED = {"create": "created", "update": "updated", "unchanged": "unchanged"}
SOURCES = ("file", "bulk")
# The jobs that are being applied, or wait to be.
BUSY = ("queued", "applying")
# A job whose preview the background work is to work, or is working (P-325).
PREVIEWING = "previewing"
# What a row of such a job holds as its outcome until the preview ends. It is never
# answered: the rows of a job that is previewing are not listed.
WAITING = "waiting"
# Why a job is stopped that the stop of the background work cut short: the process
# that applied it stopped, after the batch it was in or without storing it.
CUT_SHORT = "the background work stopped while it was being applied; apply it again to resume"
# Every so many rows the session lets go of the records it has worked on, so that a
# large file costs no more for each row than a small one.
LET_GO_EVERY = 500
# A preview of more rows than this is worked on a copy of the database, so that it
# holds nobody up while it works. See `engine.trial`.
IN_PLACE_UP_TO = 100
# An apply in the background works this many rows to a transaction (D-185).
BATCH_ROWS = 50
# Between two batches the one writer's place is let go only while a change by somebody
# else is under way, until it is done, a second at the most (P-143, P-324): see
# `engine.wait_for_changes`. A batch that waited longer than `busy_timeout` for the
# place is tried again after this long, in seconds.
AGAIN_AFTER_BUSY = 0.12
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


def _no_record(db: Session, record_type: str, hid: str) -> str:
    """Say that a row's HID names no record: or, where it was deleted by an Admin or
    removed outright, as an address is, when and by whom, as the audit trail says, in
    the words of the 404 of a deleted item (P-311)."""
    what = DELETED_KINDS.get(record_type, record_type.replace("_", " "))
    gone = deleted.missing(db, record_type, hid, what)
    if isinstance(gone, Deleted):
        return str(gone)
    return f"there is no record {hid}"


def _one_of(table: str | None) -> str | None:
    """Return what one record of a table is called, as the trail names a kind: `choice`
    of `choices`, `address` of `addresses`."""
    if table is None:
        return None
    if table.endswith("ies"):
        return table[:-3] + "y"
    if table.endswith(("sses", "xes")):
        return table[:-2]
    return table.removesuffix("s")


def _made_as(run: Run, which: Entity, values: dict[str, Any], hid: str) -> str:
    """Return the HID a row makes its record with: the one it gives, which no record of
    its table has (P-311), so that the file of every table loads into an empty inventory
    with each record as it was, and a reference by HID finds what an earlier file made.

    It is refused where the text is no HID as the server makes one, a UUID of version
    7; where a record of any table has that HID, or had it and was deleted or removed,
    which the audit trail says, since an HID is one record's for good and a file brings
    nothing back; where the row's own key finds another record, which it names, so that
    a file of another inventory makes no second of what this one has; and in a bulk
    edit, which changes records that exist.
    """
    db = run.db
    if run.mode == "update":
        raise Invalid("there is no such record", {"hid": "a bulk edit changes records that exist"})
    if not ids.is_made_hid(hid):
        raise Invalid(
            "there is no such record",
            {"hid": f"there is no record {hid}, and it is no HID, a UUID of version 7"},
        )
    if run.trail_kinds is None:
        run.trail_kinds = deleted.kinds_in_trail(db)
    held = deleted.holder_of(db, hid, run.trail_kinds)
    if held is not None and held.action == deleted.ACTION:
        raise Invalid("there is no such record", {"hid": _no_record(db, held.record_type, hid)})
    held_by = held.record_type if held is not None else _one_of(deleted.table_holding(db, hid))
    if held_by is not None:
        kind = held_by.replace("_", " ")
        one = f"{'an' if kind[:1] in 'aeiou' else 'a'} {kind}"
        raise Conflict(
            f"the HID {hid} is another record's, of {one}",
            {"hid": f"{hid} is the HID of {one}: an HID is one record's, for good"},
        )
    try:
        other = which.find(run, {name: value for name, value in values.items() if name != "hid"})
    except Invalid:
        # The key answers to several records: it finds none of them by itself.
        other = None
    if other is not None and other.hid not in run.made:
        named = which.key(values, other)
        raise Conflict(
            f"this row names {named}, which is another record, by an HID it does not have",
            {"hid": f"{named} has the HID {other.hid}: give that, or leave the HID out"},
            Existing(which.record_type, other.hid, named),
        )
    return hid


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


def _as_in_file(which: Entity, values: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """Return a change with the file's value beside it, `as_in_file`, where an input
    format wrote the value in another form (P-322); a space at either end is no other
    form. A change that a format did not write is returned as it is, with no key of it,
    so that it compares with one a release before stored."""
    if entry["field"] not in which.formatted:
        return entry
    given = records.clean(values.get(entry["field"]))
    if not isinstance(given, str) or given == entry["new"]:
        return entry
    return {**entry, "as_in_file": given}


def _tell(
    which: Entity,
    values: dict[str, Any],
    result: Result,
    record: Any,
    before: dict[str, Any] | None,
    after: dict[str, Any],
    new: bool,
) -> None:
    """Say in result what a row changed, from its record as it read before the row and
    as it reads after it: the changes, and for a record that was there, whether the row
    updated it or left it unchanged."""
    result.changes = [
        _as_in_file(which, values, change)
        for change in _differences(which, before, after)
        if change["field"] not in which.restated
        and (change["field"] not in which.by_the_clock or values.get(change["field"]) is not None)
    ]
    if not new:
        changed = result.changes or record.row_version != result.row_version
        result.outcome = "update" if changed else "unchanged"


@dataclass
class _Waiting:
    """A row whose record is still to be read back, to say what the row changed."""

    result: Result
    record: Any
    before: dict[str, Any] | None
    values: dict[str, Any]
    new: bool
    shown: Any


class _Later:
    """The rows of a batch whose records are read back together, once the batch is
    worked, and not each after its own write (P-324).

    What a row changed is what its record reads as right after its own write. So before
    a row is written, the rows waiting whose reads it may change are read first, as the
    entity's `reach` and `shown` say; a row that is refused is never waiting, since it
    is added only once it is written. Reading the rest together reads what each would
    have read after its own row.

    The records that the rows of a batch name by their HID, or that an apply's preview
    found for them, are read before the batch, together, as they read before any row of
    it: each is what its row reads it as before its write, unless a row before it in the
    batch may have changed what it reads as, which drops it, and its row reads it then.
    """

    def __init__(self, run: Run, which: Entity) -> None:
        self.run, self.which = run, which
        self.waiting: list[_Waiting] = []
        self.befores: dict[str, tuple[dict[str, Any], Any]] = {}

    def read_before(self, found: Sequence[Any]) -> None:
        """Read, together, the records that rows of the batch are to change."""
        wanted = list({one.hid: one for one in found if one.hid not in self.befores}.values())
        if not wanted:
            return
        read = self.which.read_for(self.run, wanted)
        for record, before in zip(wanted, read, strict=True):
            self.befores[record.hid] = (before, self.which.shown(self.run, record))

    def before(self, record: Any) -> dict[str, Any] | None:
        """Return a record as it read before its row, where it was read with the batch
        and nothing since may have changed it; None where it is to be read now."""
        found = self.befores.pop(record.hid, None)
        return None if found is None else found[0]

    def before_write(self, record: Any | None, values: dict[str, Any]) -> None:
        """Read back the rows waiting, and forget the records read before the batch,
        where the write of a row may change what they read as."""
        if not self.waiting and not self.befores:
            return
        reach = self.which.reach(self.run, record, values)
        if any(reach.touches(one.shown) for one in self.waiting):
            self.read()
        for hid in [hid for hid, (_, shown) in self.befores.items() if reach.touches(shown)]:
            del self.befores[hid]

    def add(
        self,
        result: Result,
        record: Any,
        before: dict[str, Any] | None,
        values: dict[str, Any],
        new: bool,
    ) -> None:
        """Keep a row that is written, to be read back with the rest of its batch."""
        shown = self.which.shown(self.run, record)
        self.waiting.append(_Waiting(result, record, before, values, new, shown))

    def drop(self, result: Result) -> None:
        """Forget a row that was undone after it was written: it is read back never."""
        self.waiting = [one for one in self.waiting if one.result is not result]

    def read(self) -> None:
        """Read back every row waiting, and say in each result what it changed."""
        waiting, self.waiting = self.waiting, []
        if not waiting:
            return
        after = self.which.read_for(self.run, [one.record for one in waiting])
        for one, read in zip(waiting, after, strict=True):
            _tell(self.which, one.values, one.result, one.record, one.before, read, one.new)

    def end_batch(self) -> None:
        """Read back every row of the batch, and forget what was read before it."""
        self.read()
        self.befores.clear()


def _records_of(which: Entity, db: Session, hids: Sequence[str | None]) -> list[Any]:
    """Return the records of some HIDs that there are, read together."""
    wanted = sorted({hid for hid in hids if hid})
    found: list[Any] = []
    for start in range(0, len(wanted), 500):
        piece = wanted[start : start + 500]
        found += db.scalars(select(which.model).where(which.model.hid.in_(piece)))
    return found


def _one(run: Run, which: Entity, values: dict[str, Any], result: Result) -> None:
    """Work one row: find its record, write it, and say in result what that changed.

    The result is filled in as the row goes, so that a row which is refused part-way
    still says which record it was about. Where the run reads its rows back together
    (`run.later`), what the row changed is said once its batch is read back (P-324).
    """
    db = run.db
    hid = values.get("hid")
    made_as: str | None = None
    if hid:
        record = db.get(which.model, hid)
        if record is None and which.keyed_beside_hid:
            record = which.find(
                run, {name: value for name, value in values.items() if name != "hid"}
            )
        if record is None:
            made_as = _made_as(run, which, values, hid)
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
    later: _Later | None = run.later
    before = later.before(record) if later is not None and not new else None
    if later is not None:
        later.before_write(None if new else record, values)
    if before is None and record is not None and not claimed:
        before = which.read_for(run, [record])[0]
    if claimed:
        run.claim(record.hid)
    # A row that makes its record retired makes it so, with the links a retired record
    # keeps (P-311); one that would retire a record that is there is refused by its write.
    retired = records.making_retired() if record is None and says_retired(values) else nullcontext()
    # A link the app keeps to a retired record is taken from a file alone, and not from a
    # bulk edit, which is the API's and held to its rules; and from a row that makes its
    # record, as a file carries an inventory over, and not from one that changes a record
    # that is there, which is held to the API's rules as a change by the API is (P-311).
    filed = run.context.via == "import" and new
    with records.filing() if filed else nullcontext([]) as linked, retired:
        if made_as is not None:
            with ids.given(which.record_type, made_as):
                record = which.write(run, record, values, new)
            if record.hid != made_as:
                raise Invalid("the record was not made with its HID", {"hid": made_as})
        else:
            record = which.write(run, record, values, new)
    # A row that makes its record retired says so plainly, and so does a link the app
    # keeps to a retired record, in the row's notes, which the preview shows (P-311).
    if isinstance(retired, nullcontext):
        run.notes.extend(linked)
    else:
        run.notes.extend([MADE_RETIRED, *linked])
    db.flush()
    if later is not None:
        later.add(result, record, before, values, new)
    else:
        _tell(which, values, result, record, before, which.read_for(run, [record])[0], new)
    if new:
        result.record_hid = record.hid
        run.made.add(record.hid)
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
    progress: Callable[[int], None] | None = None,
) -> list[Result]:
    """Work every row, each in a savepoint of its own, and report them in the file's order.

    A row that is refused leaves nothing behind and is reported as rejected. The rows
    numbered in `skip` are not worked at all. `system_hid` is the external system a file
    of items was read from (P-248). `progress`, where it is given, is told how many rows
    have been worked every `BATCH_ROWS` rows and once at the end, so that a preview in the
    background can say how far it has got (P-325).
    """
    run = Run(db, context, role, mode)
    run.system_hid = system_hid
    # The records of every BATCH_ROWS rows are read back together (P-324).
    later = run.later = _Later(run, which) if which.reads_together else None
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
    # What a file of items cannot change is looked up once for it (P-324).
    with held.holding(db) if which.holds else nullcontext():
        places = which.order(run, [typed[number] for number in workable])
        for worked, place in enumerate(places, start=1):
            number = workable[place - 1]
            row = rows[number - 1]
            if later is not None and worked % BATCH_ROWS == 1:
                # What the rows of the batch name by their HID is read before them, and
                # what they look up, together.
                coming = [
                    typed[workable[one - 1]] for one in places[worked - 1 : worked - 1 + BATCH_ROWS]
                ]
                later.read_before(_records_of(which, db, [values.get("hid") for values in coming]))
                which.ready(run, coming)
            run.start_row(number)
            result = Result(row=number, outcome="create", key=which.key(row.values, None))
            savepoint = db.begin_nested()
            try:
                _one(run, which, typed[number], result)
                savepoint.commit()
            except REFUSALS as error:
                savepoint.rollback()
                run.forget_row()
                if later is not None:
                    later.drop(result)
                # What the row would have done is undone. Which record it named is kept.
                result.outcome, result.changes, result.notes = "rejected", [], []
                result.reasons = _reasons(which, error)
            results.append(result)
            if later is not None and (worked % BATCH_ROWS == 0 or worked % LET_GO_EVERY == 0):
                later.end_batch()
            if worked % LET_GO_EVERY == 0:
                run.let_go()
            if progress is not None and worked % BATCH_ROWS == 0:
                progress(worked)
        if later is not None:
            later.end_batch()
            run.later = None
    results.sort(key=lambda result: result.row)
    # What is right or wrong only once every row is in: the members of a stack.
    wrong = which.finish(run)
    for result in results:
        if result.row in wrong and result.outcome != "rejected":
            result.outcome, result.changes, result.notes = "rejected", [], []
            result.reasons = wrong[result.row]
    run.let_go()
    if progress is not None:
        progress(len(places))
    return results


def _count(results: Sequence[Any]) -> dict[str, int]:
    counts = {"created": 0, "updated": 0, "unchanged": 0, "rejected": 0}
    for result in results:
        counts[COUNTED.get(result.outcome, "rejected")] += 1
    return counts


def _worked(
    db: Session,
    context: AuditContext,
    role: Role | None,
    *,
    source: str,
    which: Entity,
    mode: str,
    rows: Sequence[Row],
    system_hid: str | None = None,
    complete: bool = False,
    progress: Callable[[int], None] | None = None,
) -> tuple[list[Result], int]:
    """Work the rows without keeping anything. Return what each would do, and how many
    items a file read from an external system that is everything it reports would mark
    `not_reported`: none where a row is rejected (P-248).

    `progress` is told how far the rows have got, where they are worked on a copy of the
    database: worked in place, in the caller's own session, they say nothing until they
    end, since what `progress` stored in that session would be undone with them.
    """
    working = replace(context, via="import") if source == "file" else context
    with engine.trial(db, in_place=len(rows) <= IN_PLACE_UP_TO) as trying:
        told = progress if trying is not db else None
        results = _work(
            trying, working, role, which, mode, rows, system_hid=system_hid, progress=told
        )
    marks = 0
    if (
        complete
        and system_hid is not None
        and not any(result.outcome == "rejected" for result in results)
    ):
        named = {result.record_hid for result in results if result.row_version is not None}
        marks = len(systems.not_named(db, system_hid, {hid for hid in named if hid}))
    return results, marks


def _job(
    context: AuditContext,
    *,
    source: str,
    which: Entity,
    mode: str,
    rows: Sequence[Row],
    file_name: str | None,
    file_sha256: str | None,
    system_hid: str | None,
    complete: bool,
) -> ImportJob:
    """Return the job of a preview, as yet with none of its rows worked."""
    return ImportJob(
        source=source,
        entity=which.name,
        mode=mode,
        file_name=file_name,
        file_sha256=file_sha256,
        status=PREVIEWING,
        row_count=len(rows),
        rows_previewed=0,
        created_by=context.actor_hid,
        system_hid=system_hid,
        complete=complete if system_hid is not None else None,
        not_reported=0,
    )


def _sent(db: Session, context: AuditContext, job: ImportJob) -> None:
    """Record that a preview was asked for, on its job: who sent it, in which request."""
    audit.record(
        db,
        context,
        "preview",
        "import_job",
        job.hid,
        [change(name, None, getattr(job, name)) for name in ("source", "entity", "row_count")],
    )


def _store(
    db: Session, job: ImportJob, rows: Sequence[Row], results: Sequence[Result], marks: int
) -> None:
    """Store what each row of a preview would do, and its counts, and make it `previewed`:
    one way for a preview worked in the request and one worked in the background."""
    for name, count in _count(results).items():
        setattr(job, name, count)
    job.not_reported = marks
    job.rows_previewed = len(rows)
    job.status = "previewed"
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
    in_background: bool = False,
) -> ImportJob:
    """Work the rows without keeping anything, and store what they would do.

    A file read from an external system that is everything it reports counts how many
    items its apply would mark `not_reported`: none where a row is rejected (P-248).

    With `in_background`, as a request asks, more than `IN_PLACE_UP_TO` rows are not
    worked here: they are stored as they were read, on a job that is `previewing`, for
    the background work to preview (`work_preview`, P-325). Fewer are worked at once.
    """
    job = _job(
        context,
        source=source,
        which=which,
        mode=mode,
        rows=rows,
        file_name=file_name,
        file_sha256=file_sha256,
        system_hid=system_hid,
        complete=complete,
    )
    if in_background and len(rows) > IN_PLACE_UP_TO:
        db.add(job)
        db.flush()
        db.execute(
            insert(ImportRow),
            [
                {
                    "job_hid": job.hid,
                    "row": number,
                    "outcome": WAITING,
                    "values": row.values,
                    # What could not be read, which rejects the row when it is worked.
                    "reasons": row.reasons,
                }
                for number, row in enumerate(rows, start=1)
            ],
        )
        _sent(db, context, job)
        return job
    results, marks = _worked(
        db,
        context,
        role,
        source=source,
        which=which,
        mode=mode,
        rows=rows,
        system_hid=system_hid,
        complete=complete,
    )
    db.add(job)
    _store(db, job, rows, results, marks)
    _sent(db, context, job)
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
    in_background: bool = False,
) -> ImportJob:
    """Read a file, work out what importing it would do, and store that as a preview.

    A file of items may name `system`, the external system it was read from, by whose
    identifier its rows are matched first, and be `complete`, everything that system
    reports (P-248). With `in_background`, a file of more than a hundred rows is read
    and checked here, and stored for the background work to preview (P-325).
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
        in_background=in_background,
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
    file settles what that leaves tied. The rows of a job that is still `previewing` are
    not listed: nothing is known of them yet (P-325).
    """
    job = get_job(db, hid)
    if job.status == PREVIEWING:
        raise Conflict(
            "this preview is still being worked out: its rows are listed once it is previewed",
            {"status": "wait for it to be previewed"},
        )
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


def begin_apply(
    db: Session, context: AuditContext, hid: str, *, source: str, skip_rejected: bool = False
) -> ImportJob:
    """Ask for a preview to be applied in the background, or for a stopped apply to go on.

    Anybody who may change the inventory may ask, whoever made the preview, and it is
    applied once. The job is `queued`, whether another is ahead of it or none: asking
    stores the request and applies nothing. The worker of the background work takes
    it up (`work_job`), one job at a time in the order they were asked for, and it is
    `applying` from then, so that a job is `applying` only where a process has taken
    it (P-263, P-267). A stopped job goes on as it was begun.

    A file of countries or of states that makes or changes one is an Admin's to apply,
    and is refused for any other role; one whose every row changes nothing is anybody's
    who may change the inventory (P-321).
    """
    # Of two that ask at the same moment, the second sees what the first stored: the
    # job taken, or another job ahead of it.
    dialect.hold_other_writers(db)
    job = get_job(db, hid, source)
    db.refresh(job)
    if job.status == PREVIEWING:
        raise Conflict(
            "this preview is still being worked out: it may be applied once it is previewed",
            {"status": "wait for it to be previewed"},
        )
    if job.status == "failed":
        raise Conflict(
            "this preview failed, and is not applied",
            {"status": f"{_again(job)} to make a new preview"},
        )
    if job.entity in LISTS and (job.created or job.updated) and _role(db, context) != Role.ADMIN:
        raise NotAllowed(
            f"an Admin applies a file of {job.entity} that changes them: this needs the admin role"
        )
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
    job.status = "queued"
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
    """Mark stopped every job that was being applied when the background work stopped.

    It is called as the worker starts, before it does anything. Only a worker makes a
    job `applying`, as it takes it up, and one worker works a database: so a job found
    `applying` here is one that the stop of the last worker cut short. A job that
    waited, `queued`, which nobody had taken up, waits still, and is applied in its
    turn. Return the jobs stopped.

    A preview found `previewing` is worked again from its first row in its turn, since
    nothing of it was kept (P-325): it is said again to have worked none.
    """
    found = list(db.scalars(select(ImportJob.hid).where(ImportJob.status == "applying")))
    for hid in found:
        _stop(db, hid, CUT_SHORT)
    db.execute(
        update(ImportJob)
        .where(ImportJob.status == PREVIEWING, ImportJob.rows_previewed != 0)
        .values(rows_previewed=0)
    )
    return found


def next_job(db: Session) -> str | None:
    """Return the job to work next: the one applying, else the one asked for first, of
    the previews that wait for the background work, by when the file was sent (P-325),
    and the applies that wait, by when the apply was asked for."""
    asked = case((ImportJob.status == PREVIEWING, ImportJob.created_at), else_=ImportJob.applied_at)
    return db.scalar(
        select(ImportJob.hid)
        .where(ImportJob.status.in_((*BUSY, PREVIEWING)))
        .order_by(case((ImportJob.status == "applying", 0), else_=1), asked, ImportJob.hid)
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
    # An agent's apply is for the person it was answerable to when it asked (P-316).
    return AuditContext(
        actor_hid=event.actor_hid,
        via=event.via,
        request_id=event.request_id,
        for_hid=event.for_hid,
    )


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
    # A row kept while its record waits to be read back with its batch (P-324): what it
    # did, and what the preview said it would, to be compared once the batch is read.
    waiting: tuple[Result, _Stored] | None = None

    def agrees(self) -> bool:
        """Say whether a row kept while it waited does what was previewed, now that its
        batch is read back, and settle what it did."""
        if self.waiting is None:
            return True
        now, was = self.waiting
        if (now.outcome, now.changes) != (was.outcome, was.changes):
            return False
        self.outcome, self.waiting = now.outcome, None
        return True


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
    later: _Later | None = run.later
    try:
        _one(run, which, values, result)
    except REFUSALS as error:
        savepoint.rollback()
        run.forget_row()
        if later is not None:
            later.drop(result)
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
    # A row whose record waits to be read back is held now to what is known of it, and
    # to what it changed once its batch is read (P-324).
    known = result if later is None else replace(result, outcome=was.outcome, changes=was.changes)
    why = _stale(was, known)
    if why is not None:
        savepoint.rollback()
        run.forget_row()
        if later is not None:
            later.drop(result)
        if result.record_hid is not None and run.seen.get(result.record_hid) == was.row:
            del run.seen[result.record_hid]
            run.made.discard(result.record_hid)
        return _Done("stale", [reason("", why)])
    savepoint.commit()
    done = _Done(result.outcome, record_hid=result.record_hid)
    if later is not None:
        done.waiting = (result, was)
    return done


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

    Where the entity reads its rows back together (P-324), the records of the batch are
    read once it is worked. Should a row then no longer do what was previewed, the batch
    is undone and worked again a row at a time, each read back after its own write, so
    that the row is left out as stale before the rows after it are worked, as it always
    was.
    """
    numbers = {was.row for was in batch}
    refused: dict[int, list[dict[str, str]]] = {}
    together = which.reads_together
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
            run.later = _Later(run, which) if together else None
            # What a file of items cannot change is looked up once for the batch, which
            # holds the writer's place, and again for the next: another request may
            # change any of it between two batches (P-324).
            with held.holding(db) if which.holds else nullcontext():
                if run.later is not None:
                    # The records the preview found for the rows are read before them,
                    # and what the rows look up, together.
                    found = [was.record_hid for was in batch if was.row not in refused]
                    run.later.read_before(_records_of(which, db, found))
                    which.ready(run, [typed[was.row] for was in batch])
                done = {
                    was.row: _Done("rejected", refused[was.row])
                    if was.row in refused
                    else _apply_row(run, which, was, typed[was.row])
                    for was in batch
                }
                disagrees = not _read_back(run, done)
            wrong = (
                {}
                if disagrees
                else {
                    number: why
                    for number, why in which.finish(run).items()
                    if number in numbers and done[number].outcome in COUNTED
                }
            )
            if not disagrees and not wrong:
                _store_batch(db, hid, batch, done)
                break
        except BaseException:
            _undo_batch(db, run, numbers)
            raise
        _undo_batch(db, run, numbers)
        if disagrees:
            # A row would no longer do what was previewed: the batch is worked again a row
            # at a time, which leaves that row out before the rows after it are worked.
            together = False
        else:
            refused.update(wrong)
    run.let_go()
    return done


def _read_back(run: Run, done: Mapping[int, _Done]) -> bool:
    """Read back the rows of a batch whose records wait, and say whether every row does
    what was previewed (P-324). True where none waits."""
    later: _Later | None = run.later
    if later is None:
        return True
    later.end_batch()
    run.later = None
    return all(one.agrees() for one in done.values())


def _undo_batch(db: Session, run: Run, numbers: set[int]) -> None:
    """Undo a batch that was not stored, and forget what its rows taught the run."""
    run.later = None
    db.rollback()
    run.forget_batch()
    for record_hid, number in list(run.seen.items()):
        if number in numbers:
            del run.seen[record_hid]
            run.made.discard(record_hid)


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
    # Within the one transaction that reads, what a file of items cannot change is looked
    # up once (P-324).
    with held.holding(db) if which.holds else nullcontext():
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
    """Return the role that the person who asked for an apply holds now: of an agent, the
    role its person holds it to now (P-316)."""
    user = db.get(User, context.actor_hid) if context.actor_hid else None
    if user is None or user.disabled:
        return None
    return accounts.in_force(db, [user])[user.hid].role


def _take(db: Session, hid: str) -> ImportJob | None:
    """Take a job that is to be applied, as the one that is applying, in a transaction
    of its own before anything of it is worked. None if it is not to be applied."""
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
    writer's place is let go while a change by somebody else is under way, until it is
    done, so that a change which waits for it gets it (P-324).
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
        # And the records its rows made, which a later row may share a key with (P-311).
        run.made |= {
            made
            for made in db.scalars(
                select(ImportRow.record_hid).where(
                    ImportRow.job_hid == hid, ImportRow.applied_outcome == "create"
                )
            )
            if made is not None
        }
        cut, typed = _plan(db, hid, run, which)
        for number, batch in enumerate(cut):
            if number and engine.wait_for_changes(db, stop):
                _stop(db, hid, CUT_SHORT)
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
            if not dialect.is_busy(error) or stop.wait(AGAIN_AFTER_BUSY):
                raise
        else:
            return


# --- a preview in the background (P-325) ----------------------------------------------


class _Cut(Exception):
    """The stop of the background work cut a preview short: it is worked again later."""


# How long a preview in the background waits to store what it worked out again, where
# another change held the writer's place for longer than `busy_timeout`, in seconds.
STORE_AGAIN_AFTER = 0.1


def work(db: Session, hid: str, stop: threading.Event | None = None) -> str:
    """Work a job that the worker found (`next_job`): preview one that is `previewing`
    (P-325), and apply one that is to be applied (D-185). Return the status it ends in,
    or "" where it was neither."""
    status = db.scalar(select(ImportJob.status).where(ImportJob.hid == hid))
    db.rollback()
    if status == PREVIEWING:
        return work_preview(db, hid, stop)
    return work_job(db, hid, stop)


def _sender(db: Session, hid: str) -> AuditContext:
    """Return who sent a preview, through which door, in which request: its event.

    A preview in the background is worked under the request ID of the request that
    sent it, and as the person who sent it.
    """
    event = db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.record_type == "import_job",
            AuditEvent.record_hid == hid,
            AuditEvent.action == "preview",
        )
        .order_by(AuditEvent.at.desc(), AuditEvent.hid.desc())
        .limit(1)
    ).first()
    if event is None:
        return AuditContext(actor_hid=None, via="system")
    # An agent's preview is for the person it was answerable to when it sent it (P-316).
    return AuditContext(
        actor_hid=event.actor_hid,
        via=event.via,
        request_id=event.request_id,
        for_hid=event.for_hid,
    )


def _again(job: ImportJob) -> str:
    """Say how a preview that failed is made again."""
    return "send the file again" if job.source == "file" else "ask for the bulk edit again"


def _take_preview(db: Session, hid: str) -> ImportJob | None:
    """Take a preview that waits for the background work, in a transaction of its own
    before any row of it is worked, as having worked none. None where it does not wait."""
    dialect.hold_other_writers(db)
    job = db.get(ImportJob, hid)
    if job is not None:
        db.refresh(job)
    if job is None or job.status != PREVIEWING:
        db.rollback()
        return None
    job.rows_previewed = 0
    db.commit()
    return job


def _waiting_rows(db: Session, hid: str) -> list[Row]:
    """Return the rows of a preview that waits, as they were read, in the file's order."""
    found = db.execute(
        select(ImportRow.values, ImportRow.reasons)
        .where(ImportRow.job_hid == hid)
        .order_by(ImportRow.row)
    )
    return [Row(values=values or {}, reasons=reasons or []) for values, reasons in found]


def _previewed(
    db: Session,
    hid: str,
    context: AuditContext,
    rows: Sequence[Row],
    results: Sequence[Result],
    marks: int,
) -> None:
    """Store what each row of a preview in the background would do, in place of the rows
    as read, as a preview in the request stores it, and make the job `previewed`, in one
    transaction, with its event."""
    dialect.hold_other_writers(db)
    job = db.get_one(ImportJob, hid)
    db.refresh(job)
    db.execute(delete(ImportRow).where(ImportRow.job_hid == hid))
    _store(db, job, rows, results, marks)
    audit.record(
        db,
        context,
        "previewed",
        "import_job",
        hid,
        [
            change("status", PREVIEWING, job.status),
            *(change(name, None, getattr(job, name)) for name in COUNTED.values()),
            change("rejected", None, job.rejected),
            *([change("not_reported", None, marks)] if job.complete else []),
        ],
    )
    db.commit()


def _fail(db: Session, hid: str, why: str) -> None:
    """Make a preview in the background `failed`, with why, so that it is not applied.
    The rows it held for the work are let go: nothing of them was ever worked out."""
    dialect.hold_other_writers(db)
    job = db.get_one(ImportJob, hid)
    db.refresh(job)
    before = job.status
    db.execute(delete(ImportRow).where(ImportRow.job_hid == hid))
    job.status, job.failure = "failed", why
    # Nobody ended it: the server did, in the course of the preview that was sent.
    sent = _sender(db, hid)
    by_the_server = AuditContext(actor_hid=None, via="system", request_id=sent.request_id)
    audit.record(
        db,
        by_the_server,
        "preview_failed",
        "import_job",
        hid,
        [change("status", before, "failed"), change("failure", None, why)],
    )
    db.commit()


def work_preview(db: Session, hid: str, stop: threading.Event | None = None) -> str:
    """Work out a preview that a request stored for the background work (P-325).

    This is the worker's part, beside the requests. The rows are worked as the person
    who sent them, whose role is looked at again first, on a copy of the database, as a
    preview in the request is (`_worked`), and the job says how far they have got, in
    `rows_previewed`, written to the live database in a transaction of a moment every
    `BATCH_ROWS` rows. Once every row is worked, what each would do is stored and the
    job is `previewed`. A role that is lost, or an error nobody foresaw, makes it
    `failed`, with why. Nothing of a preview is kept until it ends: when `stop` is set,
    it stops after the rows it is in and is worked again from its first row, later.

    Return the status the job is left in: `previewed`, `failed`, or `previewing` where
    a stop cut it short; "" where it did not wait to be previewed.
    """
    stop = stop or threading.Event()
    job = _take_preview(db, hid)
    if job is None:
        return ""
    # What is read of the job is read once, before anything can go wrong.
    source, mode, system_hid, complete = job.source, job.mode, job.system_hid, job.complete
    again = _again(job)
    try:
        context = _sender(db, hid)
        role = _role(db, context)
        if role is None or not role.allows(Role.INVENTORY):
            _fail(
                db,
                hid,
                f"who asked for the preview no longer holds the Inventory role; anybody "
                f"who does may {again}",
            )
            return "failed"
        which = entity(job.entity)
        rows = _waiting_rows(db, hid)
        db.rollback()

        def told(done: int) -> None:
            if stop.is_set():
                raise _Cut
            try:
                db.execute(
                    update(ImportJob).where(ImportJob.hid == hid).values(rows_previewed=done)
                )
                db.commit()
            except OperationalError as error:
                # Another change held the writer's place too long: how far it has got is
                # said at the next rows instead, and nothing of the preview is lost.
                db.rollback()
                if not dialect.is_busy(error):
                    raise

        results, marks = _worked(
            db,
            context,
            role,
            source=source,
            which=which,
            mode=mode,
            rows=rows,
            system_hid=system_hid,
            complete=bool(complete),
            progress=told,
        )
        while True:
            try:
                _previewed(db, hid, context, rows, results, marks)
                break
            except OperationalError as error:
                # Another change held the writer's place too long: nothing was stored,
                # and the rows worked out are stored again a moment later.
                db.rollback()
                if not dialect.is_busy(error):
                    raise
                if stop.wait(STORE_AGAIN_AFTER):
                    raise _Cut from None
        return "previewed"
    except _Cut:
        db.rollback()
        # Worked again from its first row when the background work starts again.
        db.execute(update(ImportJob).where(ImportJob.hid == hid).values(rows_previewed=0))
        db.commit()
        return PREVIEWING
    except Exception as error:
        db.rollback()
        log.exception("the preview of %s failed", hid)
        _fail(
            db,
            hid,
            f"an error nobody foresaw ended it ({type(error).__name__}); the request ID "
            f"is {_sender(db, hid).request_id}; {again}",
        )
        return "failed"
