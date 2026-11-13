"""The client commands for the inventory: lists, items, import and export.

Every command here calls the API. None of them knows a rule: what a value may be, what
a filter means and what a file may hold are decided by the server, and these commands
print what it answers.
"""

import csv
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from hirdir import clock
from hirdir.cli import client
from hirdir.cli.client import Target

Url = Annotated[str | None, typer.Option(help="The server, such as https://host/hirdir.")]
Token = Annotated[str | None, typer.Option(help="A session or service token.")]
Filter = Annotated[
    str | None,
    typer.Option(
        "--filter", help="Conditions as field:op:value, such as 'lifecycle_state:eq:Prod'."
    ),
]
Sort = Annotated[
    str | None, typer.Option(help="Columns to sort by, with - in front for descending.")
]
Columns = Annotated[
    str | None, typer.Option(help="The columns wanted, separated by commas. hid always comes.")
]
Output = Annotated[
    Path | None, typer.Option("--output", help="Write to this file and not to the terminal.")
]
Archived = Annotated[
    bool, typer.Option("--include-archived", help="Retired and archived records as well.")
]
Drafts = Annotated[bool, typer.Option("--include-drafts", help="Draft records as well.")]

WIDEST = 40
LIMIT = 50
SLOW = 600.0
FILE_TYPES = {".json": "application/json", ".csv": "text/csv"}
# What a list shows on a terminal when no columns are asked for.
SHOWN = {
    "items": "name,hostname,vendor,pid,serial_number,lifecycle_state,owner",
    "vendors": "name,aliases,review_status",
    "catalog_entries": "vendor,pid,model_name,kind,type,ldos,review_status",
    "owners": "label,organization,is_external,record_status",
    "tags": "label,colour,description",
}


def _names(given: str | None) -> list[str] | None:
    names = [name.strip() for name in (given or "").split(",") if name.strip()]
    return names or None


def _table(rows: list[list[str]]) -> None:
    """Print rows as a table: the first is the header, and a long cell is cut short."""
    cut = [
        [cell if len(cell) <= WIDEST else cell[: WIDEST - 1] + "…" for cell in row] for row in rows
    ]
    widths = [max(len(row[at]) for row in cut) for at in range(len(cut[0]))]
    for number, row in enumerate(cut):
        cells = [cell.upper() if number == 0 else cell for cell in row]
        typer.echo(
            "  ".join(cell.ljust(width) for cell, width in zip(cells, widths, strict=True)).rstrip()
        )


def _export(
    target: Target,
    entity: str,
    *,
    format_: str,
    filter_: str | None,
    sort: str | None,
    columns: str | None,
    output: Path | None,
    limit: int | None = None,
    **more: bool,
) -> None:
    """Fetch an export and write it out: as a table, or as the file the server sent."""
    if format_ not in ("table", "csv", "json"):
        raise client.fail("--format is one of table, csv, json", 2)
    as_table = format_ == "table"
    body = {
        "entity": entity,
        "format": "csv" if as_table else format_,
        "filter": filter_ or None,
        "sort": _names(sort) or [],
        "columns": _names(columns or (SHOWN[entity] if as_table else None)),
        **more,
    }
    with client.download(target, "/exports", body) as answer:
        if as_table:
            rows = []
            for row in csv.reader(answer.iter_lines()):
                if limit is not None and len(rows) > limit:
                    typer.echo(f"the first {limit} are shown; --limit shows more", err=True)
                    break
                rows.append(row)
            _table(rows[: limit + 1] if limit is not None else rows)
            return
        if output is not None:
            with output.open("w", encoding="utf-8", newline="") as handle:
                for text in answer.iter_text():
                    handle.write(text)
            typer.echo(f"wrote {output}", err=True)
            return
        for text in answer.iter_text():
            sys.stdout.write(text)


def _lists(entity: str, plural: str) -> typer.Typer:
    """Return the command group of one kind of record, with its `list` command."""
    group = typer.Typer(no_args_is_help=True, help=f"{plural.capitalize()}.")

    @group.command("list")
    def list_(
        filter_: Filter = None,
        sort: Sort = None,
        columns: Columns = None,
        limit: Annotated[int, typer.Option(help="How many rows a table shows.")] = LIMIT,
        format_: Annotated[str, typer.Option("--format", help="table, csv or json")] = "table",
        output: Output = None,
        include_archived: Archived = False,
        include_drafts: Drafts = False,
        url: Url = None,
        token: Token = None,
    ) -> None:
        _export(
            client.load_target(url, token),
            entity,
            format_=format_,
            filter_=filter_,
            sort=sort,
            columns=columns,
            output=output,
            limit=limit,
            include_archived=include_archived,
            include_drafts=include_drafts,
        )

    list_.__doc__ = f"List {plural}: a table on a terminal, or all of them as CSV or JSON."
    return group


