"""Settings: the installation-wide values that people change in the course of work.

Each setting has a default written here. The database keeps a row only for a setting
that has been given a value, so a default that a later release changes is not held back
by a copy made at install time.

What a site may not change is listed beside them, said to be fixed (D-187): what was
decided, with the decision, and the limits that protect the service. Each is the very
value that is used, read from where it lives.
"""

import os
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import cache
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from hirdir import clock
from hirdir.db.models import Setting
from hirdir.domain import file_kinds, lifecycle, load, product, records
from hirdir.domain.audit import AuditContext
from hirdir.domain.errors import Invalid, NotFound

# The kinds of a model. The three in the middle run on a host (P-246): see
# `hirdir.domain.hosting`.
CATALOG_KINDS = (
    "hardware",
    "virtual_machine",
    "virtual_context",
    "container",
    "software",
    "service",
)
BIGGEST = Decimal(10) ** 12
# How far ahead or how long a number of days may say: a hundred years.
MOST_DAYS = 36_500
# How many items one request may cover, add to a group or receive, at most, whatever
# `max_items_per_request` says: the API takes no more.
FEWEST_ITEMS_PER_REQUEST = 100
MOST_ITEMS_PER_REQUEST = 5000
# The most a default or a minimum of support weight may be (P-155).
MOST_WEIGHT = Decimal(1_000_000)
# How long after the newest change the second process works the long reports out again
# by day, in seconds, and the longest that may be (P-276). 0: not by day.
AHEAD_SETTING = "reports_ahead_after_seconds"
DEFAULT_AHEAD_AFTER_SECONDS = 30
MOST_AHEAD_AFTER_SECONDS = 3600
# The least length of an access code that is typed, by the person whose it is or by an
# Admin (P-295). A code the server makes is not held to it, nor one that is held already.
CODE_LENGTH_SETTING = "access_code_min_length"
DEFAULT_CODE_LENGTH = 12
MOST_CODE_LENGTH = 64


def _refuse(key: str, expected: str) -> Invalid:
    return Invalid(f"the value of {key} is not acceptable", {"value": expected})


@dataclass(frozen=True)
class Check:
    """What values a setting takes: said for people, and checked."""

    accepts: str
    check: Callable[[Any], Any]
    # The values to choose from, where the setting is one or more of a list.
    options: Callable[[], tuple[str, ...]] | None = None


def _number(key: str, low: Decimal, high: Decimal | None, above_low: bool = False) -> Check:
    expected = f"a number from {low} to {high}" if high is not None else f"a number above {low}"
    expected += ", with at most two decimal places"

    def check(value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, int | float | str):
            raise _refuse(key, expected)
        try:
            number = Decimal(str(value).strip())
            if not number.is_finite() or abs(number) > BIGGEST:
                raise _refuse(key, expected)
            exact = number == number.quantize(Decimal("0.01"))
        except InvalidOperation:
            raise _refuse(key, expected) from None
        too_low = number <= low if above_low else number < low
        if not exact or too_low or (high is not None and number > high):
            raise _refuse(key, expected)
        return int(number) if number == number.to_integral_value() else float(number)

    return Check(expected, check)


