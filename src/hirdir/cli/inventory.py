"""The client commands for the inventory: lists, items, groups, reports, import and export.

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
from hirdir.io.columns import unguarded

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
    "regions": "path,code,record_status",
    "sites": "path,code,city,country,record_status",
    "locations": "path,kind,code,record_status",
    "contacts": "name,organization,email,phone,record_status",
    "tags": "label,colour,description",
    "networks": "label,kind",
    "addresses": "address,network,item,group,role,is_primary",
    "device_groups": "name,type,hostname,serial_number,members,health,owner,record_status",
}
# What a minor item may have from the item it is in.
FROM_ABOVE = ("lifecycle_state", "disposition", "expected_online")
INHERIT = "inherit"


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
                # A table is read by a person, not opened by a spreadsheet.
                rows.append([unguarded(cell) for cell in row])
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
networks = _lists("networks", "networks")
addresses = _lists("addresses", "addresses")
groups = _lists("device_groups", "device groups")
regions = _lists("regions", "regions")
sites = _lists("sites", "sites")
locations = _lists("locations", "locations")
contacts = _lists("contacts", "contacts")
geography = typer.Typer(no_args_is_help=True, help="The regions, sites and locations as one tree.")
report = typer.Typer(no_args_is_help=True, help="Reports.")
GROUPS = {
    "items": items,
    "vendors": vendors,
    "catalog": catalog,
    "owners": owners,
    "tags": tags,
    "networks": networks,
    "addresses": addresses,
    "groups": groups,
    "regions": regions,
    "sites": sites,
    "locations": locations,
    "contacts": contacts,
    "geography": geography,
    "report": report,
}


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


def _named(ref: dict[str, Any]) -> str:
    """Return what one line calls an item that another record refers to."""
    return ref.get("name") or ref.get("serial_number") or ref.get("asset_tag") or ref["hid"]


def _address(address: dict[str, Any]) -> str:
    under = f" under {address['network']}" if address["network"] else ""
    primary = ", primary" if address["is_primary"] else ""
    return f"{address['address']}{under} ({address['role']}{primary})"


def _in_force(item: dict[str, Any], name: str) -> Any:
    """Return a value an item has itself, or has from the item it is in, and says so."""
    effective = item["effective"][name]
    value = effective.get("label") or effective["value"]
    if value is None or effective["source"] == "own":
        return value
    shown = str(value).lower() if isinstance(value, bool) else value
    return f"{shown} ({effective['source']})"


def _health(health: dict[str, Any] | None) -> str | None:
    """Return a health with its reasons, as one line."""
    if health is None:
        return None
    return f"{health['value']}: {'; '.join(health['reasons'])}"


def _observed(target: Target, record: dict[str, Any], zone: str) -> str | None:
    """Return what is observed of a record, with the moment it was seen."""
    if record["observed_status"] is None:
        return None
    seen = clock.shown(datetime.fromisoformat(record["observed_at"]), zone)
    return f"{record['observed_status']}, seen {seen}"


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
        ("in", _named(found["parent"]) if found["parent"] else None),
        ("position", found["position"]),
        ("minor_items", found["minor_items"] or None),
        *((name, _in_force(found, name)) for name in FROM_ABOVE),
        ("state_reason", found["state_reason"]),
        ("condition", found["condition"]),
        ("observed_status", _observed(target, found, zone)),
        ("health", _health(found["health"])),
        ("owner", _in_force(found, "owner_hid")),
        ("owner_exception", found["owner_exception_reason"] or found["owner_exception"] or None),
        ("operator", _in_force(found, "operator_hid")),
        ("location", _in_force(found, "location_hid")),
        ("quantity", found["quantity"]),
        ("tags", ", ".join(found["tags"]) or None),
        ("record_status", found["record_status"]),
    ]
    for group in found["groups"]:
        place = f", position {group['position']}" if group["position"] is not None else ""
        lines.append(("group", f"{group['name']} ({group['type']}, {group['role']}{place})"))
    for controller in found["controllers"]:
        within = f" ({controller['cluster']})" if controller["cluster"] else ""
        lines.append(("controller", _named(controller) + within))
    for address in found["addresses"]:
        lines.append(("address", _address(address)))
    for name in ("replaces", "replaced_by"):
        if found[name]:
            other = found[name]
            why = " ".join(part for part in (other["reason"], other["reference"]) if part)
            lines.append((name, f"{_named(other)} on {other['replaced_on']} ({why})"))
    for name, effective in found["effective"].items():
        shown = ("owner_hid", "operator_hid", "location_hid", *FROM_ABOVE)
        if name not in shown and effective["value"] is not None:
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
    to: Annotated[
        str,
        typer.Argument(
            help="The lifecycle state to move to. For a minor item, `inherit` returns it "
            "to the standing of the item it is in."
        ),
    ],
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
    back = to.strip().lower() == INHERIT
    body: dict[str, Any] = {
        "row_version": found["row_version"],
        "to": None if back else to,
        "force": force,
    }
    if reason is not None:
        body["reason"] = reason
    if disposition is not None:
        body["disposition"] = disposition
    if online is not None:
        body["expected_online"] = online
    moved = client.call(target, "POST", f"/items/{found['hid']}/transition", body)
    was = found["lifecycle_state"] or "no state"
    now = moved["lifecycle_state"]
    if back:
        now = (
            f"{moved['effective']['lifecycle_state']['value'] or 'no state'}, as the item it is in"
        )
    typer.echo(f"{_shown_name(moved)}: {was} → {now}")


# --- groups --------------------------------------------------------------------------


def find_group(target: Target, text: str) -> dict[str, Any]:
    """Return the device group with an HID or a name."""
    if _is_hid(text):
        return client.call(target, "GET", f"/device-groups/{text}")
    query = {
        "filter": {"field": "name", "op": "eq", "value": text},
        "include_archived": True,
        "include_drafts": True,
        "limit": 2,
    }
    found = client.call(target, "POST", "/device-groups/query", query)["items"]
    if not found:
        raise client.fail(f"there is no device group {text}", client.EXIT_INVALID)
    return found[0]


@groups.command("show")
def show_group(
    group: Annotated[str, typer.Argument(help="An HID or a name.")],
    include_past: Annotated[
        bool, typer.Option("--include-past", help="The memberships that have ended as well.")
    ] = False,
    format_: Annotated[str, typer.Option("--format", help="table or json")] = "table",
    url: Url = None,
    token: Token = None,
) -> None:
    """Show one device group with its members, their roles and, for a stack, its serial number."""
    target = client.load_target(url, token)
    found = find_group(target, group)
    members: list[dict[str, Any]] = []
    while True:
        page = client.call(
            target,
            "GET",
            f"/device-groups/{found['hid']}/members",
            params={"include_past": include_past, "limit": 1000, "offset": len(members)},
        )
        members += page["items"]
        if not page["items"] or len(members) >= page["total"]:
            break
    if format_ == "json":
        typer.echo(json.dumps({**found, "members": members}, indent=2))
        return
    owner = found["owner"]["label"] if found["owner"] else None
    if owner and "owner_hid" in found["members_disagree"]:
        owner += " (a member has another owner)"
    zone = _zone(target)
    serial = found["serial_number"]
    if serial:
        serial += f" (of the master that is {found['serial_source']})"
    seen = _named(found["observed_master"]) if found["observed_master"] else None
    if seen:
        at = clock.shown(datetime.fromisoformat(found["master_observed_at"]), zone)
        seen += f", seen {at}"
        if found["master_as_intended"] is False:
            seen += " (not the one intended)"
    lines: list[tuple[str, Any]] = [
        ("hid", found["hid"]),
        ("name", found["name"]),
        ("type", found["type"]),
        ("hostname", found["hostname"]),
        ("fqdn", found["fqdn"]),
        ("serial_number", serial),
        ("intended_master", _named(found["master"]) if found["master"] else None),
        ("observed_master", seen),
        ("owner_exception", found["owner_exception_reason"]),
        ("operator", _in_force(found, "operator_hid")),
        ("location", found["location"]["path"] if found["location"] else None),
        ("managed_as", found["managed_as"]),
        ("expected_members", found["expected_members"]),
        ("observed_status", _observed(target, found, zone)),
        ("health", _health(found["health"])),
        ("in", found["parent"]["name"] if found["parent"] else None),
        *(("group", f"{inner['name']} ({inner['type']})") for inner in found["groups"]),
        ("owner", owner),
        *(("address", _address(address)) for address in found["addresses"]),
        ("tags", ", ".join(found["tags"]) or None),
        ("record_status", found["record_status"]),
        ("members", found["member_count"]),
        ("row_version", found["row_version"]),
    ]
    for name, value in lines:
        if value is not None:
            typer.echo(f"{name + ':':<21}{value}")
    if members:
        typer.echo("")
        head = ["position", "role", "name", "pid", "serial_number", "joined_on", "left_on"]
        _table(
            [
                head,
                *(
                    [
                        "" if member["position"] is None else str(member["position"]),
                        member["role"],
                        member["item"]["name"] or "",
                        member["item"]["pid"] or "",
                        member["item"]["serial_number"] or "",
                        member["joined_on"],
                        member["left_on"] or "",
                    ]
                    for member in members
                ),
            ]
        )


# --- reports -------------------------------------------------------------------------

MEASURES = ("items", "component_count", "managed_node_count", "support_weight")
HEALTHS = ("good", "degraded", "failed", "unknown")
MONEY = ("items", "component_count", "est_value", "annual_support_cost")


def _rows(format_: str, output: Path | None, rows: list[list[str]]) -> None:
    """Print the rows of a report as a table, or write them as CSV."""
    if format_ == "table":
        _table(rows)
        return
    handle = output.open("w", encoding="utf-8", newline="") if output is not None else sys.stdout
    try:
        csv.writer(handle, lineterminator="\n").writerows(rows)
    finally:
        if output is not None:
            handle.close()
            typer.echo(f"wrote {output}", err=True)


def _checked_format(format_: str) -> None:
    if format_ not in ("table", "csv", "json"):
        raise client.fail("--format is one of table, csv, json", 2)


@report.command("summary")
def summary(
    filter_: Filter = None,
    by: Annotated[
        str | None,
        typer.Option(
            help="One row for each: vendor, kind, type, function, owner, lifecycle_state, "
            "disposition, condition, health or tag."
        ),
    ] = None,
    include_archived: Archived = False,
    include_drafts: Drafts = False,
    format_: Annotated[str, typer.Option("--format", help="table, csv or json")] = "table",
    output: Output = None,
    url: Url = None,
    token: Token = None,
) -> None:
    """Count a view of the items: components, managed nodes, support weight and health."""
    _checked_format(format_)
    target = client.load_target(url, token)
    found = client.call(
        target,
        "GET",
        "/reports/summary",
        params={
            "filter": filter_,
            "by": by,
            "include_archived": include_archived,
            "include_drafts": include_drafts,
        },
    )
    if format_ == "json":
        typer.echo(json.dumps(found, indent=2))
        return
    totals = found["totals"]

    def cells(row: dict[str, Any]) -> list[str]:
        return [
            *(str(row[name]) for name in MEASURES),
            *(str(row["by_health"][name]) for name in HEALTHS),
        ]

    head = [*MEASURES, *HEALTHS]
    if by is None:
        if format_ == "csv":
            _rows(format_, output, [head, cells(totals)])
            return
        for name, value in zip(head, cells(totals), strict=True):
            typer.echo(f"{name + ':':<21}{value}")
        for kind in totals["by_kind"]:
            typer.echo(
                f"{kind['key'] + ':':<21}{kind['items']} items, {kind['component_count']} in hand"
            )
        return
    rows = [[by, *head]]
    for row in found["rows"]:
        rows.append([row["label"] or "(none)", *cells(row)])
    rows.append(["(all)", *cells(totals)])
    _rows(format_, output, rows)


@report.command("management")
def management(
    filter_: Filter = None,
    by: Annotated[
        str | None,
        typer.Option(
            help="One row for each: vendor, kind, type, function, owner, site, region or "
            "tag. Left out, site."
        ),
    ] = None,
    include_archived: Archived = False,
    include_drafts: Drafts = False,
    format_: Annotated[str, typer.Option("--format", help="table, csv or json")] = "table",
    output: Output = None,
    url: Url = None,
    token: Token = None,
) -> None:
    """Show the estimated value and the annual support cost of a view of the items, for
    the whole of it and for each site."""
    _checked_format(format_)
    target = client.load_target(url, token)
    found = client.call(
        target,
        "GET",
        "/reports/management",
        params={
            "filter": filter_,
            "by": by,
            "include_archived": include_archived,
            "include_drafts": include_drafts,
        },
    )
    if format_ == "json":
        typer.echo(json.dumps(found, indent=2))
        return
    totals = found["totals"]
    # Asked for by nothing, the server answers by site, and says so.
    by = found["by"]
    rows = [[by, *MONEY]]
    for row in found["rows"]:
        rows.append([row["label"] or "(none)", *(str(row[name]) for name in MONEY)])
    rows.append(["(all)", *(str(totals[name]) for name in MONEY)])
    _rows(format_, output, rows)


@report.command("duplicates")
def duplicates(
    include_archived: Archived = False,
    include_drafts: Drafts = False,
    format_: Annotated[str, typer.Option("--format", help="table, csv or json")] = "table",
    output: Output = None,
    url: Url = None,
    token: Token = None,
) -> None:
    """List each address that is held more than once under one network, and by what."""
    _checked_format(format_)
    target = client.load_target(url, token)
    found: list[dict[str, Any]] = []
    while True:
        page = client.call(
            target,
            "GET",
            "/reports/duplicates",
            params={
                "include_archived": include_archived,
                "include_drafts": include_drafts,
                "limit": 1000,
                "offset": len(found),
            },
        )
        found += page["items"]
        if not page["items"] or len(found) >= page["total"]:
            break
    if format_ == "json":
        typer.echo(json.dumps(found, indent=2))
        return
    if not found and format_ == "table":
        typer.echo("no address is held more than once under one network", err=True)
        return
    rows = [["address", "network", "held_by", "role"]]
    for one in found:
        for holder in one["holders"]:
            rows.append(
                [one["address"], one["network"] or "", holder["name"] or "", holder["role"]]
            )
    _rows(format_, output, rows)


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


# --- places --------------------------------------------------------------------------

LEVELS = {"region": "regions", "site": "sites", "location": "locations"}
PLACE_COUNTS = ("items", "component_count")


def find_place(target: Target, text: str, level: str | None = None) -> dict[str, Any]:
    """Return the region, site or location known by text: its HID or its path.

    The server finds it, as it finds the place a filter names, so that a path means
    here what it means there.
    """
    found = client.call(
        target,
        "GET",
        "/geography/tree",
        # A place that is asked for by name is shown whatever the view leaves out,
        # and its counts are those of the view a list shows.
        params={"root": text, "locations": False},
    )["roots"][0]
    if level is not None and found["level"] != level:
        raise client.fail(
            f"{found['path']} is a {found['level']}, not a {level}", client.EXIT_INVALID
        )
    return found


def _show_place(level: str) -> Any:
    def show(
        place: Annotated[str, typer.Argument(help="An HID or a path.")],
        format_: Annotated[str, typer.Option("--format", help="table or json")] = "table",
        url: Url = None,
        token: Token = None,
    ) -> None:
        target = client.load_target(url, token)
        node = find_place(target, place, level)
        record = client.call(target, "GET", f"/{LEVELS[level]}/{node['hid']}")
        in_force = client.call(target, "GET", f"/{LEVELS[level]}/{node['hid']}/effective")
        if format_ == "json":
            typer.echo(json.dumps({**record, "effective": in_force}, indent=2))
            return
        lines: list[tuple[str, Any]] = [
            ("hid", record["hid"]),
            ("path", record["path"]),
            ("code", record["code"]),
            ("kind", record.get("kind")),
            ("items", node["items"]),
            ("component_count", node["component_count"]),
            ("tags", ", ".join(record["tags"]) or None),
            ("record_status", record["record_status"]),
        ]
        street = [record.get(name) for name in ("address1", "address2", "city", "state")]
        street += [record.get(name) for name in ("postal_code", "country")]
        lines.append(("address", ", ".join(part for part in street if part) or None))
        for role in in_force["contacts"]:
            where = _from(role)
            if role["stopped"]:
                lines.append((role["role"], f"nobody{where}"))
            for contact in role["contacts"]:
                reached = " ".join(part for part in (contact["email"], contact["phone"]) if part)
                lines.append((role["role"], f"{contact['name']} {reached}".rstrip() + where))
        shipping = in_force["ship_address"]
        if shipping["value"] is not None:
            parts = ", ".join(part for part in shipping["value"].values() if part)
            if shipping["same_as_address"]:
                parts += ", its street address"
            lines.append(("ship_address", parts + _from(shipping)))
        said = in_force["ship_instructions"]
        if said["value"] is not None:
            lines.append(("ship_instructions", said["value"] + _from(said)))
        lines.append(("row_version", record["row_version"]))
        for name, value in lines:
            if value is not None:
                typer.echo(f"{name + ':':<21}{value}")

    show.__doc__ = (
        f"Show one {level} with the contacts and the shipping address it has in force, "
        "each with the level it came from."
    )
    return show


def _from(found: dict[str, Any]) -> str:
    """Return where a value in force came from, for the end of its line."""
    if found["source"] == "none":
        return ""
    if found["source"] == "own":
        # Its own, where a level above has one too: an override, and of what.
        over = found["overrides_path"]
        return f" (set here, in place of the one from {over})" if over else ""
    return f" (from {found['source_path']})"


def _move(level: str, field: str, into: str) -> Any:
    def move(
        place: Annotated[str, typer.Argument(help="An HID or a path.")],
        to: Annotated[
            str, typer.Argument(help=f"The HID or the path of the {into} to move it to.")
        ],
        url: Url = None,
        token: Token = None,
    ) -> None:
        target = client.load_target(url, token)
        node = find_place(target, place, level)
        top = level == "region" and to.strip().lower() == "top"
        new = None if top else find_place(target, to, "region")["hid"]
        record = client.call(target, "GET", f"/{LEVELS[level]}/{node['hid']}")
        changed = client.call(
            target,
            "PATCH",
            f"/{LEVELS[level]}/{node['hid']}",
            {"row_version": record["row_version"], field: new},
        )
        typer.echo(f"{record['path']} is now {changed['path']}")

    move.__doc__ = (
        f"Move a {level} to another {into}: one change, after which the paths and the "
        "totals follow."
    )
    return move


regions.command("show")(_show_place("region"))
sites.command("show")(_show_place("site"))
locations.command("show")(_show_place("location"))
sites.command("move")(_move("site", "region_hid", "region"))
regions.command("move")(_move("region", "parent_region_hid", "region, or `top` for none"))


@geography.command("tree")
def tree(
    filter_: Filter = None,
    root: Annotated[
        str | None, typer.Option(help="The HID or the path of the place to start from.")
    ] = None,
    locations_: Annotated[
        bool, typer.Option("--locations/--no-locations", help="Stop at the sites, or do not.")
    ] = True,
    include_archived: Archived = False,
    include_drafts: Drafts = False,
    format_: Annotated[str, typer.Option("--format", help="table, csv or json")] = "table",
    output: Output = None,
    url: Url = None,
    token: Token = None,
) -> None:
    """Show the regions, their sites and the locations within them, each with the items
    and the components at or beneath it."""
    _checked_format(format_)
    target = client.load_target(url, token)
    found = client.call(
        target,
        "GET",
        "/geography/tree",
        params={
            "filter": filter_,
            "root": root,
            "locations": locations_,
            "include_archived": include_archived,
            "include_drafts": include_drafts,
        },
    )
    if format_ == "json":
        typer.echo(json.dumps(found, indent=2))
        return
    indent = "" if format_ == "csv" else "  "
    rows = [["place", "level", *PLACE_COUNTS]]

    def walk(node: dict[str, Any], depth: int) -> None:
        name = node["path"] if format_ == "csv" else indent * depth + node["name"]
        rows.append([name, node["level"], *(str(node[count]) for count in PLACE_COUNTS)])
        for child in node["children"]:
            walk(child, depth + 1)

    for top in found["roots"]:
        walk(top, 0)
    for name, label in (("unplaced", "(nowhere)"), ("hidden", "(not shown)"), ("totals", "(all)")):
        if name == "totals" or found[name]["items"]:
            rows.append([label, "", *(str(found[name][count]) for count in PLACE_COUNTS)])
    _rows(format_, output, rows)
