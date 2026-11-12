"""Time, in the two forms hirdir stores: aware UTC datetimes and integer milliseconds."""

import time
from datetime import UTC, datetime


def now() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(UTC)


def now_ms() -> int:
    """Return the current time in milliseconds since the epoch."""
    return time.time_ns() // 1_000_000
