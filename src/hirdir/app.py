"""The application: the API, the web UI it serves, and what wraps every request."""

import logging
import re
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES, GZipMiddleware
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

import hirdir
from hirdir.api import (
    addresses,
    busy,
    carrier_contacts,
    catalog,
    circuits,
    contract_contacts,
    contracts,
    files,
    geography,
    groups,
    items,
    labels,
    problems,
    purchases,
    references,
    reports,
    routes,
    systems,
)
from hirdir.auth import tokens
from hirdir.auth.throttle import Throttle
from hirdir.config import Config
from hirdir.db.engine import make_engine, make_sessions
from hirdir.domain import file_kinds, load, product
from hirdir.ids import new_hid
from hirdir.io import background, fields, measures, tables
from hirdir.io.store import Store
from hirdir.schedule import JOBS, SERVER_JOBS, Scheduler

API_PREFIX = "/api/v1"
ROUTERS = (
    *routes.ROUTERS,
    *catalog.ROUTERS,
    *items.ROUTERS,
    *groups.ROUTERS,
    *addresses.ROUTERS,
    *geography.ROUTERS,
    *contracts.ROUTERS,
    # The contacts of agreements and contracts (D-183).
    *contract_contacts.ROUTERS,
    # The contacts of carriers and of circuits (P-149).
    *carrier_contacts.ROUTERS,
    *purchases.ROUTERS,
    *systems.ROUTERS,
    *reports.ROUTERS,
    *labels.ROUTERS,
    *files.ROUTERS,
    # Circuits, their carriers, cost lines and devices, and circuit groups (P-145 to P-154).
    *circuits.ROUTERS,
    # References: files kept by hirdir and links to files kept elsewhere (P-158 to P-162).
    *references.ROUTERS,
)
STATIC = Path(__file__).parent / "static"
BASE_TAG = '<base href="/" />'
# What the built page says of the product, which the server names as the site calls it.
TITLE_TAG = "<title>hirdir</title>"
NO_SCRIPT = "<noscript>hirdir needs JavaScript to run.</noscript>"
# What the page holds before its script runs (P-230).
BOOT_NAME = '<p class="boot-name">hirdir</p>'
PREFIX = re.compile(r"(/[A-Za-z0-9._~-]+)+")
REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{8,64}")
log = logging.getLogger("hirdir")
KEEP_FOR_GOOD = "public, max-age=31536000, immutable"
SMALLEST_COMPRESSED = 1024
# A picture of a reference is shown from a blob: address the page made of what it
# fetched itself, which runs nothing (P-159).
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' blob:; base-uri 'self'; form-action 'self'; "
    "frame-ancestors 'none'"
)
# The routes whose body is a reference file, which may be larger than an import.
UPLOADS = re.compile(r"/api/v1/reference-files(/[0-9a-f-]{36}/content)?")
# A download is not compressed again: what is not text is compressed already, or gains
# too little for the time it takes.
NOT_COMPRESSED = (
    *DEFAULT_EXCLUDED_CONTENT_TYPES,
    *sorted(
        {
            known.media_type
            for known in file_kinds.KNOWN.values()
            if not known.media_type.startswith("text/")
        }
    ),
    file_kinds.OCTET_STREAM,
)


