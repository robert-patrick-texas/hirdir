"""The lists of countries and states that an address takes its country and its state
from (P-318, P-321).

A country is its ISO 3166-1 code, two capital letters, and its name; a state is a
subdivision of a country as ISO 3166-2 has it, the part of its code after the hyphen,
its name and its country. Both lists are an Admin's to change, each change audited, and
every role reads them. The United States, `US`, is first in the list however it is
named, is renamed but neither removed nor given another code, and is the country of an
address that names none and has any other field.

An address stores codes: a country and a state are found from what is given, a code or
a name without regard to case, and the common spellings of the United States, and kept
as their codes. A value that no list holds is refused at its field; one held from before
is kept as it was until the country or the state of that address is changed, when both
are checked.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from hirdir.auth.roles import Role
from hirdir.db.models import ADDRESS_FIELDS, Country, Location, Region, Site, State
from hirdir.domain import audit, records
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Conflict, Existing, Invalid, NotAllowed, NotFound

US = "US"
# The common spellings of the United States that are no name or code of the list.
US_TOO = frozenset({"usa", "u.s.", "u.s.a.", "united states of america"})
COUNTRY_CODE = re.compile(r"[A-Z]{2}")
STATE_CODE = re.compile(r"[A-Z0-9]{1,3}")
NAME_LENGTH = 100
COUNTRY_FIELDS = ("code", "name")
STATE_FIELDS = ("country", "code", "name")
# Where a person finds the lists, as a refusal names it.
COUNTRIES_ARE = "the list of countries, GET /countries, which an Admin keeps under Choices"
STATES_ARE = (
    "the list of its states, GET /states?country={code}, which an Admin keeps under Choices"
)
# The places whose addresses hold a country and a state, and the sets each has: its
# street address, and the shipping set, whose fields begin `ship_`. A region has the
# shipping set alone.
STREET, SHIPPING = "", "ship_"
PREFIXES: dict[str, tuple[str, ...]] = {
    "region": (SHIPPING,),
    "site": (STREET, SHIPPING),
    "location": (STREET, SHIPPING),
}
# The names an address answers beside its fields, read from the lists (P-321).
NAMES = ("country_name", "state_name", "ship_country_name", "ship_state_name")
SETS: tuple[tuple[str, Any, tuple[str, ...]], ...] = (
    ("region", Region, PREFIXES["region"]),
    ("site", Site, PREFIXES["site"]),
    ("location", Location, PREFIXES["location"]),
)


def _admins(role: Role | None) -> None:
    """Refuse a change of either list to anybody but an Admin (P-321)."""
    if role is not Role.ADMIN:
        raise NotAllowed(
            "an Admin changes the lists of countries and states: this needs the admin role"
        )


def _first() -> Any:
    """The order of the countries as they are shown: the United States first."""
    return case((Country.code == US, 0), else_=1)


# --- reading -------------------------------------------------------------------------


def list_countries(db: Session) -> list[Country]:
    """Return the countries in the order they are shown: the United States first, then
    the rest by name."""
    return list(db.scalars(select(Country).order_by(_first(), Country.name_key, Country.code)))


def list_states(db: Session, country: str = "") -> list[State]:
    """Return the states of one country by name, found by its code or its name, or of
    every country, each country's together in the order the countries are shown."""
    if country.strip():
        code = the_country(db, country, "country").code
        return list(db.scalars(select(State).where(State.country == code).order_by(State.name_key)))
    shown = (
        select(State)
        .outerjoin(Country, Country.code == State.country)
        .order_by(
            case((State.country == US, 0), else_=1), Country.name_key, State.country, State.name_key
        )
    )
    return list(db.scalars(shown))


def get_country(db: Session, hid: str) -> Country:
    """Return the country with hid."""
    found = db.get(Country, hid)
    if found is None:
        raise NotFound(f"there is no country {hid}")
    return found


def get_state(db: Session, hid: str) -> State:
    """Return the state with hid."""
    found = db.get(State, hid)
    if found is None:
        raise NotFound(f"there is no state {hid}")
    return found


