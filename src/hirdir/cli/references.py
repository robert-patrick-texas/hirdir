"""The client commands of references (P-162): upload files and make links on records,
list what a record has, download, change, put on more records, take off and erase.

Every command calls the API. What a file may be, how large, and what a record lists are
decided by the server, and these commands print what it answers.
"""

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import httpx2
import typer

from hirdir import clock
from hirdir.cli import client, inventory
from hirdir.cli.client import Target

Url = inventory.Url
Token = inventory.Token
Format = Annotated[str, typer.Option("--format", help="table or json")]
Record = Annotated[
    str,
    typer.Option(
        help="A record, as location:PATH, site:PATH, region:PATH, model:'VENDOR PID', "
        "item:NAME, circuit:ID, or its HID alone."
    ),
]
Records = Annotated[
    list[str],
    typer.Option(
        "--to",
        help="A record to put it on, as location:PATH, site:PATH, region:PATH, "
        "model:'VENDOR PID', item:NAME, circuit:ID, or its HID alone. Repeat for more.",
    ),
]
Kind = Annotated[str, typer.Option(help="A value of the reference_kind list, such as floor_plan.")]
# An upload of a large file over a slow line may take a while.
UPLOAD_SECONDS = 3600.0
PIECE = 1024 * 1024
KINDS = {"location": "location", "site": "site", "region": "region"}

group = typer.Typer(
    no_args_is_help=True,
    help="References: files kept by hirdir and links to files kept elsewhere, on places, "
    "models, circuits and items.",
)


# --- naming a record -----------------------------------------------------------------


def _model(target: Target, text: str) -> dict[str, Any]:
    """Return the catalog entry a model is named by: the vendor and the PID, or the PID
    alone where one entry has it."""
    vendor_name, _, pid = text.strip().rpartition(" ")
    conditions: list[dict[str, Any]] = [{"field": "pid", "op": "eq", "value": pid}]
    if vendor_name:
        vendor = inventory._one_named(target, "/vendors", "name", vendor_name, "vendor")
        conditions.append({"field": "vendor_hid", "op": "eq", "value": vendor["hid"]})
    found = client.call(
        target,
        "GET",
        "/catalog-entries",
        params={
            "filter": json.dumps({"and": conditions}),
            "include_archived": True,
            "include_drafts": True,
            "limit": 20,
        },
    )["items"]
    if len(found) == 1:
        return found[0]
    if not found:
        raise client.fail(f"there is no model {text}", client.EXIT_INVALID)
    for one in found:
        typer.echo(f"  {one['hid']}  {one['vendor']['name']} {one['pid']}", err=True)
    raise client.fail(
        f"more than one model answers to {text}: name the vendor too, or the HID",
        client.EXIT_INVALID,
    )


def find_record(target: Target, text: str) -> str:
    """Return the HID of the record that text names, as `kind:what` or an HID alone."""
    kind, colon, what = text.partition(":")
    kind, what = kind.strip().lower(), what.strip()
    if not colon:
        if inventory._is_hid(text.strip()):
            return text.strip()
        raise client.fail(
            f"{text!r} names no record: write location:PATH, site:PATH, region:PATH, "
            "model:'VENDOR PID', item:NAME, circuit:ID, or an HID",
            2,
        )
    if kind in KINDS:
        return inventory.find_place(target, what, KINDS[kind])["hid"]
    if kind == "model":
        return what if inventory._is_hid(what) else _model(target, what)["hid"]
    if kind == "item":
        return inventory.find_item(target, what)["hid"]
    if kind == "circuit":
        return inventory.find_circuit(target, what)["hid"]
    raise client.fail(
        f"{kind} is no kind of record that takes references: location, site, region, "
        "model, item or circuit",
        2,
    )


ROUTES = {
    "location": "/locations",
    "site": "/sites",
    "region": "/regions",
    "model": "/catalog-entries",
    "item": "/items",
    "circuit": "/circuits",
}


