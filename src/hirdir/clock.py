"""Time, in the two forms hirdir stores: aware UTC datetimes and integer milliseconds."""

import re
import time
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

# Every time is shown in the application's time zone, so that everybody refers to the
# same time. It is the `time_zone` setting, and this zone until that is changed.
DEFAULT_ZONE = "America/New_York"


def now() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(UTC)


def now_ms() -> int:
    """Return the current time in milliseconds since the epoch."""
    return time.time_ns() // 1_000_000


def today(zone: str = DEFAULT_ZONE) -> date:
    """Return today's date in the application's time zone."""
    return now().astimezone(ZoneInfo(zone)).date()


def shown(moment: datetime, zone: str = DEFAULT_ZONE) -> str:
    """Return a moment as a person reads it: the application's time, with the zone's name."""
    return moment.astimezone(ZoneInfo(zone)).strftime("%Y-%m-%d %H:%M:%S %Z")


def stamp(moment: datetime, zone: str = DEFAULT_ZONE) -> str:
    """Return a moment for a file name: the application's time with its offset from UTC.

    `20261112T210000-0500`. The offset keeps two names apart in the hour that comes
    twice when the clocks go back.
    """
    return moment.astimezone(ZoneInfo(zone)).strftime("%Y%m%dT%H%M%S%z")


_STAMP = re.compile(r"(\d{8}T\d{6})(Z|[+-]\d{4})")


def of_stamp(text: str) -> datetime | None:
    """Return the moment a stamp in a file name stands for, or None when it holds none.

    Reads the stamps of this version and the `...Z` stamps that earlier versions wrote.
    """
    found = _STAMP.search(text)
    if found is None:
        return None
    offset = "+0000" if found[2] == "Z" else found[2]
    try:
        return datetime.strptime(found[1] + offset, "%Y%m%dT%H%M%S%z")
    except ValueError:
        return None