items = _lists("items", "items")
vendors = _lists("vendors", "vendors")
catalog = _lists("catalog_entries", "catalog entries")
owners = _lists("owners", "owners")
tags = _lists("tags", "tags")
GROUPS = {"items": items, "vendors": vendors, "catalog": catalog, "owners": owners, "tags": tags}


# --- one item ------------------------------------------------------------------------


def _is_hid(text: str) -> bool:
    try:
        return str(uuid.UUID(text)) == text
    except ValueError:
        return False


def _shown_name(item: dict[str, Any]) -> str:
    return item["name"] or item["hostname"] or item["serial_number"] or item["asset_tag"] or ""


def find_item(target: Target, text: str) -> dict[str, Any]:
    """Return the one item known by text: its HID, serial number, asset tag or name.

    When more than one item answers to it they are listed, and nothing is done.
    """
    if _is_hid(text):
        return client.call(target, "GET", f"/items/{text}")
    known_by = ("serial_number", "asset_tag", "name")
    query = {
        "filter": {"or": [{"field": name, "op": "eq", "value": text} for name in known_by]},
        "include_archived": True,
        "include_drafts": True,
        "limit": 20,
    }
    found = client.call(target, "POST", "/items/query", query)["items"]
    if len(found) == 1:
        return found[0]
    if not found:
        raise client.fail(f"there is no item {text}", client.EXIT_INVALID)
    for item in found:
        typer.echo(f"  {item['hid']}  {_shown_name(item)}", err=True)
    raise client.fail(
        f"more than one item answers to {text}: name the one meant by its HID", client.EXIT_INVALID
    )


def _zone(target: Target) -> str:
    """Return the application's time zone, as the server has it set."""
    for setting in client.call(target, "GET", "/settings"):
        if setting["key"] == "time_zone":
            return setting["value"]
    return clock.DEFAULT_ZONE


@items.command("show")
def show(
    item: Annotated[str, typer.Argument(help="An HID, serial number, asset tag or name.")],
    format_: Annotated[str, typer.Option("--format", help="table or json")] = "table",
    url: Url = None,
    token: Token = None,
) -> None:
    """Show one item, with the values in force of what it inherits and where they come from."""
    target = client.load_target(url, token)
    found = find_item(target, item)
    if format_ == "json":
        typer.echo(json.dumps(found, indent=2))
        return
    zone = _zone(target)
    model = found["catalog"]
    lines: list[tuple[str, Any]] = [
        ("hid", found["hid"]),
        ("name", found["name"] or found["hostname"]),
        ("model", f"{model['vendor']} {model['pid']}" if model else None),
        *((name, found[name]) for name in ("serial_number", "asset_tag", "mac_address", "fqdn")),
        ("lifecycle_state", found["lifecycle_state"]),
        ("disposition", found["disposition"]),
        ("expected_online", found["expected_online"]),
        ("state_reason", found["state_reason"]),
        ("owner", found["owner"]["label"] if found["owner"] else None),
        ("quantity", found["quantity"]),
        ("tags", ", ".join(found["tags"]) or None),
        ("record_status", found["record_status"]),
    ]
    for name, effective in found["effective"].items():
        if effective["value"] is not None:
            lines.append((name, f"{effective['value']} ({effective['source']})"))
    for name in ("state_changed_at", "created_at", "updated_at"):
        if found[name]:
            lines.append((name, clock.shown(datetime.fromisoformat(found[name]), zone)))
    lines.append(("row_version", found["row_version"]))
    for name, value in lines:
        if value is not None:
            typer.echo(
                f"{name + ':':<21}{str(value).lower() if isinstance(value, bool) else value}"
            )


