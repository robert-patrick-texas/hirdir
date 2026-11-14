"""The routes that came first: health, signing in, accounts and the audit trail."""

import platform
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select, text

import hirdir
from hirdir.api import schemas, views
from hirdir.api.deps import Admin, Audit, Db, SignedIn, Viewer, request_id, via
from hirdir.api.idempotent import refused
from hirdir.api.problems import problem
from hirdir.db import migrate
from hirdir.db.models import AuditEvent, ServiceToken
from hirdir.domain import accounts
from hirdir.io import tables

Limit = Annotated[int, Query(ge=1, le=1000)]
Offset = Annotated[int, Query(ge=0, le=10_000_000)]

health = APIRouter(prefix="/health", tags=["Health"])
# The answer of an account route may hold an access code or a token. Neither is kept
# anywhere, so no answer of these routes can be kept to be given a second time.
NO_KEY = [Depends(refused)]
auth = APIRouter(prefix="/auth", tags=["Access"], dependencies=NO_KEY)
users = APIRouter(tags=["Accounts"], dependencies=NO_KEY)
groups = APIRouter(prefix="/user-groups", tags=["Accounts"], dependencies=NO_KEY)
grants = APIRouter(prefix="/role-grants", tags=["Accounts"], dependencies=NO_KEY)
audit = APIRouter(tags=["Audit"])
meta = APIRouter(tags=["About"])


# --- health ------------------------------------------------------------------------


@health.get("/live")
def live() -> schemas.Health:
    """Say that the process is running. Needs no sign-in."""
    return schemas.Health(status="ok")


@health.get("/ready", responses={503: {"model": schemas.Health}})
def ready(request: Request, db: Db, response: Response) -> schemas.Health:
    """Say whether the database is reachable and at the schema this code expects."""
    engine = request.app.state.engine
    try:
        db.execute(text("SELECT 1"))
        at, wanted = migrate.current(engine), migrate.head(request.app.state.config.database_url)
        if at != wanted:
            response.status_code = 503
            return schemas.Health(status="not ready", detail="the schema needs a migration")
        if (
            engine.dialect.name == "sqlite"
            and db.execute(text("PRAGMA foreign_keys")).scalar() != 1
        ):
            response.status_code = 503
            return schemas.Health(status="not ready", detail="foreign keys are not enforced")
    except Exception:
        response.status_code = 503
        return schemas.Health(status="not ready", detail="the database cannot be reached")
    return schemas.Health(status="ok")


# --- access ------------------------------------------------------------------------


@auth.post("/sign-in", responses={401: {"model": schemas.Problem}, 429: {"model": schemas.Problem}})
def sign_in(body: schemas.SignIn, request: Request, db: Db) -> schemas.SessionOut:
    """Exchange a username and access code for a session token."""
    state = request.app.state
    user, token, expires_at = accounts.sign_in(
        db,
        username=body.username,
        access_code=body.access_code,
        address=request.client.host if request.client else "",
        via=via(request),
        request_id=request_id(request),
        throttle=state.throttle,
        signing_key=state.signing_key,
        session_hours=state.config.session_hours,
    )
    return schemas.SessionOut(token=token, expires_at=expires_at, user=views.user_out(db, user))


@auth.get("/me")
def me(principal: SignedIn, db: Db) -> schemas.UserOut:
    """Return the signed-in user, with the role they hold right now."""
    return views.user_out(db, principal.user)


@auth.post("/sign-out-everywhere", status_code=204)
def sign_out_everywhere(principal: SignedIn, context: Audit, db: Db) -> None:
    """End every session of the signed-in user, this one included."""
    accounts.sign_out_everywhere(db, context, principal.user.hid)


# --- users -------------------------------------------------------------------------


@users.get("/users")
def list_users(
    _: Admin,
    db: Db,
    q: str = "",
    sort: Annotated[list[str] | None, Query(description=tables.USERS.help)] = None,
    limit: Limit = 100,
    offset: Offset = 0,
) -> schemas.Page[schemas.UserOut]:
    """List users, by username unless a sort says otherwise. `q` matches part of a
    username or display name."""
    page, total = accounts.list_users(db, q, limit, offset, tables.arrange(tables.USERS, sort))
    return schemas.Page(
        items=[views.user_out(db, user) for user in page], total=total, limit=limit, offset=offset
    )