def _records_path(target: Target, text: str) -> str:
    """Return the route of what the record that text names lists."""
    hid = find_record(target, text)
    kind = text.partition(":")[0].strip().lower() if ":" in text else ""
    if kind in ROUTES:
        return f"{ROUTES[kind]}/{hid}/references"
    # An HID alone: ask each kind in turn, quietly, which one has it.
    headers = client._headers(target)
    for path in ROUTES.values():
        try:
            response = httpx2.request(
                "GET",
                f"{target.url}/api/v1{path}/{hid}/references",
                params={"limit": 1},
                headers=headers,
                timeout=30,
            )
        except httpx2.HTTPError as error:
            raise client.fail(f"cannot reach {target.url}: {error}", client.EXIT_SERVER) from error
        if response.is_success:
            return f"{path}/{hid}/references"
        if response.status_code != 404:
            raise client._refusal(response)
    raise client.fail(f"there is no record {hid} that takes references", client.EXIT_INVALID)


# --- showing -------------------------------------------------------------------------


def _size(count: int | None) -> str:
    if count is None:
        return ""
    for unit, scale in (("GB", 1024**3), ("MB", 1024**2), ("kB", 1024)):
        if count >= scale:
            return f"{count / scale:.1f} {unit}"
    return f"{count} B"


def _zone(target: Target) -> str:
    for setting in client.call(target, "GET", "/settings"):
        if setting["key"] == "time_zone":
            return setting["value"]
    return clock.DEFAULT_ZONE


def _what(one: dict[str, Any]) -> str:
    return (
        one["url"] if one["form"] == "link" else f"{one['file_name']} ({_size(one['size_bytes'])})"
    )


def _get(target: Target, hid: str) -> dict[str, Any]:
    return client.call(target, "GET", f"/reference-files/{hid}")


@group.command("list")
def list_references(
    of: Annotated[str | None, typer.Option("--of", help="Only what this record has.")] = None,
    kind: Annotated[str | None, typer.Option(help="Only of this kind.")] = None,
    title: Annotated[str | None, typer.Option(help="Only those whose title holds this.")] = None,
    format_: Format = "table",
    url: Url = None,
    token: Token = None,
) -> None:
    """List references: every one, or what a record has, its own first and then those of
    the records it stands under."""
    target = client.load_target(url, token)
    found: list[dict[str, Any]] = []
    path = _records_path(target, of) if of else "/reference-files"
    params: dict[str, Any] = {} if of else {"kind": kind, "title": title}
    while True:
        page = client.call(
            target, "GET", path, params={**params, "limit": 1000, "offset": len(found)}
        )
        found += page["items"]
        if not page["items"] or len(found) >= page["total"]:
            break
    if of and kind:
        found = [one for one in found if one["kind"] == kind]
    if format_ == "json":
        typer.echo(json.dumps(found, indent=2))
        return
    if not found:
        typer.echo("no references")
        return
    head = ["hid", "title", "kind", "file or address"]
    rows = [[*head, "from"]] if of else [[*head, "records"]]
    for one in found:
        last = f"{one['source']}: {one['source_label']}" if of else str(one["attachment_count"])
        rows.append([one["hid"], one["title"], one["kind"], _what(one), last])
    inventory._table(rows)


@group.command("show")
def show_reference(
    reference: Annotated[str, typer.Argument(help="The HID of a reference.")],
    format_: Format = "table",
    url: Url = None,
    token: Token = None,
) -> None:
    """Show one reference, with the records it is on."""
    target = client.load_target(url, token)
    found = _get(target, reference)
    if format_ == "json":
        typer.echo(json.dumps(found, indent=2))
        return
    zone = _zone(target)
    lines: list[tuple[str, Any]] = [
        ("hid", found["hid"]),
        ("title", found["title"]),
        ("kind", found["kind"]),
        ("form", found["form"]),
        ("url", found["url"]),
        ("file_name", found["file_name"]),
        ("media_type", found["media_type"]),
        ("size", _size(found["size_bytes"]) or None),
        ("sha256", found["sha256"]),
        ("content_missing", "true" if found["content_missing"] else None),
        ("notes", found["notes"]),
        ("created_at", clock.shown(datetime.fromisoformat(found["created_at"]), zone)),
        ("updated_at", clock.shown(datetime.fromisoformat(found["updated_at"]), zone)),
        ("row_version", found["row_version"]),
    ]
    lines += [("on", f"{one['record_type']}: {one['label']}") for one in found["attachments"]]
    for name, value in lines:
        if value is not None:
            typer.echo(f"{name + ':':<17}{value}")


# --- adding --------------------------------------------------------------------------


def _pieces(path: Path) -> Iterator[bytes]:
    """Read a file a piece at a time, so that a large one is never held in memory."""
    with path.open("rb") as handle:
        while piece := handle.read(PIECE):
            yield piece


