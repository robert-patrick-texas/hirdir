"""The application: the API, the web UI it serves, and what wraps every request."""

import re
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from starlette.datastructures import Headers, MutableHeaders
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

import hirdir
from hirdir.api import problems
from hirdir.api.routes import ROUTERS
from hirdir.auth import tokens
from hirdir.auth.throttle import Throttle
from hirdir.config import Config
from hirdir.db.engine import make_engine, make_sessions
from hirdir.ids import new_hid

API_PREFIX = "/api/v1"
STATIC = Path(__file__).parent / "static"
BASE_TAG = '<base href="/" />'
PREFIX = re.compile(r"(/[A-Za-z0-9._~-]+)+")
REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{8,64}")
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)


class Gateway:
    """Wraps every request: the proxy's forwarded facts in, hirdir's headers out.

    From a trusted proxy it takes the URL prefix the proxy stripped and the address of
    the real client. On every response it sets the request ID and the security headers,
    and removes any cookie, because hirdir never sets one.
    """

    def __init__(self, app: ASGIApp, trusted_proxies: tuple[str, ...]) -> None:
        self.app = app
        self.trusted = frozenset(trusted_proxies)

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
        is_api = scope["path"].startswith(scope.get("root_path", "") + "/api/")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                out = MutableHeaders(scope=message)
                out["X-Request-Id"] = request_id
                out["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
                out["X-Content-Type-Options"] = "nosniff"
                out["Referrer-Policy"] = "no-referrer"
                if is_api:
                    out["Cache-Control"] = "no-store"
                del out["Set-Cookie"]
            await send(message)

        await self.app(scope, receive, send_with_headers)

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
        if path and candidate.is_file() and candidate.is_relative_to(STATIC.resolve()):
            return FileResponse(candidate)
        root = request.scope.get("root_path", "")
        html = index.read_text(encoding="utf-8").replace(BASE_TAG, f'<base href="{root}/" />')
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})


def create_app(config: Config) -> FastAPI:
    """Build the application for one configuration."""
    app = FastAPI(
        title="hirdir",
        version=hirdir.__version__,
        summary="Network equipment lifecycle and inventory platform",
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )
    engine = make_engine(config.database_url)
    app.state.config = config
    app.state.engine = engine
    app.state.sessions = make_sessions(engine)
    app.state.signing_key = tokens.load_or_create_key(config.secret_key_path)
    app.state.throttle = Throttle(config.sign_in_failures_before_delay)

    api = APIRouter(prefix=API_PREFIX)
    for router in ROUTERS:
        api.include_router(router)
    app.include_router(api)
    problems.install(app)
    _install_web_ui(app)
    app.add_middleware(Gateway, trusted_proxies=config.trusted_proxies)
    return app