@items.command("transition")
def transition(
    item: Annotated[str, typer.Argument(help="An HID, serial number, asset tag or name.")],
    to: Annotated[str, typer.Argument(help="The lifecycle state to move to.")],
    reason: Annotated[str | None, typer.Option(help="Why, as a value of the reasons list.")] = None,
    disposition: Annotated[str | None, typer.Option(help="Left out, as the state has it.")] = None,
    online: Annotated[
        bool | None,
        typer.Option("--online/--offline", help="Left out, as the state has it."),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="A move the rules do not list. Admin, with a reason.")
    ] = False,
    url: Url = None,
    token: Token = None,
) -> None:
    """Move an item to another lifecycle state."""
    target = client.load_target(url, token)
    found = find_item(target, item)
    body: dict[str, Any] = {"row_version": found["row_version"], "to": to, "force": force}
    if reason is not None:
        body["reason"] = reason
    if disposition is not None:
        body["disposition"] = disposition
    if online is not None:
        body["expected_online"] = online
    moved = client.call(target, "POST", f"/items/{found['hid']}/transition", body)
    was = found["lifecycle_state"] or "no state"
    typer.echo(f"{_shown_name(moved)}: {was} → {moved['lifecycle_state']}")


# --- changes that are previewed -------------------------------------------------------


def _counts(job: dict[str, Any]) -> str:
    return ", ".join(
        f"{job[name]} {name}" for name in ("created", "updated", "unchanged", "rejected")
    )


def _value(value: Any) -> str:
    if value is None:
        return "blank"
    if isinstance(value, list):
        return ";".join(value) or "blank"
    return str(value).lower() if isinstance(value, bool) else str(value)


def _show_rows(rows: list[dict[str, Any]], row_count: int) -> None:
    """Print what the rows of a preview would do, leaving out those that change nothing."""
    for row in rows:
        if row["outcome"] == "unchanged":
            continue
        typer.echo(f"row {row['row']}  {row['outcome']}  {row['key']}")
        for change in row["changes"]:
            typer.echo(f"    {change['field']}: {_value(change['old'])} → {_value(change['new'])}")
        for reason in row["reasons"]:
            where = f"{reason['field']}: " if reason["field"] else ""
            typer.echo(f"    {where}{reason['message']}")
        for note in row["notes"]:
            typer.echo(f"    {note}")
    if row_count > len(rows):
        typer.echo(f"the first {len(rows)} of {row_count} rows are shown", err=True)


def _finish(
    target: Target,
    preview: dict[str, Any],
    apply_path: str,
    *,
    apply: bool,
    skip_rejected: bool,
    as_json: bool,
) -> None:
    """Print a preview, and apply it when asked to and when nothing stands in the way."""
    job = preview["job"]
    if not apply:
        if as_json:
            typer.echo(json.dumps(preview, indent=2))
        else:
            _show_rows(preview["rows"], job["row_count"])
            typer.echo(
                f"preview: {_counts(job)}. Nothing was changed; --apply applies it.", err=True
            )
        if job["rejected"]:
            raise typer.Exit(client.EXIT_INVALID)
        return
    if job["rejected"] and not skip_rejected:
        rejected = client.call(
            target, "GET", f"/imports/{job['hid']}/rows", params={"outcome": "rejected"}
        )
        _show_rows(rejected["items"], rejected["total"])
        raise client.fail(
            f"{job['rejected']} rows are rejected and nothing was applied: correct them, "
            "or apply the rest with --skip-rejected",
            client.EXIT_INVALID,
        )
    done = client.call(
        target,
        "POST",
        apply_path.format(hid=job["hid"]),
        params={"skip_rejected": "true"} if skip_rejected else None,
        timeout=SLOW,
    )
    if as_json:
        typer.echo(json.dumps(done, indent=2))
    else:
        if not as_json and job["row_count"] <= len(preview["rows"]):
            _show_rows(preview["rows"], job["row_count"])
        left = f", {done['rejected']} rejected and left out" if done["rejected"] else ""
        typer.echo(
            f"applied: {done['created']} created, {done['updated']} updated, "
            f"{done['unchanged']} unchanged{left}",
            err=True,
        )


