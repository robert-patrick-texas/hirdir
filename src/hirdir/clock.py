"""Time, in the two forms hirdir stores: aware UTC datetimes and integer milliseconds."""

import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

# Where the reader's own time zone is not known, times are shown in this one. An
# installation changes it with the `time_zone` setting. Times are never shown in UTC.
DEFAULT_ZONE = "America/New_York"


def now() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(UTC)


def now_ms() -> int:
    """Return the current time in milliseconds since the epoch."""
    return time.time_ns() // 1_000_000


def for_reader(moment: datetime, zone: str | None = None) -> str:
    """Return a moment as a person reads it: local time with the zone's short name.

    The zone is the one named, or else the zone of the machine this runs on, which is
    the reader's own at a command line. A machine that keeps its clock in UTC says
    nothing about where its reader is, so the default zone stands in for it.
    """
    if zone is not None:
        local = moment.astimezone(ZoneInfo(zone))
    else:
        local = moment.astimezone()
        if local.tzname() == "UTC":
            local = moment.astimezone(ZoneInfo(DEFAULT_ZONE))
    return local.strftime("%Y-%m-%d %H:%M:%S %Z")
