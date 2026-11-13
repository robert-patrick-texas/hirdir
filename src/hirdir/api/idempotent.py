"""Routes that take `Idempotency-Key`, and routes that refuse it.

The rule is in `domain/idempotency.py`. This is the plumbing: a route class that asks
the rule before a request is worked on and tells it the answer afterwards.
"""

from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from hirdir.auth.roles import Role
from hirdir.domain import accounts, idempotency
from hirdir.io import files

REPLAYED = "Idempotency-Replayed"
KeyHeader = Annotated[
    str | None,
    Header(
        alias=idempotency.HEADER,
        max_length=idempotency.MAX_KEY,
        description=(
            "A value of the caller's choosing. The same request sent again with the same "
            "key within 24 hours is answered with the first answer and not carried out again."
        ),
    ),
]


def refused(request: Request) -> None:
    """Refuse the header on a route whose answer may hold a secret that is kept nowhere."""
    if idempotency.HEADER in request.headers:
        raise idempotency.refuse(
            "the routes of accounts do not take it: their answers are not kept"
        )


async def limited_body(request: Request) -> bytes:
    """Read the body of a request, and stop reading one that is over the limit.

    The limit is that of a file, which is the largest thing anybody sends. What was
    read is kept on the request, so the route reads the same body again.
    """
    limit = request.app.state.config.max_file_bytes
    if not hasattr(request, "_body"):
        pieces: list[bytes] = []
        size = 0
        async for piece in request.stream():
            size += len(piece)
            if size > limit:
                raise files.TooLarge(f"a request is at most {limit // (1024 * 1024)} MB")
            pieces.append(piece)
        request._body = b"".join(pieces)
    return await request.body()


def _caller(request: Request) -> str | None:
    """Return the HID of a signed-in caller who may change the inventory, or None.

    Every route that takes a key changes something, and so needs the Inventory role.
    A caller who does not hold it now is left to the route to refuse: an answer kept
    for them earlier, when they did hold it, is not given again.
    """
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    with request.app.state.sessions() as db:
        try:
            principal = accounts.authenticate(db, request.app.state.signing_key, token.strip())
        except accounts.NotSignedIn:
            return None
        db.commit()
        if principal.role is None or not principal.role.allows(Role.INVENTORY):
            return None
        return principal.user.hid


def _begin(request: Request, user_hid: str, key: str, body: bytes) -> idempotency.Kept | None:
    target = request.url.path + ("?" + request.url.query if request.url.query else "")
    with request.app.state.sessions() as db:
        kept = idempotency.begin(
            db, user_hid, key, idempotency.fingerprint(request.method, target, body)
        )
        db.commit()
        return kept


def _end(request: Request, user_hid: str, key: str, failed: bool) -> None:
    response = getattr(request.state, "answer", None)
    body = getattr(response, "body", None)
    kept = not failed and response is not None and 200 <= response.status_code < 300
    with request.app.state.sessions() as db:
        if kept and isinstance(body, bytes):
            idempotency.finish(db, user_hid, key, response.status_code, body)
        else:
            idempotency.abandon(db, user_hid, key)
        db.commit()


class Replayed(Exception):
    """The request was carried out before. `kept` is the answer it was given then."""

    def __init__(self, kept: idempotency.Kept) -> None:
        super().__init__("answered before")
        self.kept = kept


def replay(kept: idempotency.Kept) -> Response:
    """Return the answer that was kept, marked as given a second time."""
    return Response(
        kept.body,
        status_code=kept.status,
        media_type="application/json",
        headers={REPLAYED: "true"},
    )


async def _keyed(request: Request, key: KeyHeader = None) -> AsyncIterator[None]:
    """Reserve the key before the route works, and keep the answer once it has.

    This is entered before the request's database session and so left after it: the
    answer is kept only once the change itself is stored. Were the server to stop
    between the two, the key would stay reserved with no answer, and the request sent
    again would be refused, never carried out twice.
    """
    user_hid = None if key is None else await run_in_threadpool(_caller, request)
    if key is None or user_hid is None:
        # No key, or nobody signed in: the route says so, and nothing is kept.
        yield
        return
    body = await limited_body(request)
    kept = await run_in_threadpool(_begin, request, user_hid, key, body)
    if kept is not None:
        raise Replayed(kept)
    failed = True
    try:
        yield
        failed = False
    finally:
        await run_in_threadpool(_end, request, user_hid, key, failed)


class IdempotentRoute(APIRoute):
    """A route whose POST requests take `Idempotency-Key`."""

    def __init__(self, path: str, endpoint: Callable[..., Any], **options: Any) -> None:
        # A query is a list asked for with a POST. It changes nothing, and takes no key.
        if "POST" in (options.get("methods") or []) and not path.endswith("/query"):
            options["dependencies"] = [
                Depends(_keyed, scope="function"),
                *(options.get("dependencies") or []),
            ]
        super().__init__(path, endpoint, **options)

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handle = super().get_route_handler()

        async def noting_the_answer(request: Request) -> Response:
            response = await handle(request)
            request.state.answer = response
            return response

        return noting_the_answer