class Gateway:
    """Wraps every request: the proxy's forwarded facts in, hirdir's headers out.

    From a trusted proxy it takes the URL prefix the proxy stripped and the address of
    the real client. On every response it sets the request ID and the security headers,
    and removes any cookie, because hirdir never sets one. An error that nothing else
    answered is logged with its request ID and answered here as a problem document, so
    that it carries the same headers as every other response.

    It is the outermost layer, so it is where the server measures itself (P-265): every
    request is timed from its arrival to the last byte of its answer and counted by its
    status, in the meter of the application. And it is where a server past its ceiling
    answers that it is busy, at once, on the event loop: before the request waits for a
    thread or for the database.
    """

    def __init__(
        self,
        app: ASGIApp,
        trusted_proxies: tuple[str, ...],
        limits: Callable[[], tuple[int, int]] | None = None,
        kinds: busy.Kinds | None = None,
    ) -> None:
        self.app = app
        self.trusted = frozenset(trusted_proxies)
        # The largest body of a request, and of an upload of a reference file.
        self.limits = limits
        # What each route of the API is to a server that is busy.
        self.kinds = kinds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        client = scope.get("client")
        if client and client[0] in self.trusted:
            self._apply_forwarded(scope, headers)
        given = headers.get("x-request-id", "")
        request_id = given if REQUEST_ID.fullmatch(given) else new_hid()
        scope.setdefault("state", {})["request_id"] = request_id
        root = scope.get("root_path", "")
        is_api = scope["path"].startswith(root + "/api/")
        is_asset = scope["path"].startswith(root + "/assets/")
        # The meter of the application as it is bound now: its state is that of one
        # installation, and a test binds one application to many.
        meter: load.Meter = scope["app"].state.load
        refused: Response | None = None
        if is_api:
            refused = self._busy(scope, meter, root)
        if refused is not None:
            flight = None
        else:
            flight = meter.began(*measures.clock(), api=is_api)
            scope["state"]["in_flight"] = flight
            refused = self._too_large(scope, headers, root)

        started = False
        status = 500

        async def send_with_headers(message: Message) -> None:
            nonlocal started, status, flight
            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
                out = MutableHeaders(scope=message)
                out["X-Request-Id"] = request_id
                # A download says of itself what it may do, which is nothing (P-159).
                if "content-security-policy" not in out:
                    out["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
                out["X-Content-Type-Options"] = "nosniff"
                out["Referrer-Policy"] = "no-referrer"
                if is_api:
                    out["Cache-Control"] = "no-store"
                elif is_asset and message["status"] == 200:
                    # The name of a built file changes whenever its content does, so a
                    # browser may keep it for good and never ask again.
                    out["Cache-Control"] = KEEP_FOR_GOOD
                del out["Set-Cookie"]
            await send(message)
            if (
                flight is not None
                and message["type"] == "http.response.body"
                and not message.get("more_body")
            ):
                # The last byte of the answer is sent: what the request took is known.
                meter.ended(flight, *measures.clock(), status=status)
                flight = None

        try:
            if refused is not None:
                # The rest of the body is read and thrown away before the answer, so
                # that a proxy that is still sending it is answered rather than cut off.
                while True:
                    message = await receive()
                    if message["type"] != "http.request" or not message.get("more_body"):
                        break
                await refused(scope, receive, send_with_headers)
                return
            try:
                await self.app(scope, receive, send_with_headers)
            except Exception:
                log.exception(
                    "request %s failed: %s %s", request_id, scope["method"], scope["path"]
                )
                if started:
                    raise
                failure = problems.problem(
                    500, "Server error", f"something went wrong; the request ID is {request_id}"
                )
                await failure(scope, receive, send_with_headers)
        finally:
            if flight is not None:
                # An answer that was cut short, or never begun, is over all the same.
                meter.ended(flight, *measures.clock(), status=status if started else 500)

    def _busy(self, scope: Scope, meter: load.Meter, root: str) -> Response | None:
        """Return the answer of a server that is past its ceiling to a request it does
        not take, or None (P-265). The meter says whether the server is busy, from what
        it holds in memory; only then is the request's route looked for, to learn
        whether it is one that waits. An answer of busy is counted, and is in neither
        measure."""
        now, cpu = measures.clock()
        reading = meter.reading(now, cpu)
        if reading.state == load.OK or self.kinds is None:
            return None
        path = scope["path"][len(root) :] if scope["path"].startswith(root) else scope["path"]
        if not load.refuses(reading.state, self.kinds.of(scope["method"], path)):
            return None
        meter.turned_away(now, cpu)
        return problems.server_busy(reading)

    def _too_large(self, scope: Scope, headers: Headers, root: str) -> Response | None:
        """Return the answer to a body that says it is over the limit of its route, or
        None. An upload of a reference file takes up to its own limit, and every other
        request up to that of an import, whatever the proxy lets through (P-162). A body
        that does not say its length is not seen here: an upload and an import hold it to
        their limits as they read it, and nginx, which reads a body whole before it
        passes it on, always says the length."""
        length = headers.get("content-length", "")
        if self.limits is None or not length.isdigit():
            return None
        largest, reference = self.limits()
        path = scope["path"][len(root) :] if scope["path"].startswith(root) else scope["path"]
        upload = scope["method"] in ("POST", "PUT") and UPLOADS.fullmatch(path)
        limit, what = (reference, "a reference file") if upload else (largest, "a request")
        if int(length) <= limit:
            return None
        return problems.problem(
            413,
            "Too large",
            f"{what} is at most {limit // (1024 * 1024)} MB",
            {"file": "too large"},
        )

    @staticmethod
    def _apply_forwarded(scope: Scope, headers: Headers) -> None:
        prefix = headers.get("x-forwarded-prefix", "").rstrip("/")
        if prefix and PREFIX.fullmatch(prefix):
            # The proxy stripped the prefix. Put it back, so that the path and the
            # root path agree whether or not a proxy strips.
            if not scope["path"].startswith(prefix + "/"):
                scope["path"] = prefix + scope["path"]
                scope["raw_path"] = prefix.encode() + scope.get("raw_path", b"")
            scope["root_path"] = prefix
        forwarded_for = headers.get("x-forwarded-for", "").split(",")[-1].strip()
        if forwarded_for:
            scope["client"] = (forwarded_for, 0)


def _install_web_ui(app: FastAPI) -> None:
    """Serve the built web UI, with the URL prefix written into its base tag."""
    if (STATIC / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def page(path: str, request: Request) -> Response:
        if path == "api" or path.startswith("api/"):
            return problems.problem(404, "Not found", "there is no such route")
        index = STATIC / "index.html"
        if not index.is_file():
            return PlainTextResponse("hirdir is running. The web UI has not been built.\n")
        candidate = (STATIC / path).resolve()
        # The page itself is always served as the page, named, by any path.
        is_page = candidate == index.resolve()
        if (
            path
            and not is_page
            and candidate.is_file()
            and candidate.is_relative_to(STATIC.resolve())
        ):
            return FileResponse(candidate)
        root = request.scope.get("root_path", "")
        html = index.read_text(encoding="utf-8").replace(BASE_TAG, f'<base href="{root}/" />')
        try:
            with request.app.state.sessions() as db:
                facts = product.page_facts(db)
        except SQLAlchemyError:
            # It is the sign-in page: served all the same, as hirdir, and signing in says
            # what is wrong.
            log.exception("the settings of the page could not be read")
            facts = product.UNREAD
        return HTMLResponse(_named(html, facts), headers={"Cache-Control": "no-store"})


def _named(html: str, facts: dict[str, Any]) -> str:
    """Write the product name into the page, and what else it carries before signing in
    (P-168, P-169): the tab's title, the note for a browser without scripts, the words
    the page holds before its script runs (P-230), and the facts the web UI reads when it
    starts, as an attribute escaped as one is."""
    name = escape(facts["product_name"], quote=True)
    html = html.replace(TITLE_TAG, f"<title>{name}</title>")
    html = html.replace(NO_SCRIPT, f"<noscript>{name} needs JavaScript to run.</noscript>")
    html = html.replace(BOOT_NAME, f'<p class="boot-name">{name}</p>')
    meta = f'<meta name="hirdir-site" content="{product.page_attribute(facts)}" />'
    return html.replace("</head>", f"    {meta}\n  </head>", 1)


def bind(app: FastAPI, config: Config) -> None:
    """Give the application everything it holds of one installation.

    That is its settings, its database, the key that signs sessions, the count of
    failed sign-ins and the meter of its own load: all of it is here, and none in the
    routes. The tests rely on that.
    They build the routes once and bind them to the state of each test in turn, which
    `create_app` does once, for the server.
    """
    engine = make_engine(config.database_url)
    app.state.config = config
    app.state.engine = engine
    app.state.sessions = make_sessions(engine)
    app.state.signing_key = tokens.load_or_create_key(config.secret_key_path)
    app.state.throttle = Throttle(config.sign_in_failures_before_delay)
    # The content of reference files, beside the database (P-161).
    app.state.store = Store(config.files_dir)
    # The server's own measures of its last ten minutes, which start empty, and the
    # ceiling as the settings of this database have it (P-265).
    measures.start(app.state)


# --- what runs beside the requests --------------------------------------------------


def _lifespan(scheduled: bool, work: bool) -> Callable[[FastAPI], Any]:
    """Return what works beside the requests for as long as the server is up.

    With `work`, that is the background work, which the second process of the service
    does otherwise (P-267): the worker that applies imports and bulk edits (D-185),
    started once the application is bound to its database and stopped, after the batch
    it is in, when the server stops, and for the server every job of the clock.

    For the server, with or without it, that is what is the server's own. The sweep of
    the store of reference files, before the first request is answered: the store is
    kept under a lock of this process, and no other may sweep it while an upload is
    taken (P-161). And the jobs of the clock that fill this process's memory
    (`hirdir.schedule.SERVER_JOBS`). A test drives `hirdir.schedule` itself.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        applying = background.running(app.state) if work else None
        if applying is not None:
            await run_in_threadpool(applying.__enter__)
        if scheduled:
            # What an upload cut short left behind, and content no record names (P-161).
            await run_in_threadpool(_sweep_store, app)
        jobs = JOBS if work else SERVER_JOBS
        scheduler = Scheduler(lambda: app.state.sessions(), jobs) if scheduled else None
        try:
            if scheduler is not None:
                await run_in_threadpool(scheduler.start)
            yield
        finally:
            if scheduler is not None:
                await run_in_threadpool(scheduler.stop)
            if applying is not None:
                await run_in_threadpool(applying.__exit__, None, None, None)

    return lifespan


def _sweep_store(app: FastAPI) -> None:
    with app.state.sessions() as db:
        app.state.store.sweep(db)


# --- the application ------------------------------------------------------------------


def create_app(config: Config, scheduled: bool = False, work: bool = True) -> FastAPI:
    """Build the application for one configuration. `scheduled` is for the server, which
    does what is due at set times; a test drives `hirdir.schedule` itself. `work` is
    whether this process does the background work as well, as the tests of the routes
    have it and `hirdir admin serve --work`; the server of the service does none, and
    leaves it to the second process (P-267)."""
    app = FastAPI(
        title="hirdir",
        version=hirdir.__version__,
        summary="Network equipment lifecycle and inventory platform",
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        lifespan=_lifespan(scheduled, work),
    )
    bind(app, config)
    # Every list is made ready by this one thread, before requests arrive side by side.
    fields.warm()
    tables.warm()

    api = APIRouter(prefix=API_PREFIX)
    for router in ROUTERS:
        api.include_router(router)
    app.include_router(api)
    problems.install(app)
    _install_web_ui(app)
    # A page of a list and the web UI's own files are text that shrinks to a tenth.
    # hirdir sets no cookie, so no other site can make a signed-in request and learn
    # anything from the size of a compressed answer.
    app.add_middleware(
        GZipMiddleware, minimum_size=SMALLEST_COMPRESSED, exclude_content_types=NOT_COMPRESSED
    )
    app.add_middleware(
        Gateway,
        trusted_proxies=config.trusted_proxies,
        limits=lambda: (app.state.config.max_file_bytes, app.state.config.max_reference_bytes),
        kinds=busy.Kinds(ROUTERS, API_PREFIX),
    )
    return app
