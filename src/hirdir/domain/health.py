"""Condition, observation and health: how an item, a stack or a cluster is doing.

Three facts are kept apart, because different people know them and they change at
different speeds. The condition is the state of the hardware as a person knows it, and
holds while the item is on a shelf. The observed status is what is seen: on the
network, or by a person who looked. The intent, `expected_online`, is what is meant.

Health is what the three say together. It is worked out here each time it is asked
for, and stored nowhere, so it is right the moment any of the three changes.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from hirdir import clock
from hirdir.domain import records
from hirdir.domain.errors import Invalid

CONDITION_LIST = "item_condition"
# The conditions that health knows. A site may add others to the list: they say
# nothing about health either way.
FAILED_CONDITIONS = ("failed", "dead")
POOR_CONDITIONS = ("degraded", "suspect")
GOOD_CONDITION = "good"
UNTESTED_CONDITION = "untested"

OBSERVED = ("online", "degraded", "unreachable", "present")
UNREACHABLE = "unreachable"
OBSERVED_DEGRADED = "degraded"
# Seen and in order: on the network, or by a person who looked.
SEEN_WELL = ("online", "present")

GOOD, DEGRADED, FAILED, UNKNOWN = "good", "degraded", "failed", "unknown"
HEALTHS = (GOOD, DEGRADED, FAILED, UNKNOWN)
# The states in which a member of a group is not doing its work.
OUT_OF_SERVICE = ("Down", "Pending-Removal")
HAS_HEALTH = ("stack", "cluster")
# The moments an observation may have: none before the inventory could hold it, and
# none further ahead than clocks and time zones may differ.
EARLIEST = datetime(2000, 1, 1, tzinfo=UTC)
AHEAD = timedelta(days=1)


@dataclass(frozen=True)
class Health:
    """How a record is doing, and why."""

    value: str
    reasons: tuple[str, ...] = ()


def of_item(
    condition: str | None, observed_status: str | None, expected_online: bool | None
) -> Health:
    """Return the health of an item: the worst of what its three facts say.

    The same cascade, in SQL, is `hirdir.io.fields.HEALTH`, and a test holds the two
    together.
    """
    failed, degraded = [], []
    if condition in FAILED_CONDITIONS:
        failed.append(f"its condition is {condition}")
    if observed_status == UNREACHABLE:
        if expected_online:
            failed.append("it is expected online and is observed unreachable")
        else:
            degraded.append("it is observed unreachable")
    if failed:
        return Health(FAILED, tuple(failed))
    if condition in POOR_CONDITIONS:
        degraded.append(f"its condition is {condition}")
    if observed_status == OBSERVED_DEGRADED:
        degraded.append("it is observed degraded")
    if degraded:
        return Health(DEGRADED, tuple(degraded))
    good = []
    if condition == GOOD_CONDITION:
        good.append("its condition is good")
    if observed_status in SEEN_WELL:
        good.append(f"it is observed {observed_status}")
    if good:
        return Health(GOOD, tuple(good))
    # Nothing decides it. What is said of the condition is told all the same: untested
    # is not known good, and a condition of the site's own says nothing either way.
    if condition is None:
        said = "nothing is said of its condition"
    elif condition == UNTESTED_CONDITION:
        said = f"its condition is {condition}"
    else:
        said = f"its condition is {condition}, which says nothing of its health"
    return Health(UNKNOWN, (f"{said}, and nothing is observed",))


def _counted(count: int, what: str) -> str:
    return f"{count} member is {what}" if count == 1 else f"{count} members are {what}"


def of_group(
    group_type: str,
    members: Sequence[tuple[Health, str | None]],
    observed_status: str | None,
    expected_members: int | None,
) -> Health | None:
    """Return the health of a stack or a cluster, from its members and what is seen of it.

    `members` holds, for each current member, its own health and its lifecycle state.
    A controller domain and a custom group have no health.
    """
    if group_type not in HAS_HEALTH:
        return None
    if not members:
        return Health(UNKNOWN, ("it has no members",))
    healths = [health.value for health, _ in members]
    failed, degraded = [], []
    if observed_status == UNREACHABLE:
        failed.append("it is observed unreachable")
    if all(value == FAILED for value in healths):
        failed.append("every member is failed")
    if failed:
        return Health(FAILED, tuple(failed))
    if observed_status == OBSERVED_DEGRADED:
        degraded.append("it is observed degraded")
    for value in (FAILED, DEGRADED):
        if count := healths.count(value):
            degraded.append(_counted(count, value))
    if count := sum(1 for _, state in members if state in OUT_OF_SERVICE):
        degraded.append(_counted(count, "in Down or Pending-Removal"))
    if expected_members is not None and len(members) < expected_members:
        degraded.append(f"it has {len(members)} of the {expected_members} members it is to have")
    elif expected_members is None and group_type == "stack" and len(members) == 1:
        degraded.append("it is one switch alone")
    if degraded:
        return Health(DEGRADED, tuple(degraded))
    if observed_status in SEEN_WELL:
        return Health(GOOD, (f"it is observed {observed_status}",))
    if all(value == GOOD for value in healths):
        return Health(GOOD, ("every member is good",))
    return Health(UNKNOWN, ("nothing is observed of it, and not every member is known good",))


def moment(value: Any, field: str, zone: str) -> datetime:
    """Return a moment something was seen at, in UTC, or refuse one that cannot be kept.

    A moment that names no zone is in `zone`, the application's time zone: it is typed
    as it is read. One that the calendar does not reach, or that lies ahead, is refused:
    nothing is seen in the future.
    """
    refusal = Invalid(
        "the moment is not acceptable",
        {field: "a date and time in ISO 8601, such as 2026-11-14T15:04:05Z, and not ahead"},
    )
    if not isinstance(value, datetime):
        raise refusal
    try:
        at = clock.in_zone(value, zone).astimezone(UTC)
    except OverflowError, ValueError:
        raise refusal from None
    if not EARLIEST <= at <= clock.now() + AHEAD:
        raise refusal
    return at


def observation(
    fields: dict[str, Any], record: Any | None, zone: str, looked_again: bool = True
) -> dict[str, Any]:
    """Return the observed status and its moment, as a change sets them.

    A status that is set is seen now, unless the change says when. A person who states
    it again as it is has looked again, and the moment is now. A file that states it
    again, with no moment, has `looked_again` false and changes nothing, so that the
    same file loaded twice changes nothing. Clearing the status clears the moment. A
    moment with no status is nothing, and a moment is not cleared by itself.
    """
    if "observed_status" not in fields and "observed_at" not in fields:
        return {}
    current = record.observed_status if record is not None else None
    status = current
    if "observed_status" in fields:
        given = records.clean(fields["observed_status"])
        if given is not None:
            given = records.key(str(given))
            if given not in OBSERVED:
                raise Invalid(
                    "the observed status is not acceptable",
                    {"observed_status": f"one of {', '.join(OBSERVED)}"},
                )
        status = given
    at = fields.get("observed_at")
    if at is not None:
        at = moment(at, "observed_at", zone)
    if status is None:
        if at is not None:
            raise Invalid(
                "nothing is observed at that moment",
                {"observed_at": "give observed_status with it"},
            )
        return {"observed_status": None, "observed_at": None}
    if at is None and "observed_status" not in fields:
        raise Invalid(
            "a moment is not cleared by itself",
            {"observed_at": "clear observed_status, and the moment goes with it"},
        )
    if at is None:
        restated = status == current and record is not None and record.observed_at is not None
        at = record.observed_at if restated and not looked_again else clock.now()
    return {"observed_status": status, "observed_at": at}