def find_country(db: Session, text: str | None) -> Country | None:
    """Return the country a value names: by its code or its name, without regard to case
    or to spaces around it, or by `USA`, `U.S.`, `U.S.A.` or `United States of America`
    for the United States. None where no country of the list is so named."""
    key = records.key(text or "")
    if not key:
        return None
    found = db.scalar(select(Country).where(Country.code == key.upper()))
    if found is None and key in US_TOO:
        found = db.scalar(select(Country).where(Country.code == US))
    if found is None:
        found = db.scalar(select(Country).where(Country.name_key == key))
    return found


def find_state(db: Session, country: str, text: str | None) -> State | None:
    """Return the state of a country, by its code, that a value names by its code or its
    name, without regard to case or to spaces around it. None where it has none so named."""
    key = records.key(text or "")
    if not key:
        return None
    found = db.scalar(select(State).where(State.country == country, State.code == key.upper()))
    if found is None:
        found = db.scalar(select(State).where(State.country == country, State.name_key == key))
    return found


def has_states(db: Session, country: str) -> bool:
    """Say whether the list holds any state of a country, by its code."""
    return db.scalar(select(State.hid).where(State.country == country).limit(1)) is not None


def the_country(db: Session, text: str, field: str) -> Country:
    """Return the country a value names, or refuse it at its field, naming the list."""
    found = find_country(db, text)
    if found is None:
        raise Invalid(f"{text.strip()} is not in the list of countries", {field: COUNTRIES_ARE})
    return found


# --- what addresses hold -------------------------------------------------------------


def _holders(db: Session, holds: Any) -> tuple[int, str]:
    """Return how many address sets, street or shipping, of every place meet a
    condition, and the first place among them in words: `holds` gives the condition of
    one set of one model, by the set's prefix."""
    total, first = 0, ""
    for level, model, prefixes in SETS:
        for prefix in prefixes:
            where = holds(model, prefix)
            total += db.scalar(select(func.count()).select_from(model).where(where)) or 0
            if not first:
                name = db.scalar(select(model.name).where(where).order_by(model.name_key))
                first = f"the {level} {name}" if name is not None else ""
    return total, first


def country_held(db: Session, code: str) -> tuple[int, str]:
    """Return how many address sets of every place hold a country, by its code, and the
    first of the places in words."""
    return _holders(db, lambda model, prefix: getattr(model, f"{prefix}country") == code)


def state_held(db: Session, state: State) -> tuple[int, str]:
    """Return how many address sets hold a state, its code with its country in force,
    which for a blank country is the United States, and the first of the places."""

    def holds(model: Any, prefix: str) -> Any:
        country = getattr(model, f"{prefix}country")
        in_force = country == state.country
        if state.country == US:
            in_force = or_(in_force, country.is_(None))
        return and_(getattr(model, f"{prefix}state") == state.code, in_force)

    return _holders(db, holds)


def _held_refusal(held: tuple[int, str], said: str, field: str) -> Conflict:
    """Return the refusal of a change that would leave an address with a value that no
    list holds, naming the first place that holds it and how many more do."""
    count, first = held
    others = count - 1
    more = f" and {others:,} more address{'es' if others > 1 else ''}" if others else ""
    return Conflict(said, {field: f"held by {first}{more}; give each another first"})


# --- the countries -------------------------------------------------------------------


def _name(fields: Mapping[str, Any], values: dict[str, Any], what: str) -> None:
    if "name" not in fields:
        return
    name = records.clean(fields["name"])
    if not isinstance(name, str) or len(name) > NAME_LENGTH:
        raise Invalid(
            f"the name of the {what} is not acceptable",
            {"name": f"1 to {NAME_LENGTH} characters"},
        )
    values["name"] = name
    values["name_key"] = records.key(name)


def _country_code(fields: Mapping[str, Any], values: dict[str, Any]) -> None:
    if "code" not in fields:
        return
    given = records.clean(fields["code"])
    code = given.upper() if isinstance(given, str) else ""
    if not COUNTRY_CODE.fullmatch(code):
        raise Invalid(
            "the code of the country is not acceptable",
            {"code": "two letters, its ISO 3166-1 alpha-2 code, kept in capitals"},
        )
    values["code"] = code


