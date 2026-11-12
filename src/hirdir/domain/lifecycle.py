"""Lifecycle: the nine states, what each allows, and the moves between them.

The states are fixed. What a state allows, and where an item may go from it, is data in
`lifecycle_rules`, which an Admin may edit. Three fields describe an item's standing:
`lifecycle_state` is the stage, `disposition` is what an item in hand is for, and
`expected_online` is the intent that it is powered and reachable.
"""

from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.auth.roles import Role
from hirdir.db.models import LifecycleRule
from hirdir.domain import records
from hirdir.domain.audit import AuditContext
from hirdir.domain.errors import Invalid, NotAllowed, NotFound

STATES = (
    "Purchased",
    "Delivered",
    "Assigned",
    "Test",
    "Prod",
    "Down",
    "Pending-Removal",
    "Released",
    "Archived",
)
DISPOSITIONS = ("Staging", "Production", "Spare", "Excess")
ARCHIVED = "Archived"

# What a caller passes for a field it says nothing about, where None means "blank".
UNSET: Final[Any] = object()


def _spelled(value: Any, allowed: tuple[str, ...], field: str) -> str:
    name = records.key(value) if isinstance(value, str) else ""
    for candidate in allowed:
        if records.key(candidate) == name:
            return candidate
    raise Invalid(f"{value} is not acceptable", {field: f"one of {', '.join(allowed)}"})


def state_name(value: Any, field: str = "lifecycle_state") -> str:
    """Return a lifecycle state as it is stored, whatever case it was written in."""
    return _spelled(value, STATES, field)


def disposition_name(value: Any, field: str = "disposition") -> str:
    """Return a disposition as it is stored, whatever case it was written in."""
    return _spelled(value, DISPOSITIONS, field)


def list_rules(db: Session) -> list[LifecycleRule]:
    """Return the rule of every state, in the order of the lifecycle."""
    return list(db.scalars(select(LifecycleRule).order_by(LifecycleRule.sort)))


def rule_of(db: Session, state: str) -> LifecycleRule:
    """Return the rule of one state."""
    rule = db.scalar(select(LifecycleRule).where(LifecycleRule.state == state))
    if rule is None:
        raise NotFound(f"there is no lifecycle rule for {state}")
    return rule


def _allowed(rule: LifecycleRule, kept: str | None) -> list[str]:
    allowed = list(rule.dispositions)
    if rule.keeps_disposition and kept and kept not in allowed:
        allowed.append(kept)
    return allowed


def standing_errors(
    rule: LifecycleRule, disposition: str | None, expected_online: bool, kept: str | None
) -> dict[str, str]:
    """Say what is wrong with a disposition and an intent for an item in the rule's state.

    `kept` is the disposition the item already has. A state that keeps the disposition
    allows that one as well as its own.
    """
    allowed = _allowed(rule, kept)
    state = rule.state
    if disposition is None:
        if allowed and not (rule.keeps_disposition and kept is None):
            return {"disposition": f"an item in {state} is one of {', '.join(allowed)}"}
    elif not allowed:
        return {"disposition": f"an item in {state} carries no disposition"}
    elif disposition not in allowed:
        return {
            "disposition": f"an item in {state} is one of {', '.join(allowed)}, not {disposition}"
        }
    what = f"a {disposition} item" if disposition else "an item"
    if expected_online and disposition not in rule.may_be_online:
        return {"expected_online": f"{what} in {state} is not expected online"}
    if not expected_online and disposition in rule.must_be_online:
        return {"expected_online": f"{what} in {state} is expected online"}
    return {}


def entry_standing(
    rule: LifecycleRule,
    current: str | None,
    disposition: Any = UNSET,
    expected_online: Any = UNSET,
) -> tuple[str | None, bool]:
    """Return the disposition and intent of an item as it enters the rule's state.

    What the caller names is taken as given. Otherwise the disposition the item has is
    kept when the state allows it, and the state's own is set when it does not; the
    intent is the state's own, bounded by what the disposition may and must be.
    """
    if disposition is UNSET:
        keep = rule.keeps_disposition or current in rule.dispositions
        disposition = current if keep else rule.entry_disposition
    if expected_online is UNSET or expected_online is None:
        if disposition in rule.must_be_online:
            expected_online = True
        elif disposition not in rule.may_be_online:
            expected_online = False
        else:
            expected_online = bool(rule.entry_online)
    return disposition, expected_online


def check_move(
    db: Session,
    current: str | None,
    to: str,
    *,
    force: bool,
    role: Role | None,
    reason: str | None,
) -> bool:
    """Refuse a move the rules do not allow. Say whether it went through by force.

    An item with no state yet may be given any. Any other move outside the rules is
    open to an Admin who asks for it by force and gives a reason.
    """
    if current == to:
        raise Invalid("the item is already there", {"to": f"the item is already in {to}"})
    if current is None or to in rule_of(db, current).next_states:
        return False
    onward = rule_of(db, current).next_states
    if not force:
        where = f"may move to {', '.join(onward)}" if onward else "may not move on"
        raise Invalid(
            f"an item in {current} {where}",
            {"to": f"an item in {current} {where}; an Admin may force another move"},
        )
    if role is None or not role.allows(Role.ADMIN):
        raise NotAllowed("forcing a lifecycle move needs the admin role")
    if not reason:
        raise Invalid("a forced move needs a reason", {"reason": "say why the move is forced"})
    return True


def _names(value: Any, allowed: tuple[str, ...], field: str) -> list[str]:
    if not isinstance(value, list):
        raise Invalid(f"{field} is not acceptable", {field: "a list"})
    chosen = {_spelled(entry, allowed, field) for entry in value}
    return [name for name in allowed if name in chosen]


def update_rule(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> LifecycleRule:
    """Change what a state allows and where an item may move from it."""
    rule = db.get(LifecycleRule, hid)
    if rule is None:
        raise NotFound(f"there is no lifecycle rule {hid}")
    values: dict[str, Any] = {}
    for name in ("dispositions", "may_be_online", "must_be_online"):
        if name in fields:
            values[name] = _names(fields[name], DISPOSITIONS, name)
    if "next_states" in fields:
        values["next_states"] = _names(fields["next_states"], STATES, "next_states")
        if rule.state in values["next_states"]:
            raise Invalid(
                "the moves are not acceptable",
                {"next_states": "a state does not move to itself"},
            )
    if "keeps_disposition" in fields:
        values["keeps_disposition"] = bool(fields["keeps_disposition"])
    if "entry_disposition" in fields:
        given = fields["entry_disposition"]
        values["entry_disposition"] = (
            None if given is None else disposition_name(given, "entry_disposition")
        )
    if "entry_online" in fields:
        values["entry_online"] = fields["entry_online"]

    def final(name: str) -> Any:
        return values.get(name, getattr(rule, name))

    errors = {}
    entry = final("entry_disposition")
    if entry is not None and entry not in final("dispositions"):
        errors["entry_disposition"] = "must be one of the dispositions the state allows"
    if not set(final("must_be_online")) <= set(final("may_be_online")):
        errors["must_be_online"] = "must be among those that may be online"
    if errors:
        raise Invalid("the rule does not agree with itself", errors)
    records.apply(db, context, "lifecycle_rule", rule, row_version, values)
    return rule
