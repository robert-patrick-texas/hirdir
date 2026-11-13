"""The CLI's side of the API: where the server is, the token, and calling it."""

import json
import os
import tomllib
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx2
import typer

EXIT_ACCESS = 3
EXIT_INVALID = 4
EXIT_CONFLICT = 5
EXIT_SERVER = 6


@dataclass
class Target:
    """The server to talk to and the token to send."""

    url: str
    token: str


def settings_path() -> Path:
    """Return the file where `hirdir sign-in` keeps the server URL and the token."""
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "hirdir" / "config.toml"


def load_target(url: str | None = None, token: str | None = None) -> Target:
    """Return the target: options first, then the environment, then the settings file."""
    saved: dict[str, str] = {}
    path = settings_path()
    if path.is_file():
        with path.open("rb") as handle:
            saved = tomllib.load(handle)
    return Target(
        url=(url or os.environ.get("HIRDIR_URL") or saved.get("url", "")).rstrip("/"),
        token=token or os.environ.get("HIRDIR_TOKEN") or saved.get("token", ""),
    )


def save_target(target: Target) -> Path:
    """Write the target to the settings file, readable only by its owner."""
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(f"url = {json.dumps(target.url)}\ntoken = {json.dumps(target.token)}\n")
    return path


def fail(message: str, code: int) -> typer.Exit:
    """Print message to stderr and return the exit to raise."""
    typer.echo(f"hirdir: {message}", err=True)
    return typer.Exit(code)


def _headers(target: Target, more: dict[str, str] | None = None) -> dict[str, str]:
    if not target.url:
        raise fail("no server is set: use --url, HIRDIR_URL, or `hirdir sign-in`", 2)
    headers = {"X-Hirdir-Client": "cli", **(more or {})}
    if target.token:
        headers["Authorization"] = f"Bearer {target.token}"
    return headers


def _refusal(response: httpx2.Response) -> typer.Exit:
    """Print the problem a refused request was answered with, and return the exit for it."""
    try:
        problem = response.json()
        detail = problem.get("detail") or problem.get("title") or response.reason_phrase
        for entry in problem.get("errors", []):
            detail += f"\n  {entry['field']}: {entry['message']}"
    except ValueError:
        detail = response.reason_phrase
    code = {401: EXIT_ACCESS, 403: EXIT_ACCESS, 404: EXIT_INVALID, 409: EXIT_CONFLICT}.get(
        response.status_code, EXIT_INVALID if response.status_code < 500 else EXIT_SERVER
    )
    return fail(detail, code)


def call(
    target: Target,
    method: str,
    path: str,
    body: Any = None,
    *,
    params: dict[str, Any] | None = None,
    content: bytes | None = None,
    content_type: str | None = None,
    timeout: float = 30,
) -> Any:
    """Call the API and return the decoded answer, or exit with the code for the error.

    `body` is sent as JSON. `content` is sent as it is, as a file is, with its type.
    """
    headers = _headers(target, {"Content-Type": content_type} if content_type else None)
    given = {name: value for name, value in (params or {}).items() if value is not None}
    try:
        response = httpx2.request(
            method,
            f"{target.url}/api/v1{path}",
            json=body,
            content=content,
            params=given,
            headers=headers,
            timeout=timeout,
        )
    except httpx2.HTTPError as error:
        raise fail(f"cannot reach {target.url}: {error}", EXIT_SERVER) from error
    if response.is_success:
        return response.json() if response.content else None
    raise _refusal(response)


@contextmanager
def download(target: Target, path: str, body: Any) -> Generator[httpx2.Response]:
    """Call a route that answers with a file, and yield the answer to be read as it arrives."""
    headers = _headers(target)
    try:
        with httpx2.stream(
            "POST", f"{target.url}/api/v1{path}", json=body, headers=headers, timeout=None
        ) as response:
            if not response.is_success:
                response.read()
                raise _refusal(response)
            yield response
    except httpx2.HTTPError as error:
        raise fail(f"cannot reach {target.url}: {error}", EXIT_SERVER) from error