@users.post("/users", status_code=201)
def create_user(body: schemas.UserCreate, _: Admin, context: Audit, db: Db) -> schemas.UserCreated:
    """Create a user. The access code in the answer is not shown again."""
    user, code = accounts.create_user(
        db,
        context,
        username=body.username,
        display_name=body.display_name,
        email=body.email,
        is_service_account=body.is_service_account,
        access_code=body.access_code,
    )
    if body.role:
        accounts.grant_role(db, context, role=body.role, user_hid=user.hid)
    return schemas.UserCreated(user=views.user_out(db, user), access_code=code)


@users.get("/users/{hid}")
def get_user(hid: str, _: Admin, db: Db) -> schemas.UserOut:
    """Return one user."""
    return views.user_out(db, accounts.get_user(db, hid))


@users.patch("/users/{hid}")
def update_user(
    hid: str, body: schemas.UserPatch, _: Admin, context: Audit, db: Db
) -> schemas.UserOut:
    """Change a user. Disabling a user ends every session they have."""
    fields = body.model_dump(exclude={"row_version"}, exclude_unset=True)
    return views.user_out(db, accounts.update_user(db, context, hid, body.row_version, fields))


@users.post("/users/{hid}/access-code")
def set_access_code(
    hid: str, body: schemas.AccessCodeSet, _: Admin, context: Audit, db: Db
) -> schemas.AccessCodeOut:
    """Give a user a new access code. Every session they have ends."""
    return schemas.AccessCodeOut(
        access_code=accounts.set_access_code(db, context, hid, body.access_code)
    )


@users.post("/users/{hid}/sign-out-everywhere", status_code=204)
def sign_out_user(hid: str, _: Admin, context: Audit, db: Db) -> None:
    """End every session of a user."""
    accounts.sign_out_everywhere(db, context, hid)


@users.get("/users/{hid}/service-tokens")
def list_service_tokens(hid: str, _: Admin, db: Db) -> list[schemas.ServiceTokenOut]:
    """List the tokens of a service account."""
    return [
        schemas.ServiceTokenOut.model_validate(t) for t in accounts.list_service_tokens(db, hid)
    ]


@users.post("/users/{hid}/service-tokens", status_code=201)
def create_service_token(
    hid: str, body: schemas.ServiceTokenCreate, _: Admin, context: Audit, db: Db
) -> schemas.ServiceTokenCreated:
    """Create a token for a service account. The secret in the answer is not shown again."""
    token, secret = accounts.create_service_token(
        db, context, hid, name=body.name, expires_at=body.expires_at
    )
    return schemas.ServiceTokenCreated(
        token=schemas.ServiceTokenOut.model_validate(token), secret=secret
    )


@users.post("/service-tokens/{hid}/revoke")
def revoke_service_token(hid: str, _: Admin, context: Audit, db: Db) -> schemas.ServiceTokenOut:
    """Revoke one service token."""
    token: ServiceToken = accounts.revoke_service_token(db, context, hid)
    return schemas.ServiceTokenOut.model_validate(token)


# --- user groups -------------------------------------------------------------------


@groups.get("")
def list_groups(_: Admin, db: Db) -> list[schemas.GroupOut]:
    """List user groups by name."""
    return [views.group_out(db, group) for group in accounts.list_groups(db)]


@groups.post("", status_code=201)
def create_group(body: schemas.GroupCreate, _: Admin, context: Audit, db: Db) -> schemas.GroupOut:
    """Create a user group."""
    group = accounts.create_group(db, context, name=body.name, description=body.description)
    return views.group_out(db, group)


@groups.get("/{hid}")
def get_group(hid: str, _: Admin, db: Db) -> schemas.GroupDetail:
    """Return one user group with its members."""
    return views.group_detail(db, accounts.get_group(db, hid))