def _upload(target: Target, path: Path, params: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        raise client.fail(f"there is no file {path}", 2)
    return client.call(
        target,
        "POST",
        "/reference-files",
        params={**params, "file_name": path.name},
        content=_pieces(path),
        content_type="application/octet-stream",
        length=path.stat().st_size,
        timeout=UPLOAD_SECONDS,
    )


@group.command("add")
def add_files(
    files: Annotated[list[Path], typer.Argument(help="The files, one or more.")],
    to: Records,
    kind: Kind,
    title: Annotated[
        str | None,
        typer.Option(help="Its title. Left out, each file's name without its extension."),
    ] = None,
    notes: Annotated[str | None, typer.Option(help="Notes.")] = None,
    url: Url = None,
    token: Token = None,
) -> None:
    """Upload files and put each on the records given. Several files are uploaded one
    after another, and one that is refused leaves the others as they went."""
    target = client.load_target(url, token)
    if title is not None and len(files) > 1:
        raise client.fail("--title names one file; leave it out for several", 2)
    records = [find_record(target, text) for text in to]
    refused = code = 0
    for path in files:
        params = {"title": title or path.stem, "kind": kind, "attach_to": records}
        try:
            made = _upload(target, path, params)
            if notes:
                # Notes may be long, and the address of an upload holds little: they
                # are given to the reference once it is there.
                made = client.call(
                    target,
                    "PATCH",
                    f"/reference-files/{made['hid']}",
                    {"notes": notes, "row_version": made["row_version"]},
                )
        except typer.Exit as stopped:
            if len(files) == 1:
                raise
            refused += 1
            typer.echo(f"{path}: refused", err=True)
            code = stopped.exit_code
            continue
        typer.echo(f"{path}: {made['hid']}  {made['title']}, {_size(made['size_bytes'])}")
    if refused:
        raise typer.Exit(code)


@group.command("link")
def add_link(
    address: Annotated[str, typer.Argument(help="The address of the file kept elsewhere.")],
    to: Records,
    kind: Kind,
    title: Annotated[str, typer.Option(help="Its title.")],
    notes: Annotated[str | None, typer.Option(help="Notes.")] = None,
    url: Url = None,
    token: Token = None,
) -> None:
    """Make a link to a file kept elsewhere, and put it on the records given."""
    target = client.load_target(url, token)
    body = {
        "title": title,
        "kind": kind,
        "url": address,
        "notes": notes,
        "attach_to": [find_record(target, text) for text in to],
    }
    made = client.call(target, "POST", "/reference-files/links", body)
    typer.echo(f"{made['hid']}  {made['title']}, on {made['attachment_count']} records")


# --- downloading ---------------------------------------------------------------------


@group.command("get")
def download(
    reference: Annotated[str, typer.Argument(help="The HID of a file.")],
    output: Annotated[
        Path | None, typer.Option("--output", help="Where to write it. Left out, its own name.")
    ] = None,
    force: Annotated[bool, typer.Option(help="Write over a file that is there.")] = False,
    url: Url = None,
    token: Token = None,
) -> None:
    """Download a file, byte for byte."""
    target = client.load_target(url, token)
    found = _get(target, reference)
    if found["form"] == "link":
        raise client.fail(
            f"a link has no content: its address is {found['url']}", client.EXIT_INVALID
        )
    path = output or Path(found["file_name"])
    if path.exists() and not force:
        raise client.fail(f"{path} is there already: --force writes over it", 2)
    headers = client._headers(target)
    try:
        with httpx2.stream(
            "GET",
            f"{target.url}/api/v1/reference-files/{found['hid']}/content",
            headers=headers,
            timeout=None,
        ) as response:
            if not response.is_success:
                response.read()
                raise client._refusal(response)
            with path.open("wb") as handle:
                for piece in response.iter_bytes():
                    handle.write(piece)
    except httpx2.HTTPError as error:
        raise client.fail(f"cannot reach {target.url}: {error}", client.EXIT_SERVER) from error
    typer.echo(f"wrote {path}, {_size(found['size_bytes'])}")


# --- changing ------------------------------------------------------------------------

EDITABLE = ("title", "kind", "notes", "url")


@group.command("set")
def set_reference(
    reference: Annotated[str, typer.Argument(help="The HID of a reference.")],
    changes: Annotated[
        list[str], typer.Argument(help="field=value: title, kind, notes, and url of a link.")
    ],
    url: Url = None,
    token: Token = None,
) -> None:
    """Change the title, the kind or the notes of a reference, or the address of a link."""
    target = client.load_target(url, token)
    found = _get(target, reference)
    body: dict[str, Any] = {"row_version": found["row_version"]}
    for argument in changes:
        name, equals, value = argument.partition("=")
        name, value = name.strip(), value.strip()
        if not equals or name not in EDITABLE:
            raise client.fail(f"{argument!r} is not field=value of {', '.join(EDITABLE)}", 2)
        body[name] = value or None
    changed = client.call(target, "PATCH", f"/reference-files/{found['hid']}", body)
    typer.echo(f"{changed['hid']}  {changed['title']} ({changed['kind']})")


@group.command("replace")
def replace_file(
    reference: Annotated[str, typer.Argument(help="The HID of a file.")],
    file: Annotated[Path, typer.Argument(help="The new edition.")],
    url: Url = None,
    token: Token = None,
) -> None:
    """Put a new edition in place of a file, on every record it is on. The edition it
    had is erased."""
    target = client.load_target(url, token)
    found = _get(target, reference)
    if not file.is_file():
        raise client.fail(f"there is no file {file}", 2)
    changed = client.call(
        target,
        "PUT",
        f"/reference-files/{found['hid']}/content",
        params={"file_name": file.name, "row_version": found["row_version"]},
        content=_pieces(file),
        content_type="application/octet-stream",
        length=file.stat().st_size,
        timeout=UPLOAD_SECONDS,
    )
    typer.echo(
        f"{changed['title']}: now {changed['file_name']}, {_size(changed['size_bytes'])}, "
        f"on {changed['attachment_count']} records"
    )


@group.command("attach")
def attach(
    reference: Annotated[str, typer.Argument(help="The HID of a reference.")],
    to: Records,
    url: Url = None,
    token: Token = None,
) -> None:
    """Put a reference on more records."""
    target = client.load_target(url, token)
    records = [find_record(target, text) for text in to]
    changed = client.call(
        target, "POST", f"/reference-files/{reference}/attachments", {"records": records}
    )
    typer.echo(f"{changed['title']}: on {changed['attachment_count']} records")


@group.command("detach")
def detach(
    reference: Annotated[str, typer.Argument(help="The HID of a reference.")],
    from_: Annotated[str, typer.Option("--from", help="The record to take it off.")],
    yes: Annotated[bool, typer.Option(help="Erase it without asking, if it is the last.")] = False,
    url: Url = None,
    token: Token = None,
) -> None:
    """Take a reference off one record. Taken off the last record it is on, it is erased
    with its content."""
    target = client.load_target(url, token)
    found = _get(target, reference)
    record = find_record(target, from_)
    attachment = next((one for one in found["attachments"] if one["record_hid"] == record), None)
    if attachment is None:
        raise client.fail(f"{found['title']} is not on that record", client.EXIT_INVALID)
    if len(found["attachments"]) == 1 and not yes:
        typer.confirm(
            f"{found['title']} is on that record alone: taking it off erases it and its "
            "content. The backups on the server keep a copy until they rotate out. Go on?",
            abort=True,
        )
    answer = client.call(
        target, "DELETE", f"/reference-files/{found['hid']}/attachments/{attachment['hid']}"
    )
    typer.echo(f"{found['title']}: erased" if answer["erased"] else f"{found['title']}: taken off")


@group.command("remove")
def erase(
    reference: Annotated[str, typer.Argument(help="The HID of a reference.")],
    yes: Annotated[bool, typer.Option(help="Erase it without asking.")] = False,
    url: Url = None,
    token: Token = None,
) -> None:
    """Erase a reference from every record it is on, and its content with it. The
    backups on the server keep a copy until they rotate out."""
    target = client.load_target(url, token)
    found = _get(target, reference)
    if not yes:
        typer.confirm(
            f"Erase {found['title']} from the {found['attachment_count']} records it is on? "
            "Its content is erased at once; the backups on the server keep a copy until "
            "they rotate out.",
            abort=True,
        )
    client.call(target, "DELETE", f"/reference-files/{found['hid']}")
    typer.echo(f"{found['title']}: erased")