def import_file(
    file: Annotated[Path, typer.Argument(help="A CSV file, or a JSON file in its envelope.")],
    entity: Annotated[
        str | None, typer.Option(help="The records the file holds. A JSON file may say so itself.")
    ] = None,
    mode: Annotated[str | None, typer.Option(help="upsert, or create to refuse a match.")] = None,
    apply: Annotated[
        bool, typer.Option("--apply", help="Apply the file after the preview.")
    ] = False,
    skip_rejected: Annotated[
        bool, typer.Option("--skip-rejected", help="Apply the rows that are not rejected.")
    ] = False,
    format_: Annotated[str, typer.Option("--format", help="table or json")] = "table",
    url: Url = None,
    token: Token = None,
) -> None:
    """Preview what a file would create and change, and with --apply, do it."""
    target = client.load_target(url, token)
    try:
        data = file.read_bytes()
    except OSError as error:
        raise client.fail(f"cannot read {file}: {error.strerror}", 2) from None
    preview = client.call(
        target,
        "POST",
        "/imports/preview",
        params={"entity": entity, "mode": mode, "file_name": file.name},
        content=data,
        content_type=FILE_TYPES.get(file.suffix.lower(), "text/csv"),
        timeout=SLOW,
    )
    _finish(
        target,
        preview,
        "/imports/{hid}/apply",
        apply=apply,
        skip_rejected=skip_rejected,
        as_json=format_ == "json",
    )


def export(
    entity: Annotated[str, typer.Argument(help="items, vendors, catalog_entries, owners or tags")],
    filter_: Filter = None,
    sort: Sort = None,
    columns: Columns = None,
    format_: Annotated[str, typer.Option("--format", help="csv or json")] = "csv",
    output: Output = None,
    own_values: Annotated[
        bool,
        typer.Option("--own-values", help="Stored values, not those in force: to import back."),
    ] = False,
    include_sources: Annotated[
        bool, typer.Option("--include-sources", help="Add where each inherited value came from.")
    ] = False,
    include_archived: Archived = False,
    include_drafts: Drafts = False,
    url: Url = None,
    token: Token = None,
) -> None:
    """Export records as CSV or JSON, to the terminal or to a file."""
    if format_ not in ("csv", "json"):
        raise client.fail("--format is one of csv, json", 2)
    _export(
        client.load_target(url, token),
        entity.replace("-", "_"),
        format_=format_,
        filter_=filter_,
        sort=sort,
        columns=columns,
        output=output,
        own_values=own_values,
        include_sources=include_sources,
        include_archived=include_archived,
        include_drafts=include_drafts,
    )


@items.command("set")
def set_(
    arguments: Annotated[
        list[str],
        typer.Argument(
            help="An item, then field=value to set and field= to clear. With --filter or "
            "--all, the fields alone."
        ),
    ],
    filter_: Filter = None,
    all_rows: Annotated[bool, typer.Option("--all", help="Every item.")] = False,
    add_tag: Annotated[
        list[str] | None, typer.Option(help="A tag to put on. May be repeated.")
    ] = None,
    remove_tag: Annotated[
        list[str] | None, typer.Option(help="A tag to take off. May be repeated.")
    ] = None,
    apply: Annotated[
        bool, typer.Option("--apply", help="Apply a change to more than one item.")
    ] = False,
    skip_rejected: Annotated[
        bool, typer.Option("--skip-rejected", help="Change the rows that are not rejected.")
    ] = False,
    include_archived: Archived = False,
    include_drafts: Drafts = False,
    format_: Annotated[str, typer.Option("--format", help="table or json")] = "table",
    url: Url = None,
    token: Token = None,
) -> None:
    """Change one item, or with --filter, many: previewed first, applied with --apply."""
    target = client.load_target(url, token)
    many = filter_ is not None or all_rows
    named = [] if many else arguments[:1]
    changes: dict[str, Any] = {}
    for argument in arguments[len(named) :]:
        name, equals, value = argument.partition("=")
        if not equals or not name.strip():
            raise client.fail(f"{argument!r} is not field=value", 2)
        changes[name.strip()] = value if value.strip() else None
    body: dict[str, Any] = {
        "set": changes,
        "add_tags": add_tag or [],
        "remove_tags": remove_tag or [],
    }
    if many:
        body.update(
            filter=filter_,
            all_rows=all_rows,
            include_archived=include_archived,
            include_drafts=include_drafts,
        )
    elif not named or "=" in named[0]:
        raise client.fail("name an item, or the rows with --filter or --all", 2)
    else:
        body["hids"] = [find_item(target, named[0])["hid"]]
    preview = client.call(target, "POST", "/items/bulk-update", body, timeout=SLOW)
    _finish(
        target,
        preview,
        "/items/bulk-update/{hid}/apply",
        # One item is changed there and then. More than one is previewed first.
        apply=apply or not many,
        skip_rejected=skip_rejected,
        as_json=format_ == "json",
    )
