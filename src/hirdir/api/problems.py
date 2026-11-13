"""Errors as RFC 9457 problem documents."""

from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException

from hirdir.api import idempotent
from hirdir.db import dialect
from hirdir.domain import errors
from hirdir.domain.accounts import NotSignedIn
from hirdir.io import files

MEDIA_TYPE = "application/problem+json"
BUSY_RETRY_SECONDS = 5


def problem(
    status: int,
    title: str,
    detail: str = "",
    fields: dict[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Build a problem response."""
    body = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
        "errors": [{"field": name, "message": text} for name, text in (fields or {}).items()],
    }
    return JSONResponse(body, status_code=status, media_type=MEDIA_TYPE, headers=headers)


def install(app: FastAPI) -> None:
    """Teach app to answer every error as a problem document."""

    @app.exception_handler(NotSignedIn)
    async def _not_signed_in(_: Request, error: NotSignedIn) -> JSONResponse:
        return problem(401, "Not signed in", str(error), headers={"WWW-Authenticate": "Bearer"})

    @app.exception_handler(errors.SignInRefused)
    async def _refused(_: Request, error: errors.SignInRefused) -> JSONResponse:
        return problem(401, "Sign-in refused", str(error))

    @app.exception_handler(errors.SignInDelayed)
    async def _delayed(_: Request, error: errors.SignInDelayed) -> JSONResponse:
        seconds = str(max(1, round(error.retry_after)))
        return problem(429, "Too many attempts", str(error), headers={"Retry-After": seconds})

    @app.exception_handler(errors.NotAllowed)
    async def _not_allowed(_: Request, error: errors.NotAllowed) -> JSONResponse:
        return problem(403, "Not allowed", str(error))

    @app.exception_handler(errors.NotFound)
    async def _not_found(_: Request, error: errors.NotFound) -> JSONResponse:
        return problem(404, "Not found", str(error))

    @app.exception_handler(errors.Conflict)
    async def _conflict(_: Request, error: errors.Conflict) -> JSONResponse:
        title = "Stale version" if isinstance(error, errors.StaleVersion) else "Conflict"
        return problem(409, title, str(error), error.fields)

    @app.exception_handler(StaleDataError)
    async def _stale(_: Request, error: StaleDataError) -> JSONResponse:
        # Two changes were made against one version at the same moment, and the
        # database let the other one through first.
        return problem(409, "Stale version", "this record was changed by someone else a moment ago")

    @app.exception_handler(OperationalError)
    async def _busy(_: Request, error: OperationalError) -> JSONResponse:
        # One change is stored at a time. This one waited behind another, such as a
        # large import being applied, for as long as it may, and was not made.
        if not dialect.is_busy(error):
            raise error
        return problem(
            503,
            "Busy",
            "another change is being stored and this one was not made; try again in a moment",
            headers={"Retry-After": str(BUSY_RETRY_SECONDS)},
        )

    @app.exception_handler(IntegrityError)
    async def _collision(_: Request, error: IntegrityError) -> JSONResponse:
        # A uniqueness rule is checked before a write, and by the database as well.
        # This is the database's refusal, when two requests passed the check together.
        return problem(
            409, "Conflict", "the change collides with a record that was saved a moment ago"
        )

    @app.exception_handler(idempotent.Replayed)
    async def _replayed(_: Request, error: idempotent.Replayed) -> Response:
        return idempotent.replay(error.kept)

    @app.exception_handler(files.TooLarge)
    async def _too_large(_: Request, error: files.TooLarge) -> JSONResponse:
        return problem(413, "Too large", str(error), error.fields)

    @app.exception_handler(errors.Invalid)
    async def _invalid(_: Request, error: errors.Invalid) -> JSONResponse:
        return problem(422, "Invalid input", str(error), error.fields)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, error: RequestValidationError) -> JSONResponse:
        fields = {
            ".".join(str(part) for part in item["loc"] if part != "body"): item["msg"]
            for item in error.errors()
        }
        return problem(422, "Invalid input", "the request is not well formed", fields)

    @app.exception_handler(HTTPException)
    async def _http(_: Request, error: HTTPException) -> JSONResponse:
        return problem(error.status_code, str(error.detail), headers=error.headers)
