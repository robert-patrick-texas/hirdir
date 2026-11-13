"""What routes depend on: a database session, the caller, and the audit context."""

from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from hirdir.auth.roles import Role
from hirdir.domain import accounts
from hirdir.domain.accounts import Principal
from hirdir.domain.audit import AuditContext
from hirdir.domain.errors import NotAllowed

CLIENTS = {"web", "cli"}


def get_db(request: Request) -> Iterator[Session]:
    """Yield the request's session. It commits if the route succeeds, else rolls back.

    The commit is made when the route function returns, before any of the answer is
    sent, so a change that could not be stored is never answered as if it had been.
    """
    with request.app.state.sessions() as db:
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise


Db = Annotated[Session, Depends(get_db, scope="function")]


def via(request: Request) -> str:
    """Say through which door a request came: the web UI, the CLI, or the bare API."""
    client = request.headers.get("x-hirdir-client", "")
    return client if client in CLIENTS else "api"


def request_id(request: Request) -> str:
    """Return the ID of this request."""
    return getattr(request.state, "request_id", "")


def get_principal(request: Request, db: Db) -> Principal:
    """Return who the request comes from, or refuse it as not signed in."""
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise accounts.NotSignedIn("sign in to continue")
    return accounts.authenticate(db, request.app.state.signing_key, token.strip())


SignedIn = Annotated[Principal, Depends(get_principal)]


def require(role: Role) -> Callable[[Principal], Principal]:
    """Return a dependency that lets through only callers who hold at least role."""

    def check(principal: SignedIn) -> Principal:
        if principal.role is None or not principal.role.allows(role):
            raise NotAllowed(f"this needs the {role.value} role")
        return principal

    return check


Viewer = Annotated[Principal, Depends(require(Role.VIEWER))]
Inventory = Annotated[Principal, Depends(require(Role.INVENTORY))]
Admin = Annotated[Principal, Depends(require(Role.ADMIN))]


def get_audit_context(request: Request, principal: SignedIn) -> AuditContext:
    """Return the audit context of a signed-in request."""
    return AuditContext(
        actor_hid=principal.user.hid, via=via(request), request_id=request_id(request)
    )


Audit = Annotated[AuditContext, Depends(get_audit_context)]