@groups.patch("/{hid}")
def update_group(
    hid: str, body: schemas.GroupPatch, _: Admin, context: Audit, db: Db
) -> schemas.GroupOut:
    """Change a user group."""
    fields = body.model_dump(exclude={"row_version"}, exclude_unset=True)
    return views.group_out(db, accounts.update_group(db, context, hid, body.row_version, fields))


@groups.delete("/{hid}", status_code=204)
def delete_group(hid: str, _: Admin, context: Audit, db: Db) -> None:
    """Remove a user group, its memberships and the roles granted to it."""
    accounts.delete_group(db, context, hid)


@groups.put("/{hid}/members/{user_hid}", status_code=204)
def add_member(hid: str, user_hid: str, _: Admin, context: Audit, db: Db) -> None:
    """Put a user in a group."""
    accounts.add_member(db, context, hid, user_hid)


@groups.delete("/{hid}/members/{user_hid}", status_code=204)
def remove_member(hid: str, user_hid: str, _: Admin, context: Audit, db: Db) -> None:
    """Take a user out of a group."""
    accounts.remove_member(db, context, hid, user_hid)


# --- role grants -------------------------------------------------------------------


@grants.get("")
def list_grants(_: Admin, db: Db) -> list[schemas.GrantOut]:
    """List every role grant."""
    return [views.grant_out(db, grant) for grant in accounts.list_grants(db)]


@grants.post("", status_code=201)
def grant_role(body: schemas.GrantCreate, _: Admin, context: Audit, db: Db) -> schemas.GrantOut:
    """Grant a role to one user or one group."""
    grant = accounts.grant_role(
        db, context, role=body.role, user_hid=body.user_hid, group_hid=body.group_hid
    )
    return views.grant_out(db, grant)


@grants.delete("/{hid}", status_code=204)
def revoke_grant(hid: str, _: Admin, context: Audit, db: Db) -> None:
    """Take back a role grant."""
    accounts.revoke_grant(db, context, hid)


# --- audit -------------------------------------------------------------------------


@audit.get("/audit-events")
def list_audit_events(
    _: Viewer,
    db: Db,
    record_type: str = "",
    record_hid: str = "",
    action: str = "",
    actor_hid: str = "",
    request: str = Query(default="", alias="request_id"),
    sort: Annotated[list[str] | None, Query(description=tables.AUDIT_EVENTS.help)] = None,
    limit: Limit = 100,
    offset: Offset = 0,
) -> schemas.Page[schemas.AuditEventOut]:
    """List audit events, newest first unless a sort says otherwise."""
    arrange = tables.arrange(tables.AUDIT_EVENTS, sort)
    query = select(AuditEvent)
    for column, value in (
        (AuditEvent.record_type, record_type),
        (AuditEvent.record_hid, record_hid),
        (AuditEvent.action, action),
        (AuditEvent.actor_hid, actor_hid),
        (AuditEvent.request_id, request),
    ):
        if value:
            query = query.where(column == value)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    if arrange is not None:
        query = arrange(query)
    page = db.scalars(
        query.order_by(AuditEvent.at.desc(), AuditEvent.hid.desc()).limit(limit).offset(offset)
    )
    return schemas.Page(
        items=[views.audit_out(db, event) for event in page],
        total=total,
        limit=limit,
        offset=offset,
    )


# --- about -------------------------------------------------------------------------


@meta.get("/about")
def about(_: SignedIn, request: Request) -> schemas.About:
    """Say what is running."""
    return schemas.About(
        name="hirdir",
        version=hirdir.__version__,
        python=platform.python_version(),
        sqlite=sqlite3.sqlite_version,
        schema_revision=migrate.current(request.app.state.engine),
    )


@meta.get("/openapi.json", include_in_schema=False)
def openapi(_: SignedIn, request: Request) -> dict:
    """Return the OpenAPI document of this API, with the URL prefix it is served under."""
    document = dict(request.app.openapi())
    root = request.scope.get("root_path", "")
    if root:
        document["servers"] = [{"url": root}]
    return document


ROUTERS = (health, auth, users, groups, grants, audit, meta)

__all__ = ["ROUTERS", "problem"]