def _checked_country(
    db: Session, fields: Mapping[str, Any], country: Country | None
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    _country_code(fields, values)
    _name(fields, values, "country")
    code = values.get("code")
    if country is not None and code is not None and code != country.code:
        if country.code == US:
            raise Invalid(
                "the United States keeps its code",
                {"code": "US is not given another code; its name may be changed"},
            )
        held = country_held(db, country.code)
        if held[0]:
            raise _held_refusal(
                held, f"the code {country.code} is not changed: an address holds it", "code"
            )
    if code is not None and (country is None or code != country.code):
        twin = db.scalar(select(Country).where(Country.code == code))
        if twin is not None:
            raise Conflict(
                f"the code {code} is taken by {twin.name}",
                {"code": "another country has it"},
                Existing("country", twin.hid, twin.name),
            )
    key = values.get("name_key")
    if key is not None:
        mine = code or (country.code if country is not None else "")
        if key in US_TOO and mine != US:
            raise Invalid(
                "the name is one of the United States'",
                {"name": "USA, U.S., U.S.A. and United States of America name the United States"},
            )
        twin = db.scalar(select(Country).where(Country.name_key == key))
        if twin is not None and (country is None or twin.hid != country.hid):
            raise Conflict(
                f"there is already a country {twin.name}",
                {"name": "another country has it"},
                Existing("country", twin.hid, twin.name),
            )
    return values


def create_country(
    db: Session, context: AuditContext, fields: Mapping[str, Any], role: Role | None
) -> Country:
    """Add a country to the list. An Admin's."""
    _admins(role)
    values = _checked_country(db, {"code": None, "name": None, **fields}, None)
    country = Country(**values)
    records.created(db, context, "country", country, COUNTRY_FIELDS)
    return country


def update_country(
    db: Session,
    context: AuditContext,
    hid: str,
    row_version: int,
    fields: Mapping[str, Any],
    role: Role | None,
) -> Country:
    """Rename a country, or give it another code where no address holds the one it has,
    its states then being of the new code. An Admin's; a change that changes nothing is
    nobody's to refuse."""
    country = get_country(db, hid)
    values = _checked_country(db, fields, country)
    if records.differences(country, values):
        _admins(role)
    before = country.code
    records.apply(db, context, "country", country, row_version, values)
    if country.code != before:
        # A state is of its country by the code: the states go with it.
        for state in db.scalars(select(State).where(State.country == before)):
            records.apply(db, context, "state", state, None, {"country": country.code})
    return country


def delete_country(db: Session, context: AuditContext, hid: str, role: Role | None) -> None:
    """Remove a country that no address holds, with its states, none of which any address
    holds either, in one change; each removal is audited, and the country's event names
    the states removed with it. The United States is not removed."""
    _admins(role)
    country = get_country(db, hid)
    if country.code == US:
        raise Conflict(
            "the United States is not removed",
            {"code": "the United States stays first in the list; it may be renamed"},
        )
    held = country_held(db, country.code)
    if held[0]:
        raise _held_refusal(held, f"{country.name} is not removed: an address holds it", "code")
    states = list(
        db.scalars(select(State).where(State.country == country.code).order_by(State.name_key))
    )
    for state in states:
        held = state_held(db, state)
        if held[0]:
            raise _held_refusal(
                held,
                f"{country.name} is not removed: an address holds its state {state.name}",
                "code",
            )
    for state in states:
        _delete_state(db, context, state)
    audit.record(
        db,
        context,
        "delete",
        "country",
        country.hid,
        [
            change("code", country.code, None),
            change("name", country.name, None),
            *(
                [change("states", [f"{one.code} {one.name}" for one in states], None)]
                if states
                else []
            ),
        ],
    )
    db.delete(country)


# --- the states ----------------------------------------------------------------------


def _state_code(fields: Mapping[str, Any], values: dict[str, Any]) -> None:
    if "code" not in fields:
        return
    given = records.clean(fields["code"])
    code = given.upper() if isinstance(given, str) else ""
    if not STATE_CODE.fullmatch(code):
        raise Invalid(
            "the code of the state is not acceptable",
            {
                "code": "1 to 3 letters and digits, the part of its ISO 3166-2 code after "
                "the hyphen, kept in capitals"
            },
        )
    values["code"] = code


def _checked_state(db: Session, fields: Mapping[str, Any], state: State | None) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if "country" in fields:
        given = records.clean(fields["country"])
        found = the_country(db, given, "country") if isinstance(given, str) else None
        if found is None:
            raise Invalid("a state is of a country", {"country": COUNTRIES_ARE})
        if state is not None and found.code != state.country:
            raise Invalid(
                "a state's country is not changed",
                {"country": "a state stays of its country; add it to the other country"},
            )
        values["country"] = found.code
    _state_code(fields, values)
    _name(fields, values, "state")
    country = values.get("country", state.country if state is not None else "")
    code = values.get("code")
    if state is not None and code is not None and code != state.code:
        held = state_held(db, state)
        if held[0]:
            raise _held_refusal(
                held, f"the code {state.code} is not changed: an address holds it", "code"
            )
    if code is not None and (state is None or code != state.code):
        twin = db.scalar(select(State).where(State.country == country, State.code == code))
        if twin is not None:
            raise Conflict(
                f"the code {code} is taken by {twin.name}",
                {"code": "another state of the country has it"},
                Existing("state", twin.hid, twin.name),
            )
    key = values.get("name_key")
    if key is not None:
        twin = db.scalar(select(State).where(State.country == country, State.name_key == key))
        if twin is not None and (state is None or twin.hid != state.hid):
            raise Conflict(
                f"the country has a state {twin.name} already",
                {"name": "another state of the country has it"},
                Existing("state", twin.hid, twin.name),
            )
    return values


def create_state(
    db: Session, context: AuditContext, fields: Mapping[str, Any], role: Role | None
) -> State:
    """Add a state to a country of the list. An Admin's."""
    _admins(role)
    values = _checked_state(db, {"country": None, "code": None, "name": None, **fields}, None)
    state = State(**values)
    records.created(db, context, "state", state, STATE_FIELDS)
    return state


def update_state(
    db: Session,
    context: AuditContext,
    hid: str,
    row_version: int,
    fields: Mapping[str, Any],
    role: Role | None,
) -> State:
    """Rename a state, or give it another code where no address holds the one it has.
    Its country is not changed. An Admin's; a change that changes nothing is nobody's to
    refuse."""
    state = get_state(db, hid)
    values = _checked_state(db, fields, state)
    if records.differences(state, values):
        _admins(role)
    records.apply(db, context, "state", state, row_version, values)
    return state


def _delete_state(db: Session, context: AuditContext, state: State) -> None:
    audit.record(
        db,
        context,
        "delete",
        "state",
        state.hid,
        [
            change("country", state.country, None),
            change("code", state.code, None),
            change("name", state.name, None),
        ],
    )
    db.delete(state)


def delete_state(db: Session, context: AuditContext, hid: str, role: Role | None) -> None:
    """Remove a state that no address holds. An Admin's, audited."""
    _admins(role)
    state = get_state(db, hid)
    held = state_held(db, state)
    if held[0]:
        raise _held_refusal(held, f"{state.name} is not removed: an address holds it", "code")
    _delete_state(db, context, state)


# --- an address ----------------------------------------------------------------------


def checked_address(
    db: Session, fields: Mapping[str, Any], values: dict[str, Any], record: Any, prefix: str = ""
) -> None:
    """Hold the country and the state of one set of an address to the lists (P-321).

    `values` holds what the change gives, as the place's own rules took it. A country
    given is the code it resolves to, and is no change where that is the code held. Where
    the change changes the country or the state of the set, both are checked: the country is a
    listed one, found by its code or its name, and kept as its code, or blank, which is
    read as the United States and not written so; the state, where the country in force
    has states listed, one of them, kept as its code, or blank, and where it has none, text
    as typed. A value held from before that no list holds is kept until then, so that a
    change of anything else of the place goes through.
    """
    country_field, state_field = f"{prefix}country", f"{prefix}state"

    def held(name: str) -> Any:
        return getattr(record, name) if record is not None else None

    country = values.get(country_field, held(country_field))
    if country_field in fields and country is not None and country != held(country_field):
        # A country given by its name, or by its code in another case, is the code it
        # resolves to: that it is spelled otherwise than the one held changes nothing.
        country = values[country_field] = the_country(db, country, country_field).code
    state_changed = state_field in fields and values.get(state_field) != held(state_field)
    if not state_changed and country == held(country_field):
        return
    state = values.get(state_field, held(state_field))
    code = US
    if country is not None:
        code = the_country(db, country, country_field).code
        values[country_field] = code
    if state is None or not has_states(db, code):
        # Where the country has no states listed, the state is text as typed.
        return
    found = find_state(db, code, state)
    if found is None:
        named = db.scalar(select(Country.name).where(Country.code == code)) or code
        raise Invalid(
            f"{state} is not a state of {named}",
            {state_field: STATES_ARE.format(code=code)},
        )
    values[state_field] = found.code


@dataclass(frozen=True)
class Lists:
    """The two lists as an address reads them: the name of each country by its code, and
    of each state by its country and its code. Read once for a page of places."""

    countries: Mapping[str, str]
    states: Mapping[tuple[str, str], str]
    with_states: frozenset[str]

    @classmethod
    def read(cls, db: Session) -> Lists:
        """Read both lists."""
        countries: dict[str, str] = dict(db.execute(select(Country.code, Country.name)).all())
        states = {
            (country, code): name
            for country, code, name in db.execute(select(State.country, State.code, State.name))
        }
        return cls(countries, states, frozenset(country for country, _ in states))

    def in_force(self, values: Mapping[str, Any], prefix: str = "") -> str | None:
        """Return the country in force of one set of an address: its own, or the United
        States where it names none and any other field of the set is filled."""
        country = values.get(f"{prefix}country")
        if country:
            return country
        others = (values.get(f"{prefix}{name}") for name in ADDRESS_FIELDS if name != "country")
        return US if any(others) else None

    def names(self, values: Mapping[str, Any], prefix: str = "") -> dict[str, str | None]:
        """Return `country_name` and `state_name` of one set of an address, with the
        set's prefix: the names of its codes, the United States' for a blank country of
        a set that has any other field, and null where a value is blank or in no list."""
        country = self.in_force(values, prefix)
        state = values.get(f"{prefix}state")
        return {
            f"{prefix}country_name": self.countries.get(country) if country else None,
            f"{prefix}state_name": self.states.get((country, state)) if country and state else None,
        }

    def of(self, record: Any, level: str) -> dict[str, str | None]:
        """Return the names of the country and the state of each set of a place's
        address: `country_name`, `state_name`, `ship_country_name`, `ship_state_name`,
        those of the sets the place has."""
        found: dict[str, str | None] = {}
        for prefix in PREFIXES[level]:
            held = {
                f"{prefix}{name}": getattr(record, f"{prefix}{name}") for name in ADDRESS_FIELDS
            }
            found.update(self.names(held, prefix))
        return found

    def unlisted(self, values: Mapping[str, Any], prefix: str = "") -> list[tuple[str, str]]:
        """Return each field of one set of an address that holds a value no list holds,
        with the value: a country that is no listed code, and a state that is none of the
        states listed for its country in force. A state of a country that is not listed
        is judged once the country is chosen."""
        found = []
        country = values.get(f"{prefix}country")
        if country and country not in self.countries:
            found.append((f"{prefix}country", country))
        in_force = self.in_force(values, prefix)
        state = values.get(f"{prefix}state")
        if state and in_force in self.with_states and (in_force, state) not in self.states:
            found.append((f"{prefix}state", state))
        return found
