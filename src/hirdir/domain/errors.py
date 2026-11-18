"""What can go wrong in a rule, in terms the interfaces turn into answers."""

from dataclasses import dataclass
from datetime import datetime


class DomainError(Exception):
    """The base of every error a rule raises."""


class NotFound(DomainError):
    """There is no such record."""


class Deleted(NotFound):
    """The record was there, and an Admin deleted it (P-236): when, by whom and why, as
    the audit trail has it."""

    def __init__(
        self,
        message: str,
        at: datetime,
        actor_hid: str | None,
        actor_name: str | None,
        reason: str | None,
    ) -> None:
        super().__init__(message)
        self.at = at
        self.actor_hid = actor_hid
        self.actor_name = actor_name
        self.reason = reason


@dataclass(frozen=True)
class Existing:
    """The record that already has a value another may not have too (P-207).

    `record_type` is its kind as the audit trail names it, `item` or `catalog_entry`,
    and `label` what a person knows it by.
    """

    record_type: str
    hid: str
    label: str


class Conflict(DomainError):
    """The change collides with the present state: a duplicate, or a rule it would break.

    `fields` names the field that collides, where there is one, and `existing` the
    record that has the value already, where the collision is with one. `depends_on`
    are the records that stand on the one the change is about, where those are why.
    """

    def __init__(
        self,
        message: str,
        fields: dict[str, str] | None = None,
        existing: Existing | None = None,
        depends_on: list[Existing] | None = None,
    ) -> None:
        super().__init__(message)
        self.fields = fields or {}
        self.existing = existing
        self.depends_on = depends_on or []


class StaleVersion(Conflict):
    """The record has changed since the copy this change was made against."""


class Invalid(DomainError):
    """The input is not acceptable. `fields` names what is wrong with which field."""

    def __init__(self, message: str, fields: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.fields = fields or {}


class NotAllowed(DomainError):
    """The caller's role does not permit this."""


class SignInRefused(DomainError):
    """The username and access code were not accepted."""


class SignInDelayed(DomainError):
    """Too many failures in a row. `retry_after` is the wait in seconds."""

    def __init__(self, retry_after: float) -> None:
        super().__init__("too many failed attempts; try again later")
        self.retry_after = retry_after
