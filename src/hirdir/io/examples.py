"""The examples: the fictional inventory of `examples/`, loaded with one command.

`hirdir admin load-examples` loads every file of the examples, in the load order, into
an inventory that holds nothing yet, so that a site can try `hirdir` and clear it again
with `hirdir admin reset`, which then takes the examples and nothing of the site's own
(P-166). The lists of countries and states, which a reset keeps, are not loaded (P-321).
Each file is previewed and applied as any import is, through the same functions, so
that no rule is written twice. It is reached from that command on the
server and from nowhere else: no route calls it.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hirdir.auth.roles import Role
from hirdir.db.models import ImportJob, ImportRow
from hirdir.domain import audit, reset
from hirdir.domain.errors import Conflict, Invalid, NotFound
from hirdir.ids import new_hid
from hirdir.io import imports
from hirdir.io.entities import LISTS, LOAD_ORDER

# The examples are loaded from their CSV files; the JSON files hold the same records.
FORMAT = "csv"
# The role the examples are loaded with: the one an import asks of anybody.
ROLE = Role.INVENTORY
# How many rejected rows a refusal names before it says how many more there are.
NAMED = 5
# The files that are loaded, in the load order: what a reset clears. The lists of
# countries and states are in the examples as an export writes them, and are not loaded:
# a reset keeps them, as it keeps the choices, and every inventory has them from its
# install, which the examples are never to change (P-321).
LOADED = tuple(name for name in LOAD_ORDER if name not in LISTS)


@dataclass(frozen=True)
class Loaded:
    """One file of the examples, applied: its stored import, and how many records it made."""

    file_name: str
    job_hid: str
    created: int


def stem(entity: str) -> str:
    """Return the name of the example file of an entity, without its extension."""
    return entity.replace("_", "-")


def file_name(entity: str, format_: str = FORMAT) -> str:
    """Return the name of the example file of an entity."""
    return f"{stem(entity)}.{format_}"


def folder() -> Path:
    """Return where this installation keeps the examples.

    A package carries them inside the application, beside its code, so that a host whose
    dpkg leaves out /usr/share/doc, as a minimal or container image does, still has them.
    A development checkout has them at its top, where `make examples` writes them.
    """
    code = Path(__file__).resolve().parent.parent
    carried = code / "examples"
    for candidate in (carried, code.parent.parent / "examples"):
        if (candidate / file_name(LOAD_ORDER[0])).is_file():
            return candidate
    raise NotFound(f"the examples are not in this installation: there is no {carried}")


def check(db: Session) -> None:
    """Refuse unless the inventory is empty and no import waits to be applied.

    The examples are never mixed with a site's own records, so that a reset takes them
    and nothing else. An import that waits would be applied beside them once the
    service starts.
    """
    # In the load order, which is the order a reset clears them in, the other way round.
    held = list(reversed(reset.held(db).items()))
    if held:
        named = ", ".join(f"{count:,} {name.replace('_', ' ')}" for name, count in held[:NAMED])
        more = f" and {len(held) - NAMED} kinds of record more" if len(held) > NAMED else ""
        raise Conflict(
            f"the inventory is not empty: it holds {named}{more}",
            {
                "inventory": "the examples are loaded into an empty inventory only, "
                "which `hirdir admin reset` makes it"
            },
        )
    waiting = db.scalar(
        select(func.count()).select_from(ImportJob).where(ImportJob.status.in_(imports.BUSY))
    )
    if waiting:
        raise Conflict(
            f"{waiting} imports wait to be applied, and would be applied beside the examples",
            {"imports": "start the service and let them be applied, then clear the inventory"},
        )


def _rejected(db: Session, hid: str) -> dict[str, str]:
    """Return the first rejected rows of a preview, each with its reasons."""
    rows = db.scalars(
        select(ImportRow)
        .where(ImportRow.job_hid == hid, ImportRow.outcome == "rejected")
        .order_by(ImportRow.row)
    ).all()
    named = {
        f"row {row.row}": "; ".join(
            f"{reason.get('field', 'row')}: {reason.get('message', '')}"
            for reason in row.reasons or []
        )
        for row in rows[:NAMED]
    }
    if len(rows) > NAMED:
        named["more"] = f"and {len(rows) - NAMED} more rows"
    return named


def _created(db: Session, hid: str) -> tuple[int, int]:
    """Return how many rows of an applied job made a record, and how many were left out."""
    by_outcome: dict[str | None, int] = dict(
        db.execute(
            select(ImportRow.applied_outcome, func.count())
            .where(ImportRow.job_hid == hid)
            .group_by(ImportRow.applied_outcome)
        ).all()
    )
    return by_outcome.get("create", 0), by_outcome.get("rejected", 0) + by_outcome.get("stale", 0)


def load(
    db: Session,
    source: Path,
    each: Callable[[Loaded], None] | None = None,
) -> list[Loaded]:
    """Load every file of the examples in source, in the load order, and say what each made.

    Each file is previewed, applied when no row of it is rejected, and kept as a stored
    import named for its file, audited as the system. A file with a rejected row stops
    the load there, and what the files before it made stays, for a reset to clear. `each`
    is told of every file as soon as it is applied.
    """
    check(db)
    missing = [file_name(name) for name in LOADED if not (source / file_name(name)).is_file()]
    if missing:
        raise NotFound(
            f"{source} lacks {len(missing)} of the {len(LOADED)} files of the examples, "
            f"the first {missing[0]}"
        )
    loaded = []
    for name in LOADED:
        file = file_name(name)
        # Each file is a request of its own, as an import through the API is: what it
        # made shares its request ID, and no other file's does.
        context = replace(audit.SYSTEM, request_id=new_hid())
        job = imports.preview(
            db,
            context,
            ROLE,
            data=(source / file).read_bytes(),
            format_=FORMAT,
            entity_name=name,
            file_name=file,
        )
        db.commit()
        if job.rejected:
            raise Invalid(
                f"{job.rejected} of the {job.row_count} rows of {file} are rejected, "
                "so the load stopped there",
                _rejected(db, job.hid),
            )
        hid = job.hid
        imports.begin_apply(db, context, hid, source="file")
        db.commit()
        status = imports.work_job(db, hid, as_role=ROLE)
        # The worker lets go of what it held between its batches: the job is read again.
        job = db.get_one(ImportJob, hid)
        if status != "applied":
            raise Conflict(f"{file} was not applied: {job.failure or status}")
        created, left_out = _created(db, hid)
        if left_out:
            raise Conflict(
                f"{left_out} of the rows of {file} were left out when it was applied, "
                "so the load stopped there",
                {"import": hid},
            )
        done = Loaded(file, hid, created)
        loaded.append(done)
        if each is not None:
            each(done)
    return loaded
