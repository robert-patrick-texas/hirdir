"""What can go wrong in a rule, in terms the interfaces turn into answers."""


class DomainError(Exception):
    """The base of every error a rule raises."""


class NotFound(DomainError):
    """There is no such record."""


class Conflict(DomainError):
    """The change collides with the present state: a duplicate, or a rule it would break."""


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