def _whole(key: str, low: int, high: int, unit: str = "") -> Check:
    expected = f"a whole number{unit} from {low:,} to {high:,}"

    def check(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise _refuse(key, expected)
        return value

    return Check(expected, check)


def _month() -> Check:
    expected = "a month number from 1 to 12"

    def check(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 12:
            raise _refuse("fiscal_year_start_month", expected)
        return value

    return Check(expected, check)


def _days(key: str) -> Check:
    return _whole(key, 1, MOST_DAYS, " of days")


def _currency() -> Check:
    expected = "a three-letter currency code, such as USD"

    def check(value: Any) -> str:
        code = value.strip().upper() if isinstance(value, str) else ""
        if len(code) != 3 or not code.isascii() or not code.isalpha():
            raise _refuse("currency", expected)
        return code

    return Check(expected, check)


def _time_zone() -> Check:
    expected = "the name of a time zone, such as America/New_York or Europe/Berlin"

    def check(value: Any) -> str:
        name = value.strip() if isinstance(value, str) else ""
        try:
            if not name or name.startswith(("/", ".")) or "\\" in name:
                raise ValueError
            return ZoneInfo(name).key
        except ValueError, KeyError, OSError:
            raise _refuse("time_zone", expected) from None

    return Check(expected, check)


def _subset(key: str, allowed: Callable[[], tuple[str, ...]]) -> Check:
    def check(value: Any) -> list[str]:
        names = allowed()
        expected = f"a list of one or more of {', '.join(names)}"
        if not isinstance(value, list) or not value:
            raise _refuse(key, expected)
        by_key = {records.key(name): name for name in names}
        chosen = set()
        for entry in value:
            name = by_key.get(records.key(entry)) if isinstance(entry, str) else None
            if name is None:
                raise _refuse(key, expected)
            chosen.add(name)
        return [name for name in names if name in chosen]

    return Check("a list of one or more of the options", check, allowed)


def _one_of(key: str, allowed: Callable[[], tuple[str, ...]]) -> Check:
    def check(value: Any) -> str:
        names = allowed()
        by_key = {records.key(name): name for name in names}
        name = by_key.get(records.key(value)) if isinstance(value, str) else None
        if name is None:
            raise _refuse(key, f"one of {', '.join(names)}")
        return name

    return Check("one of the options", check, allowed)


def _extensions(key: str) -> Check:
    """A list of the extensions of files: those hirdir knows are offered, and an Admin
    may add another of letters and digits, but never one of a web page, a script or a
    program (P-159)."""
    expected = (
        "a list of extensions of letters and digits, up to ten each, such as pdf, "
        "and none of a web page, a script or a program: " + ", ".join(file_kinds.REFUSED)
    )

    def check(value: Any) -> list[str]:
        if not isinstance(value, list):
            raise _refuse(key, expected)
        chosen: list[str] = []
        for entry in value:
            name = entry.strip().lower().removeprefix(".") if isinstance(entry, str) else ""
            if not file_kinds.EXTENSION.fullmatch(name) or name in file_kinds.REFUSED:
                raise _refuse(key, expected)
            if name not in chosen:
                chosen.append(name)
        return chosen

    return Check(expected, check, lambda: file_kinds.DEFAULT_TYPES)


MAP_LINK = "map_link"
# Where the coordinates of a place go in the address of a map (P-229, P-236).
MAP_PLACES = ("{latitude}", "{longitude}")
DEFAULT_MAP = "https://www.google.com/maps/search/?api=1&query={latitude},{longitude}"


# What the address of a map may hold nowhere, beside a control character (P-229).
MAP_REFUSED = frozenset(['"', "'", "<", ">", "\\"])


def _map_link() -> Check:
    """Blank, or an address on the web, as a link is, of a host of its own, with where
    the latitude and the longitude go after the host."""
    expected = (
        "blank, or a web address, https:// or http://, with both {latitude} and "
        "{longitude} after its host, and no user or password, space, quote, < > or \\"
    )

    def check(value: Any) -> str:
        if not isinstance(value, str):
            raise _refuse(MAP_LINK, expected)
        if not value.strip():
            return ""
        try:
            url = records.checked_url(MAP_LINK, value)
        except Invalid:
            raise _refuse(MAP_LINK, expected) from None
        if url is None or any(
            character in MAP_REFUSED or unicodedata.category(character).startswith("C")
            for character in url
        ):
            raise _refuse(MAP_LINK, expected)
        try:
            # A host in brackets that is no address, or a port that is no number, is
            # refused here by the parser itself: with the words of the rule, not its own.
            parts = urlsplit(url)
            host, named, _port = parts.netloc, parts.hostname, parts.port
        except ValueError:
            raise _refuse(MAP_LINK, expected) from None
        after = f"{parts.path}?{parts.query}#{parts.fragment}"
        if (
            not host
            or not named
            or "@" in host
            or "{" in host
            or "}" in host
            or not all(place in after for place in MAP_PLACES)
        ):
            raise _refuse(MAP_LINK, expected)
        return url

    return Check(expected, check)


def usable_map_link(value: Any) -> str | None:
    """Return the address of a map that the setting holds where its rule takes it, and
    None where it is blank or a value stored before the rule was what it is: no place's
    answer is made of that."""
    try:
        return _map_link().check(value) or None
    except Invalid, ValueError:
        return None


def _processors() -> int:
    """Return how many processors the host has: the most the threads of one process
    can use at once, each to its 100 percent (P-265)."""
    return os.cpu_count() or 1


def _states() -> tuple[str, ...]:
    return lifecycle.STATES


def _kinds() -> tuple[str, ...]:
    return CATALOG_KINDS


def _sides() -> tuple[str, ...]:
    return ("a", "z")


def _end_of_life_dates() -> tuple[str, ...]:
    # The four dates are the catalog's, which reads the settings: it is asked when
    # they are wanted, once both are loaded.
    from hirdir.domain import catalog

    return catalog.DATES


@dataclass(frozen=True)
class Spec:
    """One setting: its default, what it means, and what values it takes."""

    default: Any
    meaning: str
    takes: Check

    def check(self, value: Any) -> Any:
        return self.takes.check(value)


SPECS: dict[str, Spec] = {
    "stack_discount_pct": Spec(
        50,
        "applied to stack members whose model sets none",
        _number("stack_discount_pct", Decimal(0), Decimal(100)),
    ),
    "currency": Spec("USD", "label only", _currency()),
    "time_zone": Spec(
        clock.DEFAULT_ZONE,
        "the zone times are shown in where the reader's own zone is not known",
        _time_zone(),
    ),
    "fiscal_year_start_month": Spec(
        1,
        "for reports grouped by fiscal year",
        _month(),
    ),
    "count_states": Spec(
        ["Assigned", "Test", "Prod", "Down", "Pending-Removal"],
        "states that count toward the component count",
        _subset("count_states", _states),
    ),
    "weight_states": Spec(
        ["Test", "Prod", "Down"],
        "states that carry support weight",
        _subset("weight_states", _states),
    ),
    "service_states": Spec(
        ["Assigned", "Test", "Prod", "Down"],
        "states in which an item is in service, for the coverage report",
        _subset("service_states", _states),
    ),
    "count_kinds": Spec(
        # What runs on a host is counted from the start (P-246). An installation that
        # has set the setting itself keeps what it set.
        ["hardware", "virtual_machine", "virtual_context", "container"],
        "kinds in the headline component count",
        _subset("count_kinds", _kinds),
    ),
    "weight_per_resource_unit": Spec(
        300,
        "how much support weight one resource unit carries",
        _number("weight_per_resource_unit", Decimal(0), None, above_low=True),
    ),
    "renewal_warning_days": Spec(
        90,
        "how far ahead a contract counts as ending soon: the renewal worklist, the alert "
        "after sign-in and the coverage report's list of what runs out soon",
        _days("renewal_warning_days"),
    ),
    "renewal_pending_overdue_days": Spec(
        60,
        "how long a renewal may be pending, counted from the end of the term it is for, "
        "before it is overdue",
        _days("renewal_pending_overdue_days"),
    ),
    "end_of_life_within_days": Spec(
        730,
        "how far ahead the end-of-life report counts a date as approaching",
        _days("end_of_life_within_days"),
    ),
    "end_of_life_date": Spec(
        "ldos",
        "which of the four end-of-life dates the end-of-life report is of, unless asked",
        _one_of("end_of_life_date", _end_of_life_dates),
    ),
    "max_items_per_request": Spec(
        1000,
        "how many items one request may cover, add to a group or receive; the web UI and "
        "the command line send their pieces by it",
        _whole("max_items_per_request", FEWEST_ITEMS_PER_REQUEST, MOST_ITEMS_PER_REQUEST),
    ),
    # The defaults and minimums of support weight (P-141, P-155): blank unless an Admin
    # sets one, so that nothing is counted that nobody chose.
    "default_item_weight": Spec(
        None,
        "the support weight of a major item that neither it nor its model gives",
        _number("default_item_weight", Decimal(0), MOST_WEIGHT),
    ),
    "minimum_item_weight": Spec(
        None,
        "the least support weight a major item counts at, where it has one",
        _number("minimum_item_weight", Decimal(0), MOST_WEIGHT),
    ),
    "default_site_weight": Spec(
        None,
        "the support weight of a site that gives none of its own",
        _number("default_site_weight", Decimal(0), MOST_WEIGHT),
    ),
    "minimum_site_weight": Spec(
        None,
        "the least support weight a site counts at, where it has one",
        _number("minimum_site_weight", Decimal(0), MOST_WEIGHT),
    ),
    "default_circuit_weight": Spec(
        None,
        "the support weight of a circuit that gives none of its own",
        _number("default_circuit_weight", Decimal(0), MOST_WEIGHT),
    ),
    "minimum_circuit_weight": Spec(
        None,
        "the least support weight a circuit counts at, where it has one",
        _number("minimum_circuit_weight", Decimal(0), MOST_WEIGHT),
    ),
    "reference_file_types": Spec(
        list(file_kinds.DEFAULT_TYPES),
        "the extensions of the files a reference may be; one that is not known here "
        "is kept and downloaded as application/octet-stream. A change of it changes no "
        "file that is kept",
        _extensions("reference_file_types"),
    ),
    "circuit_cost_side": Spec(
        "a",
        "the side, a or z, whose site a new circuit's cost and support weight count at; "
        "a change of it changes no circuit that exists",
        _one_of("circuit_cost_side", _sides),
    ),
    # 0.9.2: the name a site gives the product, and whom to ask (P-168, P-169).
    "product_name": Spec(
        product.DEFAULT_NAME,
        "the name the web page gives the product, and the first part of the name of a "
        "downloaded file; the commands, the package and the API keep the name hirdir",
        Check(
            f"a name of 1 to {product.MOST_NAME} characters, with neither < nor > nor a "
            "control character",
            product.check_name,
        ),
    ),
    "help_organization": Spec(
        None,
        "the group that runs this installation, named on About under Whom to ask",
        Check(
            f"a name of 1 to {product.MOST_ORGANIZATION} characters, with neither < nor > "
            "nor a control character",
            product.check_organization,
        ),
    ),
    "help_email": Spec(
        None,
        "the email address to write to for help with this installation",
        Check(
            "a plain email address, such as tools@example.net, with no space and none of "
            "? & = % / : ; , \" '",
            product.check_email,
        ),
    ),
    "help_phone": Spec(
        None,
        "the number to call for help with this installation, shown as it is typed",
        Check(
            f"a number of at most {product.MOST_PHONE} characters: digits, spaces, letters "
            "and + - ( ) . , # *",
            product.check_phone,
        ),
    ),
    "help_url": Spec(
        None,
        "an address on the web for help with this installation, such as the team's page",
        Check("an address that begins with https:// or http://", product.check_url),
    ),
    "help_on_sign_in": Spec(
        False,
        "whether the sign-in page lists whom to ask as well, where anyone who reaches the "
        "site sees it",
        Check("true or false", product.check_flag("help_on_sign_in")),
    ),
    # 0.9.7: the map that the coordinates of a place open (P-229, P-236).
    MAP_LINK: Spec(
        DEFAULT_MAP,
        "the map that the coordinates of a site or a location open, with {latitude} and "
        "{longitude} where they go. Blank, they are plain numbers",
        _map_link(),
    ),
    # 0.9.10: the ceiling past which the server answers that it is busy (P-265). The
    # meter keeps the three in memory, from the moment one is saved.
    load.RESPONSE_SETTING: Spec(
        load.DEFAULT_RESPONSE_MS,
        "how long requests may take before the server is busy, in milliseconds: the "
        "95th percentile of the reads and the changes of the API that came over the "
        "last busy_over_seconds, with the wait of those still in flight, which of "
        "twenty or fewer is the slowest. Its thirds are the health of the server: good "
        "under a third, slow to two thirds, very slow to the whole and busy past it. "
        "What is refused is decided by the reads alone, where twenty-one or more of "
        "them came in that time: reports, exports and previews are answered 503 Busy "
        "where the reads are very slow, and every read where they are busy. 0: nothing "
        "is refused for it, and the health is said by the thirds of 3000",
        _whole(load.RESPONSE_SETTING, 0, load.MOST_RESPONSE_MS, " of milliseconds"),
    ),
    load.PROCESSOR_SETTING: Spec(
        load.DEFAULT_CPU_PERCENT,
        "the processor time the server's process may use over the last "
        "busy_over_seconds, as a percentage of one processor, before the health of the "
        "server is very slow at the least, and reports, exports and previews are "
        "answered 503 Busy. The process passes 100 where several requests are in the "
        "database at once, so it takes up to 100 for each processor of the host. 0: not "
        "looked at, and both at 0 is no ceiling",
        _whole(load.PROCESSOR_SETTING, 0, load.CPU_PERCENT_OF_A_PROCESSOR * _processors()),
    ),
    load.OVER_SETTING: Spec(
        load.DEFAULT_OVER_SECONDS,
        "over how long the two measures of the ceiling are read, in seconds, and for "
        "how long after it last refused its reads the server refuses what is long",
        _whole(load.OVER_SETTING, load.FEWEST_OVER_SECONDS, load.MOST_OVER_SECONDS, " of seconds"),
    ),
    # 0.9.11: the long reports worked out again by day (P-276). The second process reads
    # it at each look.
    AHEAD_SETTING: Spec(
        DEFAULT_AHEAD_AFTER_SECONDS,
        "how long after the newest change the background work works the long reports "
        "out again, in seconds. 0: when it starts and at five past midnight alone",
        _whole(AHEAD_SETTING, 0, MOST_AHEAD_AFTER_SECONDS, " of seconds"),
    ),
    # 0.9.14: the least length of a typed access code (P-295).
    CODE_LENGTH_SETTING: Spec(
        DEFAULT_CODE_LENGTH,
        "the least length of an access code that is typed, by a person for themselves or "
        "by an Admin for an account. A code the server makes is not held to it, and a "
        "code that is held already is not looked at",
        _whole(CODE_LENGTH_SETTING, 1, MOST_CODE_LENGTH, " of characters"),
    ),
}


@dataclass(frozen=True)
class SettingValue:
    """A setting as it stands: its value in force and whether that is the default.

    A fixed value is listed in the same way, with `fixed` true, the reason it is fixed
    and the decision that fixed it, if one did: it is always at its default.
    """

    key: str
    value: Any
    default: Any
    is_default: bool
    meaning: str
    row_version: int
    updated_at: datetime | None
    updated_by: str | None
    accepts: str | None = None
    options: tuple[str, ...] | None = None
    fixed: bool = False
    reason: str | None = None
    decision: str | None = None


def _spec(key: str) -> Spec:
    spec = SPECS.get(key)
    if spec is None:
        if key in fixed_values():
            raise Invalid(
                f"{key} is fixed", {"value": f"{key} is fixed: {fixed_values()[key].reason}"}
            )
        raise NotFound(f"there is no setting {key}")
    return spec


def _view(key: str, row: Setting | None) -> SettingValue:
    spec = SPECS[key]
    own = row.value if row is not None else None
    options = spec.takes.options
    return SettingValue(
        key=key,
        value=spec.default if own is None else own,
        default=spec.default,
        is_default=own is None,
        meaning=spec.meaning,
        row_version=row.row_version if row is not None else 0,
        updated_at=row.updated_at if row is not None else None,
        updated_by=row.updated_by if row is not None else None,
        accepts=spec.takes.accepts,
        options=options() if options is not None else None,
    )


def list_settings(db: Session) -> list[SettingValue]:
    """Return every setting with the value in force, and then every fixed value."""
    rows = {row.key: row for row in db.scalars(select(Setting))}
    return [_view(key, rows.get(key)) for key in SPECS] + [
        fixed.view() for fixed in fixed_values().values()
    ]


# The settings that are set, read once for a transaction: a request asks for a dozen of
# them, one at a time, and each was a statement of its own. What is kept is the rows as
# the session holds them, so a setting changed in the transaction reads as changed; a
# row that is added or removed, and the end of the transaction, leave nothing kept.
_READ = "hirdir.settings"


def _rows(db: Session) -> dict[str, Setting]:
    rows: dict[str, Setting] | None = db.info.get(_READ)
    if rows is None:
        rows = {row.key: row for row in db.scalars(select(Setting))}
        db.info[_READ] = rows
    return rows


@event.listens_for(Session, "after_flush")
def _after_a_flush(session: Session, _: Any) -> None:
    if _READ in session.info and any(
        isinstance(one, Setting) for one in (*session.new, *session.deleted)
    ):
        session.info.pop(_READ, None)


@event.listens_for(Session, "after_commit")
@event.listens_for(Session, "after_rollback")
def _after_a_transaction(session: Session) -> None:
    session.info.pop(_READ, None)


def get_setting(db: Session, key: str) -> SettingValue:
    """Return one setting with the value in force."""
    _spec(key)
    return _view(key, _rows(db).get(key))


def value(db: Session, key: str) -> Any:
    """Return the value in force of the setting key."""
    return get_setting(db, key).value


def values(db: Session, keys: tuple[str, ...]) -> dict[str, Any]:
    """Return the values in force of several settings, read in one query."""
    for key in keys:
        _spec(key)
    rows = _rows(db)
    return {key: _view(key, rows.get(key)).value for key in keys}


def time_zone(db: Session) -> str:
    """Return the application's time zone, in which a time that names no zone is read."""
    return str(value(db, "time_zone"))


def max_items(db: Session) -> int:
    """Return how many items one request may cover, add to a group or receive."""
    return int(value(db, "max_items_per_request"))


def check_items(db: Session, count: int, field: str, what: str = "items") -> None:
    """Refuse a request of more items than `max_items_per_request` lets one take."""
    most = max_items(db)
    if count > most:
        raise Invalid(
            "too many at once",
            {field: f"at most {most:,} {what} to a request (max_items_per_request)"},
        )


def code_length(db: Session) -> int:
    """Return the least length of an access code that is typed (P-295)."""
    return int(value(db, CODE_LENGTH_SETTING))


def ceiling(db: Session) -> load.Ceiling:
    """Return the ceiling in force: what the three settings of it say (P-265)."""
    held = values(db, load.SETTINGS)
    return load.Ceiling(
        response_ms=int(held[load.RESPONSE_SETTING]),
        cpu_percent=int(held[load.PROCESSOR_SETTING]),
        over_seconds=int(held[load.OVER_SETTING]),
    )


def set_setting(
    db: Session, context: AuditContext, key: str, row_version: int, new: Any
) -> SettingValue:
    """Give a setting a value. None returns it to its default. A fixed value is not
    changed.

    A setting that has never been given a value is at version 0.
    """
    spec = _spec(key)
    checked = None if new is None else spec.check(new)
    if checked == spec.default:
        checked = None
    row = db.scalar(select(Setting).where(Setting.key == key))
    if row is None:
        if row_version != 0:
            raise Invalid(
                "the version is not acceptable",
                {"row_version": "0 for a setting that has never been changed"},
            )
        if checked is None:
            return _view(key, None)
        row = Setting(key=key, value=None, row_version=0)
        row.created_by = context.actor_hid
        db.add(row)
        db.flush()
    records.apply(db, context, "setting", row, row_version, {"value": checked})
    return _view(key, row)


# --- what is fixed -------------------------------------------------------------------


@dataclass(frozen=True)
class Fixed:
    """A value of a rule that a site does not change: what it is, what it limits, and why."""

    key: str
    value: Any
    meaning: str
    reason: str
    decision: str | None = None

    def view(self) -> SettingValue:
        value = list(self.value) if isinstance(self.value, tuple) else self.value
        return SettingValue(
            key=self.key,
            value=value,
            default=value,
            is_default=True,
            meaning=self.meaning,
            row_version=0,
            updated_at=None,
            updated_by=None,
            fixed=True,
            reason=self.reason,
            decision=self.decision,
        )


DECIDED = "decided, and the same for every site"
PROTECTS = "a limit that protects the service"


@cache
def fixed_values() -> dict[str, Fixed]:
    """Return what is fixed, by key, each read from the module that uses it.

    They are gathered when first asked for, because the modules that hold them read
    the settings themselves.
    """
    from hirdir.auth import throttle
    from hirdir.db import dialect, engine
    from hirdir.domain import (
        contracts,
        geography,
        groups,
        health,
        idempotency,
        items,
        purchases,
        references,
    )
    from hirdir.io import entities, exports, files, filters, imports, listing

    found = (
        Fixed(
            "out_of_service_states",
            contracts.OUT_OF_SERVICE,
            "the states in which an item is out of service, as a retired item is, for "
            "the coverage report and the contracts that still count it",
            DECIDED,
            "D-142",
        ),
        Fixed(
            "out_of_hands_states",
            items.OUT_OF_HANDS,
            "the states in which an item has left the team's hands: it leaves its groups, "
            "and is no longer at a place that is still in use",
            DECIDED,
            "D-103",
        ),
        Fixed(
            "received_state",
            purchases.RECEIVED_AS,
            "the lifecycle state an item that is received on a purchase line is created in",
            DECIDED,
            "D-145",
        ),
        Fixed(
            "condition_health",
            {
                health.FAILED: list(health.FAILED_CONDITIONS),
                health.DEGRADED: list(health.POOR_CONDITIONS),
                health.GOOD: [health.GOOD_CONDITION],
            },
            "what each condition says of an item's health; any other condition, untested "
            "and those a site adds among them, says nothing of it",
            DECIDED,
            "D-112",
        ),
        Fixed(
            "review_status_of_what_a_file_makes",
            entities.MADE_BY_A_FILE,
            "the review status of a vendor or a catalog entry that a file names and that is "
            "not known yet",
            DECIDED,
            "P-14",
        ),
        Fixed(
            "refused_file_types",
            file_kinds.REFUSED,
            "the extensions of a web page, a script or a program, which no reference may "
            "have, whatever reference_file_types says",
            DECIDED,
            "P-159",
        ),
        Fixed(
            "busy_fewest_requests",
            load.FEWEST_REQUESTS,
            "the reads, answered and in flight over the last busy_over_seconds, from "
            "which on what is refused follows how long they take: with fewer, nothing "
            "is refused for it, whatever the health says, and the percentile is never "
            "one request alone",
            DECIDED,
            "P-265",
        ),
        Fixed(
            "default_page_size",
            listing.DEFAULT_LIMIT,
            "the rows of a page of a list where limit is not given",
            PROTECTS,
        ),
        Fixed("max_page_size", listing.MAX_LIMIT, "the rows of one page of a list", PROTECTS),
        Fixed("max_offset", listing.MAX_OFFSET, "the offset of a page of a list", PROTECTS),
        Fixed(
            "max_filter_length",
            filters.MAX_FILTER_LENGTH,
            "the characters of a filter in the address of a request; a longer one is sent "
            "as the body of a query",
            PROTECTS,
        ),
        Fixed(
            "max_filter_depth", filters.MAX_DEPTH, "how deep the parts of a filter nest", PROTECTS
        ),
        Fixed(
            "max_filter_conditions", filters.MAX_CONDITIONS, "the conditions of a filter", PROTECTS
        ),
        Fixed("max_filter_values", filters.MAX_LIST, "the values of one condition", PROTECTS),
        Fixed("max_filter_value_length", filters.MAX_TEXT, "the characters of one value", PROTECTS),
        Fixed(
            "max_pattern_length",
            dialect.REGEX_MAX_LENGTH,
            "the characters of a regular expression in a filter",
            PROTECTS,
        ),
        Fixed(
            "max_pattern_repeat",
            dialect.REGEX_MAX_REPEAT,
            "the counted repeats of a regular expression, multiplied together",
            PROTECTS,
        ),
        Fixed(
            "pattern_match_seconds",
            dialect.REGEX_MATCH_SECONDS,
            "how long one match of a regular expression may take",
            PROTECTS,
        ),
        Fixed(
            "pattern_request_seconds",
            dialect.REGEX_REQUEST_SECONDS,
            "how long all the matches of one request may take together",
            PROTECTS,
        ),
        Fixed("max_file_rows", files.MAX_ROWS, "the rows of a file, or of a bulk edit", PROTECTS),
        Fixed(
            "max_export_hids",
            exports.MAX_HIDS,
            "the records an export, or a bulk edit, names by their HIDs",
            PROTECTS,
        ),
        Fixed(
            "import_batch_rows",
            imports.BATCH_ROWS,
            "the rows of an import applied at once",
            PROTECTS,
        ),
        Fixed(
            "max_minor_item_depth",
            items.MAX_DEPTH,
            "how many levels of minor items there may be beneath a major item",
            PROTECTS,
        ),
        Fixed("max_group_nesting", groups.MAX_NESTING, "how deep device groups nest", PROTECTS),
        Fixed(
            "max_location_depth",
            geography.MAX_LOCATION_DEPTH,
            "how deep locations nest within a site",
            PROTECTS,
        ),
        Fixed("max_region_depth", geography.MAX_REGION_DEPTH, "how deep regions nest", PROTECTS),
        Fixed(
            "max_request_lines", purchases.MAX_LINES, "the lines of a purchase request", PROTECTS
        ),
        Fixed(
            "max_line_quantity", purchases.MAX_QUANTITY, "the quantity of a purchase line", PROTECTS
        ),
        Fixed(
            "sign_in_max_delay_seconds",
            int(throttle.MAX_DELAY_SECONDS),
            "the longest that a sign-in is delayed after wrong access codes",
            PROTECTS,
        ),
        Fixed(
            "sign_in_window_seconds",
            int(throttle.FORGET_AFTER_SECONDS),
            "how long wrong access codes are remembered",
            PROTECTS,
        ),
        Fixed(
            "max_attachments_per_request",
            references.MAX_ATTACHMENTS,
            "the records one request puts a reference on",
            PROTECTS,
        ),
        Fixed(
            "idempotency_key_hours",
            int(idempotency.KEPT_FOR.total_seconds() // 3600),
            "how long the answer to a request with an Idempotency-Key is kept",
            PROTECTS,
        ),
        Fixed(
            "max_idempotency_key_length",
            idempotency.MAX_KEY,
            "the characters of an Idempotency-Key",
            PROTECTS,
        ),
        Fixed(
            "max_kept_answer_bytes",
            idempotency.MAX_BODY,
            "the largest answer that is kept for an Idempotency-Key",
            PROTECTS,
        ),
        Fixed(
            "writer_wait_seconds",
            engine.WRITER_WAIT_SECONDS,
            "how long a change waits for another to be stored before it is answered 503",
            PROTECTS,
        ),
        Fixed(
            "busy_retry_seconds",
            load.RETRY_SECONDS,
            "how long a request that a busy server did not take is told to wait",
            PROTECTS,
        ),
        Fixed(
            "load_window_seconds",
            load.WINDOW_SECONDS,
            "how long the server keeps its own measures, in memory",
            PROTECTS,
        ),
        Fixed(
            "load_step_seconds",
            load.STEP_SECONDS,
            "the length of a step of the server's own measures",
            PROTECTS,
        ),
    )
    return {fixed.key: fixed for fixed in found}
