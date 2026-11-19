"""The client commands for the inventory: lists, items, groups, reports, import and export.

Every command here calls the API. None of them knows a rule: what a value may be, what
a filter means and what a file may hold are decided by the server, and these commands
print what it answers.
"""

import csv
import json
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from hirdir import clock
from hirdir.cli import client
from hirdir.cli.client import Target
from hirdir.domain import settings
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
    "contacts": "name,organization,email,phone,phone2,user,record_status",
    "operators": "label,description,contact,scope,is_open,record_status",
    "tags": "label,colour,description",
    "networks": "label,kind",
    "addresses": "address,network,item,group,role,is_primary",
    "device_groups": "name,type,hostname,serial_number,members,health,owner,record_status",
    "agreements": "name,number,vendor,starts_on,ends_on,status,next_starts_on,record_status",
    "contracts": "number,vendor,agreement,starts_on,ends_on,status,covered_items,record_status",
    "purchase_requests": "reference,requested_on,status,notes",
    "external_systems": "name,kind,url,record_status",
    "registrations": "system,item,group,external_id,status,confirmed_at",
    "capacity_lines": "side,category,name,effect,quantity,units_each,units,vendor,record_status",
    # Circuits and circuit groups (P-154).
    "circuits": (
        "name,enterprise_circuit_id,circuit_type,speed,carrier,carrier_circuit_number,"
        "a_site,z_site,monthly_cost,record_status"
    ),
    "circuit_groups": "name,description,owner,circuits,monthly_cost,annual_cost,record_status",
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
operators = _lists("operators", "operators")
agreements = _lists("agreements", "support agreements")
contracts = _lists("contracts", "contracts")
purchases = _lists("purchase_requests", "purchase requests")
systems = _lists("external_systems", "external systems")
registrations = _lists("registrations", "registrations")
capacity = _lists("capacity_lines", "capacity lines")
circuits = _lists("circuits", "circuits")
circuit_groups = _lists("circuit_groups", "circuit groups")
geography = typer.Typer(no_args_is_help=True, help="The regions, sites and locations as one tree.")
report = typer.Typer(no_args_is_help=True, help="Reports.")
replacements = typer.Typer(
    no_args_is_help=True, help="Replacements: one that was a mistake is removed by an Admin."
)
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
    "operators": operators,
    "agreements": agreements,
    "contracts": contracts,
    "purchases": purchases,
    "systems": systems,
    "registrations": registrations,
    "capacity": capacity,
    "circuits": circuits,
    "circuit-groups": circuit_groups,
    "geography": geography,
    "report": report,
    "replacements": replacements,
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


def _operator(effective: dict[str, Any]) -> str | None:
    """Return an operator in force as one line: the label, who is behind it or that
    nobody is, and where it came from when it is not the record's own."""
    if effective["value"] is None:
        return None
    behind = "open: nobody is behind it" if effective["is_open"] else effective["contact"]
    shown = f"{effective['label']} ({behind})"
    if effective["source"] == "own":
        return shown
    where = effective["source"].replace("_", " ")
    named = f" {effective['source_label']}" if effective["source_label"] else ""
    return f"{shown}, from the {where}{named}"


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


def _setting(target: Target, key: str, otherwise: Any) -> Any:
    """Return the value of a setting as the server has it, or otherwise where it has none."""
    for setting in client.call(target, "GET", "/settings"):
        if setting["key"] == key:
            return setting["value"]
    return otherwise


def _zone(target: Target) -> str:
    """Return the application's time zone, as the server has it set."""
    return _setting(target, "time_zone", clock.DEFAULT_ZONE)


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
        ("operator", _operator(found["effective"]["operator_hid"])),
        ("location", _in_force(found, "location_hid")),
        ("planned_location", _in_force(found, "planned_location_hid")),
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
    # Every replacement it is part of, the latest first (P-241).
    for one in found.get("replacements") or []:
        why = " ".join(part for part in (one["reason"], one["reference"]) if part)
        name = "replaced_by" if one["part"] == "left" else "replaces"
        lines.append((name, f"{_named(one['item'])} on {one['replaced_on']} ({why})"))
    for name, effective in found["effective"].items():
        shown = ("owner_hid", "operator_hid", "location_hid", *FROM_ABOVE)
        if name not in shown and effective["value"] is not None:
            # A weight raised to the minimum says what it was (P-155).
            raised = effective.get("raised_from")
            came = effective["source"] + (f", raised from {raised}" if raised else "")
            lines.append((name, f"{effective['value']} ({came})"))
    # The links of its model.
    lines += [("link", _link(link)) for link in (model["links"] if model else [])]
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
        ("operator", _operator(found["effective"]["operator_hid"])),
        ("location", _in_force(found, "location_hid")),
        ("planned_location", _in_force(found, "planned_location_hid")),
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
        # A stack: the position a member added with none takes (P-219).
        ("next_position", found["next_position"]),
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
            help="One row for each: vendor, kind, type, function, owner, operator, site, "
            "region, contract, group, model, lifecycle_state, disposition, condition, health "
            "or tag."
        ),
    ] = None,
    operators_: Annotated[
        bool,
        typer.Option(
            "--operators", help="With --by: who looks after the items of each row, and how much."
        ),
    ] = False,
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
            "operators": operators_ and by is not None,
            "include_archived": include_archived,
            "include_drafts": include_drafts,
        },
    )
    if format_ == "json":
        typer.echo(json.dumps(found, indent=2))
        return
    totals = found["totals"]
    involved = operators_ and by is not None

    def cells(row: dict[str, Any]) -> list[str]:
        shown = [
            *(str(row[name]) for name in MEASURES),
            *(str(row["by_health"][name]) for name in HEALTHS),
        ]
        if involved:
            # Who looks after it, each with its support weight: the most first.
            shown.append(
                ", ".join(
                    f"{one['label'] or '(nobody)'} {one['support_weight']}"
                    for one in row.get("operators") or []
                )
            )
        return shown

    head = [*MEASURES, *HEALTHS, *(("operators",) if involved else ())]
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
            help="One row for each: vendor, kind, type, function, owner, operator, site, "
            "region, contract, group, model or tag. Left out, site."
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
    wait: bool = True,
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
            _say_not_reported(preview)
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
    if not as_json and job["row_count"] <= len(preview["rows"]):
        _show_rows(preview["rows"], job["row_count"])
    _apply_job(target, apply_path.format(hid=job["hid"]), skip_rejected, as_json=as_json, wait=wait)


def _say_not_reported(preview: dict[str, Any]) -> None:
    """Say how many items a file that is everything its system reports would mark as
    reported no more, with the first of them (P-248)."""
    job = preview["job"]
    if not job.get("complete"):
        return
    system = (job.get("system") or {}).get("name", "the system")
    count = job["not_reported"]
    if not count:
        typer.echo(f"it marks nothing as not reported by {system}", err=True)
        return
    first = ", ".join(one["label"] for one in preview["not_reported_first"])
    more = f" and {count - len(preview['not_reported_first'])} more" if count > 10 else ""
    typer.echo(f"it marks {count} as not reported by {system}: {first}{more}", err=True)


# --- an apply in the background (D-185) ---

NoWait = Annotated[
    bool,
    typer.Option("--no-wait", help="Leave the apply to the server, and do not wait for it to end."),
]
BEING_APPLIED = ("queued", "applying")
# How long the command waits between two looks at a job being applied: at first, and
# at the longest, in seconds. A small file is done before a person would notice.
FIRST_LOOK = 0.05
LOOK_AT_MOST = 1.0


def _apply_job(
    target: Target, path: str, skip_rejected: bool, *, as_json: bool, wait: bool
) -> None:
    """Ask for a job to be applied, or resumed, and wait for its end unless told not to."""
    job = client.call(
        target, "POST", path, params={"skip_rejected": "true"} if skip_rejected else None
    )
    if wait:
        job = _wait(target, job, quiet=as_json)
    _ended(target, job, as_json=as_json)


def _wait(target: Target, job: dict[str, Any], *, quiet: bool = False) -> dict[str, Any]:
    """Wait for a job being applied to end, saying how far it has got. Return it then.

    Stopping the command does not stop the apply, which the server goes on with.
    """
    pause = FIRST_LOOK
    said = None
    while job["status"] in BEING_APPLIED:
        now = (job["status"], job["rows_done"])
        if not quiet and now != said:
            typer.echo(
                "queued: waiting for another import to be applied"
                if job["status"] == "queued"
                else f"applying: {job['rows_done']} of {job['row_count']} rows",
                err=True,
            )
            said = now
        time.sleep(pause)
        pause = min(pause * 2, LOOK_AT_MOST)
        job = client.call(target, "GET", f"/imports/{job['hid']}")
    return job


def _show_applied(rows: list[dict[str, Any]]) -> None:
    """Print the rows that an apply left out, each with why."""
    for row in rows:
        typer.echo(f"row {row['row']}  {row['applied_outcome']}  {row['key']}")
        for reason in row["applied_reasons"]:
            where = f"{reason['field']}: " if reason["field"] else ""
            typer.echo(f"    {where}{reason['message']}")


def _ended(target: Target, job: dict[str, Any], *, as_json: bool) -> None:
    """Say how an apply ended, and exit with the code for it."""
    hid = job["hid"]
    if as_json:
        typer.echo(json.dumps(job, indent=2))
    if job["status"] in BEING_APPLIED:
        typer.echo(
            f"{job['status']}: the server applies it; `hirdir imports show {hid} --wait` "
            "waits for its end",
            err=True,
        )
        return
    if job["status"] == "stopped":
        raise client.fail(
            f"stopped after {job['rows_done']} of {job['row_count']} rows: {job['failure']}. "
            f"`hirdir imports apply {hid}` resumes it",
            client.EXIT_SERVER,
        )
    left_out = job["rejected"] if job["skip_rejected"] else 0
    refused = job["rows_done"] - job["applied"] - job["stale"] - left_out
    if not job["stale"] and not refused:
        left = f", {job['rejected']} rejected and left out" if left_out else ""
        marked = f", {job['not_reported']} marked not reported" if job.get("complete") else ""
        typer.echo(
            f"applied: {job['created']} created, {job['updated']} updated, "
            f"{job['unchanged']} unchanged{left}{marked}",
            err=True,
        )
        return
    rows = []
    for outcome in ("stale", "rejected"):
        offset = 0
        while True:
            page = client.call(
                target,
                "GET",
                f"/imports/{hid}/rows",
                params={"applied_outcome": outcome, "limit": 1000, "offset": offset},
            )
            rows += [row for row in page["items"] if row["outcome"] != "rejected"]
            offset += len(page["items"])
            if not page["items"] or offset >= page["total"]:
                break
    if not as_json:
        _show_applied(sorted(rows, key=lambda row: row["row"]))
    said = [f"applied: {job['applied']} of {job['row_count']} rows"]
    if job["stale"]:
        said.append(f"{job['stale']} changed since the preview and were left out")
    if refused:
        said.append(f"{refused} were refused when they were applied")
    raise client.fail(
        "; ".join(said) + ": preview them again",
        client.EXIT_CONFLICT if job["stale"] else client.EXIT_INVALID,
    )


imports_ = typer.Typer(
    no_args_is_help=True, help="Stored previews of imports and bulk edits, and their applies."
)


@imports_.command("show")
def show_import(
    hid: Annotated[str, typer.Argument(help="The HID of the stored preview.")],
    wait: Annotated[
        bool, typer.Option("--wait", help="Wait for an apply that is going on to end.")
    ] = False,
    format_: Annotated[str, typer.Option("--format", help="table or json")] = "table",
    url: Url = None,
    token: Token = None,
) -> None:
    """Show a stored preview and how far its apply has got."""
    target = client.load_target(url, token)
    job = client.call(target, "GET", f"/imports/{hid}")
    if wait:
        job = _wait(target, job, quiet=format_ == "json")
        _ended(target, job, as_json=format_ == "json")
        return
    if format_ == "json":
        typer.echo(json.dumps(job, indent=2))
        return
    shown = ("source", "entity", "file_name", "status", "row_count", "rows_done", "applied")
    for name in (*shown, "stale", "failure"):
        if job[name] is not None:
            typer.echo(f"{name}: {job[name]}")
    typer.echo(f"preview: {_counts(job)}")


@imports_.command("apply")
def apply_import(
    hid: Annotated[str, typer.Argument(help="The HID of the stored preview.")],
    skip_rejected: Annotated[
        bool, typer.Option("--skip-rejected", help="Apply the rows that are not rejected.")
    ] = False,
    no_wait: NoWait = False,
    format_: Annotated[str, typer.Option("--format", help="table or json")] = "table",
    url: Url = None,
    token: Token = None,
) -> None:
    """Apply a stored preview of an import or a bulk edit, or resume one that stopped."""
    target = client.load_target(url, token)
    job = client.call(target, "GET", f"/imports/{hid}")
    path = f"/items/bulk-update/{hid}/apply" if job["source"] == "bulk" else f"/imports/{hid}/apply"
    _apply_job(target, path, skip_rejected, as_json=format_ == "json", wait=not no_wait)


@imports_.command("created")
def created(
    hid: Annotated[str, typer.Argument(help="The HID of the import.")],
    format_: Annotated[str, typer.Option("--format", help="table or json")] = "table",
    url: Url = None,
    token: Token = None,
) -> None:
    """List the records an import made, each with what it is now, and then the vendors
    and catalog entries it made because a row named them (P-234)."""
    target = client.load_target(url, token)
    found: list[dict[str, Any]] = []
    while True:
        page = client.call(
            target, "GET", f"/imports/{hid}/created", params={"limit": 1000, "offset": len(found)}
        )
        found += page["items"]
        if not page["items"] or len(found) >= page["total"]:
            break
    if format_ == "json":
        typer.echo(json.dumps({**page, "items": found, "limit": len(found), "offset": 0}, indent=2))
        return
    if found:
        rows = [["row", "kind", "name", "state", "hid"]]
        rows += [
            [str(one["row"]), one["record_type"], one["label"], one["state"], one["record_hid"]]
            for one in found
        ]
        _table(rows)
    else:
        typer.echo("the import made no record", err=True)
    if page["also"]:
        typer.echo("")
        typer.echo("made because a row named them:")
        rows = [["kind", "name", "state", "hid"]]
        rows += [
            [one["record_type"], one["label"], one["state"], one["record_hid"]]
            for one in page["also"]
        ]
        _table(rows)


GROUPS["imports"] = imports_


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
    system: Annotated[
        str | None,
        typer.Option(
            help="A file of items: the external system it was read from, by its HID or "
            "name, whose identifier of each row, external_id, finds its item first."
        ),
    ] = None,
    complete: Annotated[
        bool,
        typer.Option(
            "--complete",
            help="With --system: the file is everything the system reports, and what it "
            "does not name is marked not reported once it is applied whole.",
        ),
    ] = False,
    no_wait: NoWait = False,
    format_: Annotated[str, typer.Option("--format", help="table or json")] = "table",
    url: Url = None,
    token: Token = None,
) -> None:
    """Preview what a file would create and change, and with --apply, do it.

    The server applies it in the background, and the command waits for the end and
    says how far it has got, unless --no-wait is given.
    """
    target = client.load_target(url, token)
    try:
        data = file.read_bytes()
    except OSError as error:
        raise client.fail(f"cannot read {file}: {error.strerror}", 2) from None
    preview = client.call(
        target,
        "POST",
        "/imports/preview",
        params={
            "entity": entity,
            "mode": mode,
            "file_name": file.name,
            "system": system,
            "complete": "true" if complete else None,
        },
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
        wait=not no_wait,
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
    place_codes: Annotated[
        bool,
        typer.Option(
            "--place-codes", help="Write each place by the codes of its site and its own."
        ),
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
        place_codes=place_codes,
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
    no_wait: NoWait = False,
    include_archived: Archived = False,
    include_drafts: Drafts = False,
    format_: Annotated[str, typer.Option("--format", help="table or json")] = "table",
    url: Url = None,
    token: Token = None,
) -> None:
    """Change one item, or with --filter, many: previewed first, applied with --apply.

    The server applies a change in the background, and the command waits for the end
    unless --no-wait is given.
    """
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
        wait=not no_wait,
    )


# --- several retired or deleted at once (P-227, P-228) -------------------------------

# How many one request retires or deletes, at most, as the server takes them.
AT_ONCE = 1000
OUTCOMES = ("retired", "already", "refused", "missing")
NAMED = "Each by its HID, or as the other commands name one."
Yes = Annotated[bool, typer.Option("--yes", help="Go on without asking. For a script.")]


def _hids(target: Target, named: list[str], find: Any, doing: str) -> list[str]:
    """Return the HIDs of the records named, each once: an HID as it is, anything else
    as the server finds it. More than one request takes are refused, and not split: the
    records of one command are judged together, a switch with its power supplies."""
    if len(set(named)) > AT_ONCE:
        raise _too_many(len(set(named)), doing)
    hids = list(
        dict.fromkeys(text if _is_hid(text) else find(target, text)["hid"] for text in named)
    )
    if len(hids) > AT_ONCE:
        raise _too_many(len(hids), doing)
    return hids


def _too_many(given: int, doing: str) -> typer.Exit:
    return client.fail(
        f"at most {AT_ONCE:,} are {doing} by one command, and {given:,} were given: "
        f"name {AT_ONCE:,} or fewer",
        2,
    )


def _sent(target: Target, path: str, hids: list[str], **body: Any) -> dict[str, Any]:
    """Send the HIDs in one request, which judges them together, and return its answer."""
    return client.call(target, "POST", path, {"hids": hids, **body})


def _said(found: list[dict[str, Any]], what: str) -> None:
    for one in found:
        typer.echo(f"{what}: {one['label']}  {one['hid']}")


def _depends(one: dict[str, Any]) -> str:
    return "; ".join(
        f"{tie['record_type']} {tie['label']} ({tie['hid']})" for tie in one["depends_on"]
    )


def _retire_many(path: str, find: Any, plural: str, metavar: str) -> Any:
    def retire(
        records: Annotated[list[str], typer.Argument(metavar=metavar, help=NAMED)],
        format_: Annotated[str, typer.Option("--format", help="table or json")] = "table",
        url: Url = None,
        token: Token = None,
    ) -> None:
        target = client.load_target(url, token)
        done = _sent(target, f"{path}/retire", _hids(target, records, find, "retired"))
        if format_ == "json":
            typer.echo(json.dumps(done, indent=2))
        else:
            _said(done["retired"], "retired")
            # What ran on those, and went with them (P-247).
            _said(done["hosted"], "retired with its host")
            _said(done["already"], "retired already")
            for one in done["refused"]:
                what = f" ({_depends(one)})" if one["depends_on"] else ""
                typer.echo(f"refused: {one['label']}  {one['hid']}: {one['detail']}{what}")
            for hid in done["missing"]:
                typer.echo(f"not found: {hid}")
        counts = [f"{len(done['retired'])} retired", f"{len(done['already'])} retired already"]
        if done["hosted"]:
            counts.insert(1, f"{len(done['hosted'])} with their hosts")
        counts += [f"{len(done['refused'])} refused", f"{len(done['missing'])} not found"]
        if done["refused"] or done["missing"]:
            raise client.fail(", ".join(counts), client.EXIT_INVALID)
        typer.echo(", ".join(counts), err=True)

    retire.__doc__ = (
        f"Retire several {plural} at once, each as its own page retires it. One retired "
        "already is counted, not refused."
    )
    return retire


def _delete_many(path: str, find: Any, plural: str, metavar: str) -> Any:
    def delete(
        records: Annotated[list[str], typer.Argument(metavar=metavar, help=NAMED)],
        reason: Annotated[
            str | None, typer.Option(help="Why they are deleted: kept in the audit trail.")
        ] = None,
        yes: Yes = False,
        dry_run: Annotated[
            bool, typer.Option("--dry-run", help="Say what would be done, and do nothing.")
        ] = False,
        format_: Annotated[str, typer.Option("--format", help="table or json")] = "table",
        url: Url = None,
        token: Token = None,
    ) -> None:
        if not dry_run and not (reason or "").strip():
            raise client.fail("--reason says why they are deleted", 2)
        target = client.load_target(url, token)
        hids = _hids(target, records, find, "deleted")
        # Asked first: what would be deleted, and what refused with what depends on it.
        tried = _sent(target, f"{path}/delete", hids, reason=reason, dry_run=True)
        as_json = format_ == "json"
        if not as_json or dry_run:
            if as_json:
                typer.echo(json.dumps(tried, indent=2))
            else:
                _said(tried["deleted"], "to be deleted" if not dry_run else "would be deleted")
                for one in tried["refused"]:
                    typer.echo(f"refused: {one['label']}  {one['hid']}, depends on {_depends(one)}")
                for hid in tried["missing"]:
                    typer.echo(f"not found: {hid}")
        left_out = len(tried["refused"]) + len(tried["missing"])
        if dry_run:
            if left_out:
                raise client.fail(f"{left_out} would not be deleted", client.EXIT_INVALID)
            return
        going = [one["hid"] for one in tried["deleted"]]
        if not going:
            raise client.fail("none of them can be deleted", client.EXIT_INVALID)
        if not yes:
            typer.confirm(
                f"Delete {len(going)} {plural}? They are removed for good; the audit trail "
                "keeps each as it was.",
                abort=True,
            )
        done = _sent(target, f"{path}/delete", going, reason=reason, dry_run=False)
        if as_json:
            typer.echo(json.dumps(done, indent=2))
        else:
            _said(done["deleted"], "deleted")
            for one in done["refused"]:
                typer.echo(f"refused: {one['label']}  {one['hid']}, depends on {_depends(one)}")
        left_out += len(done["refused"]) + len(done["missing"])
        said = f"{len(done['deleted'])} deleted" + (f", {left_out} not" if left_out else "")
        if left_out:
            raise client.fail(said, client.EXIT_INVALID)
        typer.echo(said, err=True)

    delete.__doc__ = (
        f"Delete {plural} that were a mistake, for an Admin: says what it would do, and "
        "asks. One that another record depends on is refused, naming what."
    )
    return delete


items.command("retire")(_retire_many("/items", find_item, "items", "ITEM..."))
items.command("delete")(_delete_many("/items", find_item, "items", "ITEM..."))
groups.command("retire")(_retire_many("/device-groups", find_group, "device groups", "GROUP..."))
groups.command("delete")(_delete_many("/device-groups", find_group, "device groups", "GROUP..."))


@replacements.command("remove")
def remove_replacement(
    hid: Annotated[str, typer.Argument(help="The HID of the replacement.")],
    reason: Annotated[
        str | None, typer.Option(help="Why it was a mistake: kept in the audit trail.")
    ] = None,
    yes: Yes = False,
    url: Url = None,
    token: Token = None,
) -> None:
    """Remove a replacement that was a mistake, for an Admin: says which, and asks.

    What it handed over, memberships and connections of circuits, stays as it is
    (P-238).
    """
    if not (reason or "").strip():
        raise client.fail("--reason says why the replacement was a mistake", 2)
    target = client.load_target(url, token)
    found = client.call(target, "GET", "/reports/replacements", params={"filter": f"hid:eq:{hid}"})[
        "items"
    ]
    if not found:
        raise client.fail(f"there is no replacement {hid}", client.EXIT_INVALID)
    one = found[0]
    said = (
        f"{_named(one['old_item'])} replaced by {_named(one['new_item'])} "
        f"on {one['replaced_on']} ({one['reason_label']})"
    )
    typer.echo(said)
    if not yes:
        typer.confirm("Remove this replacement? The audit trail keeps it as it was.", abort=True)
    client.call(target, "POST", f"/item-replacements/{hid}/remove", {"reason": reason})
    typer.echo(f"removed: {said}")


@items.command("make-stack")
def make_stack(
    item: Annotated[str, typer.Argument(help="An HID, serial number, asset tag or name.")],
    name: Annotated[
        str | None, typer.Option(help="The stack's name. Left out, the item's own.")
    ] = None,
    member: Annotated[
        list[str] | None,
        typer.Option(
            help="One more member, which takes the stack's name and place as it joins. "
            "Given again for each."
        ),
    ] = None,
    url: Url = None,
    token: Token = None,
) -> None:
    """Make a stack of an item that stands alone, with the item as its first member.

    The stack takes the item's host name, FQDN and addresses, and the location, planned
    location, owner and operator it has of its own, which it has from the stack from
    then on (P-243).
    """
    target = client.load_target(url, token)
    found = find_item(target, item)
    body: dict[str, Any] = {"row_version": found["row_version"]}
    if name is not None:
        body["name"] = name
    if member:
        body["members"] = [
            {"item_hid": find_item(target, text)["hid"], "drop_identity": True} for text in member
        ]
    stack = client.call(target, "POST", f"/items/{found['hid']}/make-stack", body)
    typer.echo(f"made the stack {stack['name']}  {stack['hid']}")
    for one in client.call(target, "GET", f"/device-groups/{stack['hid']}/members")["items"]:
        typer.echo(f"  {one['position']}: {_named(one['item'])}")


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
        lines.append(("support_weight", _weight_shown(record)))
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
        lines += [("link", _link(link)) for link in record["links"]]
        lines.append(("row_version", record["row_version"]))
        for name, value in lines:
            if value is not None:
                typer.echo(f"{name + ':':<21}{value}")

    show.__doc__ = (
        f"Show one {level} with the contacts and the shipping address it has in force, "
        "each with the level it came from."
    )
    return show


def _weight_shown(record: dict[str, Any]) -> str | None:
    """Return the support weight of a place as a person reads it (P-155): a site's in
    force, with the setting it came from or the minimum it was raised to; a region's and
    a location's own."""
    found = (record.get("effective") or {}).get("support_weight")
    if found is None:
        return record.get("support_weight")
    if found["value"] is None:
        return None
    said = found["value"]
    if found["source"] == "setting":
        said += " (default_site_weight)"
    if found["raised_from"] is not None:
        said += f" (raised from {found['raised_from']} to minimum_site_weight)"
    return said


def _link(link: dict[str, Any]) -> str:
    """Return a link as a person reads it: its text and its address, or the address."""
    return f"{link['text']} <{link['url']}>" if link["text"] else link["url"]


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


# --- operators -----------------------------------------------------------------------


def find_operator(target: Target, text: str) -> dict[str, Any]:
    """Return the operator with an HID or a label."""
    if _is_hid(text):
        return client.call(target, "GET", f"/operators/{text}")
    found = client.call(
        target,
        "GET",
        "/operators",
        params={
            "filter": json.dumps({"field": "label", "op": "eq", "value": text}),
            "include_archived": True,
            "include_drafts": True,
            "limit": 2,
        },
    )["items"]
    if not found:
        raise client.fail(f"there is no operator {text}", client.EXIT_INVALID)
    return found[0]


@operators.command("assign")
def assign_operator(
    operator: Annotated[str, typer.Argument(help="A label or an HID.")],
    contact: Annotated[
        str | None, typer.Argument(help="The email address or the HID of the person behind it.")
    ] = None,
    open_: Annotated[
        bool, typer.Option("--open", help="Nobody is behind it for now: an open assignment.")
    ] = False,
    url: Url = None,
    token: Token = None,
) -> None:
    """Put a person behind an operator, or leave it open. Everything the label is on
    follows at once, and none of it is written to."""
    if (contact is None) != open_:
        raise client.fail("name the contact, or say --open", 2)
    target = client.load_target(url, token)
    found = find_operator(target, operator)
    person = None
    if contact is not None:
        key = "hid" if _is_hid(contact) else "email"
        people = client.call(
            target,
            "GET",
            "/contacts",
            params={"filter": json.dumps({"field": key, "op": "eq", "value": contact}), "limit": 2},
        )["items"]
        if len(people) != 1:
            raise client.fail(f"there is no contact {contact}", client.EXIT_INVALID)
        person = people[0]
    changed = client.call(
        target,
        "PATCH",
        f"/operators/{found['hid']}",
        {"row_version": found["row_version"], "contact_hid": person["hid"] if person else None},
    )
    behind = changed["contact"]["name"] if changed["contact"] else "nobody: it is open"
    if changed.get("scope"):
        behind += f", {changed['scope']}"
    typer.echo(f"{changed['label']} is {behind}; it is on {changed['uses']} records of its own")


@operators.command("release")
def release_operator(
    operator: Annotated[str, typer.Argument(help="A label or an HID.")],
    url: Url = None,
    token: Token = None,
) -> None:
    """Release what an operator is on: the label is retired and stands for nothing, and
    each thing it was on has the operator of the next level up, or none."""
    target = client.load_target(url, token)
    found = find_operator(target, operator)
    client.call(
        target, "POST", f"/operators/{found['hid']}/retire", {"row_version": found["row_version"]}
    )
    typer.echo(f"{found['label']} is released; it was on {found['uses']} records of its own")


# --- contracts -----------------------------------------------------------------------

Day = Annotated[str | None, typer.Option(help="A day, as YYYY-MM-DD.")]
COVER_AT_ONCE = 10_000
# The setting that says how many items one request may cover.
ONE_REQUEST = "max_items_per_request"
CONTRACT_TEXTS = (
    "number",
    "starts_on",
    "ends_on",
    "status",
    "support_level",
    "purchase_reference",
    "account_manager",
    "support_contact",
    "support_url",
    "annual_cost",
    "notes",
)


def _one_named(
    target: Target, path: str, field: str, text: str, what: str, also: str | None = None
) -> dict[str, Any]:
    """Return the one record of a list with an HID, or with text in a field, or in
    another field as well."""
    if _is_hid(text):
        return client.call(target, "GET", f"{path}/{text}")
    named: dict[str, Any] = {"field": field, "op": "eq", "value": text}
    if also is not None:
        named = {"or": [named, {"field": also, "op": "eq", "value": text}]}
    found = client.call(
        target,
        "GET",
        path,
        params={
            "filter": json.dumps(named),
            "include_archived": True,
            "include_drafts": True,
            "limit": 20,
        },
    )["items"]
    if len(found) == 1:
        return found[0]
    if not found:
        raise client.fail(f"there is no {what} {text}", client.EXIT_INVALID)
    for one in found:
        typer.echo(f"  {one['hid']}  {one.get('vendor', {}).get('name', '')}", err=True)
    raise client.fail(
        f"more than one {what} answers to {text}: name the one meant by its HID",
        client.EXIT_INVALID,
    )


def find_contract(target: Target, text: str) -> dict[str, Any]:
    """Return the contract with an HID or a number: the number it has, or the one of
    the term that is still to begin."""
    return _one_named(target, "/contracts", "number", text, "contract", also="next_number")


def _period(starts_on: str | None, ends_on: str | None) -> str:
    return f"{starts_on or 'the beginning'} to {ends_on or 'further notice'}"


def _in_force_period(contract: dict[str, Any]) -> str:
    """Return the period a contract has in force: its own, or its agreement's."""
    in_force = contract["effective"]
    return _period(in_force["starts_on"]["value"], in_force["ends_on"]["value"])


def _from_agreement(contract: dict[str, Any], name: str) -> str | None:
    """Return what a contract has in force in a field, and says so where it is not its
    own, or what its own is in place of."""
    found = contract["effective"][name]
    value = found.get("label") or found["value"]
    if value is None:
        return value
    if found["source"] != "own":
        return f"{value} ({found['source']})"
    theirs = found.get("from_agreement_label") or found.get("from_agreement")
    return value if theirs is None else f"{value} (in place of the agreement's {theirs})"


def _term_period(term: dict[str, Any]) -> str:
    """Return the period of an earlier term, saying which of its dates were the agreement's."""

    def one(name: str, blank: str) -> str:
        value = term[name] or blank
        return f"{value} (agreement)" if term.get(f"{name}_source") == "agreement" else value

    return f"{one('starts_on', 'the beginning')} to {one('ends_on', 'further notice')}"


@contracts.command("show")
def show_contract(
    contract: Annotated[str, typer.Argument(help="A number or an HID.")],
    limit: Annotated[int, typer.Option(help="How many of its items are shown.")] = LIMIT,
    format_: Annotated[str, typer.Option("--format", help="table or json")] = "table",
    url: Url = None,
    token: Token = None,
) -> None:
    """Show a contract: what it says, what it has from its agreement, and what it covers."""
    target = client.load_target(url, token)
    found = find_contract(target, contract)
    covered = client.call(
        target,
        "GET",
        f"/contracts/{found['hid']}/coverage",
        params={"limit": min(limit, 1000), "sort": "item.name"},
    )
    terms = client.call(target, "GET", f"/contracts/{found['hid']}/terms")
    if format_ == "json":
        typer.echo(json.dumps({**found, "coverage": covered["items"], "terms": terms}, indent=2))
        return
    lines = [
        ("hid", found["hid"]),
        ("number", found["number"]),
        ("vendor", found["vendor"]["name"]),
        ("agreement", found["agreement"]["name"] if found["agreement"] else None),
        ("reseller", _from_agreement(found, "reseller_hid")),
        ("starts_on", _from_agreement(found, "starts_on")),
        ("ends_on", _from_agreement(found, "ends_on")),
        (
            "status",
            found["status"]
            + (", lapsed" if found["lapsed"] else "")
            + (", ends with its term" if found["ends_with_term"] else "")
            + (
                f", pending {found['renewal_pending_days']} days"
                + (" (overdue)" if found["renewal_overdue"] else "")
                if found["renewal_pending_days"] is not None
                else ""
            ),
        ),
        ("covers today", "yes" if found["covers_today"] else "no"),
        (
            "next term",
            None
            if found["next_term"] is None
            else f"{found['next_term']['number'] or found['number']}, "
            + _period(found["next_term"]["starts_on"], found["next_term"]["ends_on"])
            + (", with the agreement's term" if found["next_term"]["with_agreement"] else ""),
        ),
        (
            "this part since",
            f"{found['part_began_on']}, {found['part_began_by']}"
            if found.get("part_began_on")
            else None,
        ),
        ("support_level", _from_agreement(found, "support_level")),
        ("purchase_reference", found["purchase_reference"]),
        ("account_manager", _from_agreement(found, "account_manager")),
        ("support_contact", _from_agreement(found, "support_contact")),
        *_contacts_in_force(found),
        ("support_url", _from_agreement(found, "support_url")),
        ("annual_cost", found["annual_cost"]),
        ("notes", found["notes"]),
        ("tags", ", ".join(found["tags"]) or None),
        ("record_status", found["record_status"]),
        ("items covered", str(found["covered_items"])),
        ("items in scope", str(found["items_in_scope"])),
    ]
    for name, value in lines:
        if value not in (None, ""):
            typer.echo(f"{name + ':':<21}{value}")
    for term in terms:
        typer.echo(
            f"{'earlier term:':<21}{term['number']}, {_term_period(term)}"
            + (f", {term['purchase_reference']}" if term["purchase_reference"] else "")
            + f"; {term['began_on']} to {term['ended_on']}, began by {term['began_by']}"
            + (", in an agreement" if term["agreement_hid"] else ", by itself")
        )
    if covered["items"]:
        typer.echo("")
        rows = [["item", "pid", "serial_number", "starts_on", "ends_on", "in_force"]]
        for one in covered["items"]:
            rows.append(
                [
                    _named(one["item"]),
                    one["item"]["pid"] or "",
                    one["item"]["serial_number"] or "",
                    one["effective_starts_on"] or "",
                    one["effective_ends_on"] or "",
                    "yes" if one["in_force"] else "no",
                ]
            )
        _table(rows)
        if covered["total"] > len(covered["items"]):
            typer.echo(
                f"the first {len(covered['items'])} of {covered['total']} are shown; "
                "--limit shows more",
                err=True,
            )


@contracts.command("set")
def set_contract(
    contract: Annotated[str, typer.Argument(help="A number or an HID.")],
    changes: Annotated[
        list[str],
        typer.Argument(
            help="field=value to set and field= to clear. agreement= and reseller= take a "
            "name: agreement='Cisco Enterprise Agreement' rolls the contract into it."
        ),
    ],
    url: Url = None,
    token: Token = None,
) -> None:
    """Change a contract. Every item under it shows the change at once, and none of
    them is written to."""
    target = client.load_target(url, token)
    found = find_contract(target, contract)
    body: dict[str, Any] = {"row_version": found["row_version"]}
    for argument in changes:
        name, equals, value = argument.partition("=")
        name, value = name.strip(), value.strip()
        if not equals or not name:
            raise client.fail(f"{argument!r} is not field=value", 2)
        if name == "agreement":
            body["agreement_hid"] = (
                _one_named(target, "/agreements", "name", value, "agreement")["hid"]
                if value
                else None
            )
        elif name == "reseller":
            body["reseller_hid"] = (
                _one_named(target, "/vendors", "name", value, "vendor")["hid"] if value else None
            )
        elif name in CONTRACT_TEXTS:
            body[name] = value or None
        else:
            known = ", ".join(("agreement", "reseller", *CONTRACT_TEXTS))
            raise client.fail(f"{name} is not a field of a contract: one of {known}", 2)
    changed = client.call(target, "PATCH", f"/contracts/{found['hid']}", body)
    within = f" in {changed['agreement']['name']}" if changed["agreement"] else ""
    typer.echo(
        f"{changed['number']}{within}: "
        f"{_in_force_period(changed)}, "
        f"{changed['items_in_scope']} items in scope"
    )


def _renewed(found: dict[str, Any], renewed: dict[str, Any], called: str, follow: str) -> None:
    """Say what a renewal did: in force at once, kept as the next term, or withdrawn."""
    waiting = renewed["next_term"]
    if waiting is not None:
        number = f" as {waiting['number']}" if waiting["number"] else ""
        typer.echo(
            f"{called} renews{number} on {waiting['starts_on']}, to "
            f"{waiting['ends_on'] or 'further notice'}; until then it runs on as it is, "
            f"{follow}"
        )
    elif found["next_term"] is not None and all(
        renewed.get(name) == found.get(name) for name in ("number", "starts_on", "ends_on")
    ):
        typer.echo(f"{called}: the term that was to begin is withdrawn")
    else:
        typer.echo(f"{called} is now {renewed.get('number') or called}, {follow}")
        if found["next_term"] is not None:
            typer.echo("the term that was to begin is superseded by it", err=True)


def _renewal(
    number: str | None,
    from_: str | None,
    to: str | None,
    purchase_reference: str | None,
    annual_cost: str | None,
    withdraw: bool,
    row_version: int,
) -> dict[str, Any]:
    body: dict[str, Any] = {"row_version": row_version}
    if withdraw:
        return {**body, "withdraw": True}
    for name, value in (
        ("number", number),
        ("starts_on", from_),
        ("ends_on", to),
        ("purchase_reference", purchase_reference),
        ("annual_cost", annual_cost),
    ):
        if value is not None:
            body[name] = value
    return body


Number = Annotated[str | None, typer.Option(help="The new number.")]
From = Annotated[str | None, typer.Option("--from", help="The first day of the new period.")]
To = Annotated[str | None, typer.Option(help="The last day of the new period.")]
Reference = Annotated[
    str | None, typer.Option(help="The request or tracking number of the new term.")
]
Cost = Annotated[str | None, typer.Option(help="What the new term costs a year.")]
Withdraw = Annotated[
    bool, typer.Option("--withdraw", help="Withdraw the term that is still to begin.")
]


@contracts.command("renew")
def renew_contract(
    contract: Annotated[str, typer.Argument(help="A number or an HID.")],
    number: Number = None,
    from_: From = None,
    to: To = None,
    purchase_reference: Reference = None,
    annual_cost: Cost = None,
    withdraw: Withdraw = False,
    url: Url = None,
    token: Token = None,
) -> None:
    """Renew a contract: its new number, its new period, or both, in one change. Every
    item in scope follows, and none of them is written to. A period that begins after
    today is kept as the next term, and the present one runs on until then."""
    target = client.load_target(url, token)
    found = find_contract(target, contract)
    body = _renewal(
        number, from_, to, purchase_reference, annual_cost, withdraw, found["row_version"]
    )
    renewed = client.call(target, "POST", f"/contracts/{found['hid']}/renew", body)
    scope = renewed["items_in_scope"]
    follow = (
        f"{_in_force_period(renewed)}; {scope} {'item follows' if scope == 1 else 'items follow'}"
    )
    _renewed(found, renewed, found["number"], follow)


@agreements.command("show")
def show_agreement(
    agreement: Annotated[str, typer.Argument(help="A name or an HID.")],
    format_: Annotated[str, typer.Option("--format", help="table or json")] = "table",
    url: Url = None,
    token: Token = None,
) -> None:
    """Show a support agreement: what it says, how many contracts it groups, and the
    terms it had before, its purchase history."""
    target = client.load_target(url, token)
    found = _one_named(target, "/agreements", "name", agreement, "agreement")
    terms = client.call(target, "GET", f"/agreements/{found['hid']}/terms")
    if format_ == "json":
        typer.echo(json.dumps({**found, "terms": terms}, indent=2))
        return
    lines = [
        ("hid", found["hid"]),
        ("name", found["name"]),
        ("number", found["number"]),
        ("vendor", found["vendor"]["name"]),
        ("period", _period(found["starts_on"], found["ends_on"])),
        ("status", found["status"] + (", lapsed" if found["lapsed"] else "")),
        (
            "next term",
            None
            if found["next_term"] is None
            else (f"{found['next_term']['number']}, " if found["next_term"]["number"] else "")
            + _period(found["next_term"]["starts_on"], found["next_term"]["ends_on"]),
        ),
        ("support_level", found["support_level"]),
        ("purchase_reference", found["purchase_reference"]),
        ("account_manager", found["account_manager"]),
        ("support_contact", found["support_contact"]),
        *_contacts_in_force(found),
        ("support_url", found["support_url"]),
        ("annual_cost", found["annual_cost"]),
        ("contracts", str(found["contracts"])),
    ]
    for name, value in lines:
        if value not in (None, ""):
            typer.echo(f"{name + ':':<21}{value}")
    for term in terms:
        typer.echo(
            f"{'earlier term:':<21}{term['number'] or '(no number)'}, "
            f"{_period(term['starts_on'], term['ends_on'])}"
            + (f", {term['purchase_reference']}" if term["purchase_reference"] else "")
        )


def _members(target: Target, agreement_hid: str, given: list[str]) -> list[dict[str, Any]]:
    """Return what `--member` says of each contract that shares an agreement's period:
    `CON-1=same`, `CON-1=new:CON-2` or `CON-1=ends`, the contract by number or HID."""
    asked = []
    for one in given:
        contract, _, choice = one.partition("=")
        if not contract or (choice not in ("same", "ends") and not choice.startswith("new:")):
            raise typer.BadParameter(
                f"{one}: write CONTRACT=same, CONTRACT=new:NUMBER or CONTRACT=ends",
                param_hint="--member",
            )
        if _is_hid(contract):
            hid = contract
        else:
            named = {
                "and": [
                    {"field": "number", "op": "eq", "value": contract},
                    {"field": "agreement_hid", "op": "eq", "value": agreement_hid},
                ]
            }
            found = client.call(
                target, "GET", "/contracts", params={"filter": json.dumps(named), "limit": 2}
            )["items"]
            if len(found) != 1:
                raise client.fail(
                    f"there is no one contract {contract} in this agreement", client.EXIT_INVALID
                )
            hid = found[0]["hid"]
        member: dict[str, Any] = {"contract_hid": hid, "renewal": choice}
        if choice.startswith("new:"):
            member |= {"renewal": "new_number", "number": choice.removeprefix("new:")}
        asked.append(member)
    return asked


Member = Annotated[
    list[str] | None,
    typer.Option(
        "--member",
        help="What a contract that shares the agreement's period does: CONTRACT=same, "
        "CONTRACT=new:NUMBER or CONTRACT=ends. Again for each; a contract left out keeps "
        "its number.",
    ),
]


@agreements.command("renew")
def renew_agreement(
    agreement: Annotated[str, typer.Argument(help="A name or an HID.")],
    number: Number = None,
    from_: From = None,
    to: To = None,
    purchase_reference: Reference = None,
    annual_cost: Cost = None,
    withdraw: Withdraw = False,
    member: Member = None,
    url: Url = None,
    token: Token = None,
) -> None:
    """Renew a support agreement: its new period, in one change. The contracts that
    share its period follow it, each under its number, with a new number that begins
    with the new term, or let go with the present term, and the items under them."""
    target = client.load_target(url, token)
    found = _one_named(target, "/agreements", "name", agreement, "agreement")
    body = _renewal(
        number, from_, to, purchase_reference, annual_cost, withdraw, found["row_version"]
    )
    if member:
        body["members"] = _members(target, found["hid"], member)
    renewed = client.call(target, "POST", f"/agreements/{found['hid']}/renew", body)
    for one in renewed["members"]:
        if one["renewal"] != "same" or one["left_behind"]:
            said = {"new_number": f"takes {one['number']}", "ends": "ends with this term"}
            left = f", {one['left_behind']} left behind" if one["left_behind"] else ""
            typer.echo(f"  {one['number']}: {said.get(one['renewal'], 'keeps its number')}{left}")
    follow = (
        f"{_period(renewed['starts_on'], renewed['ends_on'])}; "
        f"{renewed['contracts']} "
        f"{'contract is' if renewed['contracts'] == 1 else 'contracts are'} in it"
    )
    _renewed(found, {**renewed, "number": renewed["name"]}, found["name"], follow)


# --- the contacts of agreements and contracts ----------------------------------------

Role = Annotated[str, typer.Option("--role", help="account_manager or support_contact.")]


def _contacts_in_force(record: dict[str, Any]) -> list[tuple[str, str]]:
    """Return a line for each contact record in force, by role: who, how to reach them,
    and where it came from when that is the agreement."""
    lines = []
    for name in ("account_managers", "support_contacts"):
        in_force = record["effective"][name]
        source = " (agreement)" if in_force["source"] == "agreement" else ""
        for named in in_force["value"]:
            contact = named["contact"]
            reached = " ".join(part for part in (contact["email"], contact["phone"]) if part)
            retired = " (retired)" if contact["record_status"] == "retired" else ""
            lines.append((name, f"{contact['name']} {reached}".rstrip() + retired + source))
    return lines


def _find_contact(target: Target, text: str) -> dict[str, Any]:
    """Return the contact a command names: by its HID, its email address or a name that
    one contact alone has."""
    return _one_named(target, "/contacts", "email", text, "contact", also="name")


def _naming(
    group: typer.Typer, what: str, known_by: str, find: Any, called: str, note: str = ""
) -> None:
    """Add to a group the commands that name a contact for an agreement, a contract or
    a vendor, and that remove one. `note` says who else has the contact named."""
    path = f"/{what}s"

    def add(
        record: Annotated[str, typer.Argument(help=f"The {what}: {known_by}.")],
        contact: Annotated[
            str, typer.Argument(help="The contact: an email address, a name or an HID.")
        ],
        role: Role,
        priority: Annotated[
            int | None, typer.Option(help="Its place in the list, from 1. Left out, the last.")
        ] = None,
        url: Url = None,
        token: Token = None,
    ) -> None:
        target = client.load_target(url, token)
        found = find(target, record)
        person = _find_contact(target, contact)
        body: dict[str, Any] = {"contact_hid": person["hid"], "role": role}
        if priority is not None:
            body["priority"] = priority
        named = client.call(target, "POST", f"{path}/{found['hid']}/contacts", body)
        typer.echo(
            f"{found[called]} names {named['contact']['name']} as {named['role']}, "
            f"number {named['priority']} of the list"
        )

    def remove(
        record: Annotated[str, typer.Argument(help=f"The {what}: {known_by}.")],
        contact: Annotated[
            str, typer.Argument(help="The contact: an email address, a name or an HID.")
        ],
        role: Role,
        url: Url = None,
        token: Token = None,
    ) -> None:
        target = client.load_target(url, token)
        found = find(target, record)
        person = _find_contact(target, contact)
        named = [
            one
            for one in found["contacts"]
            if one["contact_hid"] == person["hid"] and one["role"] == role
        ]
        if not named:
            raise client.fail(
                f"{found[called]} does not name {person['name']} as {role}", client.EXIT_INVALID
            )
        client.call(target, "DELETE", f"{path}/{found['hid']}/contacts/{named[0]['hid']}")
        typer.echo(f"{found[called]} no longer names {person['name']} as {role}")

    add.__doc__ = (
        f"Name a contact record for a {what} as an account manager or a support contact. "
        + (
            note
            or (
                "Once a contract names anybody in a role, it has its own in place of its "
                "agreement's."
                if what == "contract"
                else "Each contract in it that names nobody of its own in the role has it."
            )
        )
    )
    remove.__doc__ = (
        f"Remove a contact that was named for a {what} by mistake. The audit trail keeps "
        "what it was."
    )
    group.command("add-contact")(add)
    group.command("remove-contact")(remove)


def _find_agreement(target: Target, text: str) -> dict[str, Any]:
    return _one_named(target, "/agreements", "name", text, "agreement")


_naming(agreements, "agreement", "a name or an HID", _find_agreement, "name")
_naming(contracts, "contract", "a number or an HID", find_contract, "number")


# --- the contacts of carriers and of circuits (P-149) --------------------------------


def _find_vendor(target: Target, text: str) -> dict[str, Any]:
    return _one_named(target, "/vendors", "name", text, "vendor")


_naming(
    vendors,
    "vendor",
    "a name or an HID",
    _find_vendor,
    "name",
    note="Each circuit of the carrier that names nobody of its own in the role has it.",
)

CircuitRole = Annotated[
    str,
    typer.Option(
        "--role",
        help="account_manager or support_contact; with --side, a role of the contact_role list.",
    ),
]
Side = Annotated[
    str | None,
    typer.Option(help="a or z, for a site contact of that side. Left out, one of the carrier's."),
]


def _on_side(side: str | None) -> str:
    return f" on the {side.upper()} side" if side else ""


@circuits.command("add-contact")
def add_circuit_contact(
    circuit: Annotated[
        str, typer.Argument(help="The circuit: its enterprise ID, a name or an HID.")
    ],
    contact: Annotated[
        str, typer.Argument(help="The contact: an email address, a name or an HID.")
    ],
    role: CircuitRole,
    side: Side = None,
    priority: Annotated[
        int | None, typer.Option(help="Its place in the list, from 1. Left out, the last.")
    ] = None,
    url: Url = None,
    token: Token = None,
) -> None:
    """Name a contact record for a circuit. With no --side, as an account manager or a
    support contact, in place of its carrier's in that role; with --side a or z, as a
    site contact of that side, in place of what its location gives in that role."""
    target = client.load_target(url, token)
    found = find_circuit(target, circuit)
    person = _find_contact(target, contact)
    body: dict[str, Any] = {"contact_hid": person["hid"], "role": role}
    if side is not None:
        body["side"] = side
    if priority is not None:
        body["priority"] = priority
    named = client.call(target, "POST", f"/circuits/{found['hid']}/contacts", body)
    typer.echo(
        f"{found['name']} names {named['contact']['name']} as {named['role']}"
        f"{_on_side(named['side'])}, number {named['priority']} of the list"
    )


@circuits.command("remove-contact")
def remove_circuit_contact(
    circuit: Annotated[
        str, typer.Argument(help="The circuit: its enterprise ID, a name or an HID.")
    ],
    contact: Annotated[
        str, typer.Argument(help="The contact: an email address, a name or an HID.")
    ],
    role: CircuitRole,
    side: Side = None,
    url: Url = None,
    token: Token = None,
) -> None:
    """Remove a contact that was named for a circuit by mistake. The audit trail keeps
    what it was. A circuit that names nobody left in a role has its carrier's, or its
    location's, again."""
    target = client.load_target(url, token)
    found = find_circuit(target, circuit)
    person = _find_contact(target, contact)
    listed = client.call(
        target, "GET", f"/circuits/{found['hid']}/contacts", params={"limit": 1000}
    )["items"]
    named = [
        one
        for one in listed
        if one["contact_hid"] == person["hid"] and one["role"] == role and one["side"] == side
    ]
    if not named:
        raise client.fail(
            f"{found['name']} does not name {person['name']} as {role}{_on_side(side)}",
            client.EXIT_INVALID,
        )
    client.call(target, "DELETE", f"/circuits/{found['hid']}/contacts/{named[0]['hid']}")
    typer.echo(f"{found['name']} no longer names {person['name']} as {role}{_on_side(side)}")


@contracts.command("cover")
def cover(
    contract: Annotated[str, typer.Argument(help="A number or an HID.")],
    named: Annotated[
        list[str] | None,
        typer.Argument(help="Items, each by its HID, serial number, asset tag or name."),
    ] = None,
    filter_: Filter = None,
    from_: Annotated[str | None, typer.Option("--from", help="Left out, the contract's.")] = None,
    to: Annotated[str | None, typer.Option(help="Left out, the contract's.")] = None,
    apply: Annotated[bool, typer.Option("--apply", help="Cover them.")] = False,
    include_archived: Archived = False,
    include_drafts: Drafts = False,
    url: Url = None,
    token: Token = None,
) -> None:
    """Put items under a contract: the items named, or those of a filter. A preview
    unless --apply is given."""
    if bool(named) == (filter_ is not None):
        raise client.fail("name the items, or the rows with --filter", 2)
    target = client.load_target(url, token)
    found = find_contract(target, contract)
    hids: list[str] = []
    if named:
        hids = [find_item(target, text)["hid"] for text in named]
    else:
        while True:
            page = client.call(
                target,
                "GET",
                "/items",
                params={
                    "filter": filter_,
                    "fields": "hid",
                    "limit": 1000,
                    "offset": len(hids),
                    "include_archived": include_archived,
                    "include_drafts": include_drafts,
                },
            )
            hids += [item["hid"] for item in page["items"]]
            if not page["items"] or len(hids) >= page["total"]:
                break
            if len(hids) > COVER_AT_ONCE:
                raise client.fail(
                    f"more than {COVER_AT_ONCE} items match: narrow the filter", client.EXIT_INVALID
                )
    period = _period(
        from_ or found["effective"]["starts_on"]["value"],
        to or found["effective"]["ends_on"]["value"],
    )
    if not hids:
        raise client.fail("no item matches", client.EXIT_INVALID)
    if not apply:
        typer.echo(f"{len(hids)} items would be covered by {found['number']}, {period}")
        typer.echo("nothing was changed; add --apply to cover them", err=True)
        return
    dates = {name: value for name, value in (("starts_on", from_), ("ends_on", to)) if value}
    covered = 0
    # A request covers as many as the setting max_items_per_request says, and each
    # request is whole or not at all: so where a later one is refused, what the earlier
    # ones covered stays covered, and that is said, with how to go on.
    in_one = int(_setting(target, ONE_REQUEST, settings.SPECS[ONE_REQUEST].default))
    for start in range(0, len(hids), in_one):
        try:
            made = client.call(
                target,
                "POST",
                f"/contracts/{found['hid']}/coverage",
                {"items": [{"item_hid": hid, **dates} for hid in hids[start : start + in_one]]},
                timeout=SLOW,
            )
        except typer.Exit:
            if covered:
                typer.echo(
                    f"{covered} of {len(hids)} items are covered by {found['number']}, and the "
                    f"other {len(hids) - covered} are not: put right what was refused, and "
                    f"cover the rest with --filter 'contract.hid:ne:{found['hid']}' added",
                    err=True,
                )
            raise
        covered += len(made)
    typer.echo(f"{covered} items are covered by {found['number']}, {period}")


# --- purchases -----------------------------------------------------------------------


def find_line(target: Target, text: str) -> dict[str, Any]:
    """Return the purchase line with an HID, or named as `RITM0012345/2`."""
    if _is_hid(text):
        return client.call(target, "GET", f"/purchase-lines/{text}")
    reference, slash, number = text.rpartition("/")
    if not slash or not number.strip().isdigit():
        raise client.fail(f"{text} is not a line: a line is named as RITM0012345/2", 2)
    found = client.call(
        target,
        "GET",
        "/purchase-lines",
        params={
            "filter": json.dumps(
                {
                    "and": [
                        {"field": "request.reference", "op": "eq", "value": reference.strip()},
                        {"field": "line", "op": "eq", "value": int(number)},
                    ]
                }
            ),
            "limit": 2,
        },
    )["items"]
    if len(found) != 1:
        raise client.fail(f"there is no purchase line {text}", client.EXIT_INVALID)
    return found[0]


@purchases.command("show")
def show_purchase(
    request: Annotated[str, typer.Argument(help="A reference or an HID.")],
    format_: Annotated[str, typer.Option("--format", help="table or json")] = "table",
    url: Url = None,
    token: Token = None,
) -> None:
    """Show a purchase request and its lines, with what is still to come on each."""
    target = client.load_target(url, token)
    found = _one_named(target, "/purchase-requests", "reference", request, "purchase request")
    if format_ == "json":
        typer.echo(json.dumps(found, indent=2))
        return
    for name in ("hid", "reference", "requested_on", "status", "notes"):
        if found[name] not in (None, ""):
            typer.echo(f"{name + ':':<21}{found[name]}")
    typer.echo(f"{'still to come:':<21}{found['pending_quantity']} of {found['quantity']}")
    if found["lines"]:
        typer.echo("")
        rows = [
            [
                "line",
                "vendor",
                "pid",
                "part_number",
                "quantity",
                "received",
                "pending",
                "destination",
                "expected_on",
            ]
        ]
        for line in found["lines"]:
            site = line["destination_site"]
            # A line with no model is not tracked: what procurement gave is all there is.
            model = line["catalog"] or {"vendor": "", "pid": "(not tracked)"}
            rows.append(
                [
                    line["name"],
                    model["vendor"],
                    model["pid"],
                    line["part_number"] or "",
                    str(line["quantity"]),
                    str(line["received_quantity"]),
                    str(line["pending_quantity"]),
                    site["path"] if site else "",
                    line["expected_on"] or "",
                ]
            )
        _table(rows)


@purchases.command("receive")
def receive(
    line: Annotated[str, typer.Argument(help="A line, as RITM0012345/2, or its HID.")],
    serial: Annotated[
        list[str] | None, typer.Option(help="The serial number of an item that arrived.")
    ] = None,
    asset_tag: Annotated[
        list[str] | None, typer.Option(help="The asset tag of an item that arrived.")
    ] = None,
    name: Annotated[
        list[str] | None, typer.Option(help="The name of an item that arrived.")
    ] = None,
    location: Annotated[
        str | None, typer.Option(help="Where they were put: the path or the HID of a location.")
    ] = None,
    on: Annotated[str | None, typer.Option(help="The day they arrived. Left out, today.")] = None,
    count: Annotated[
        int,
        typer.Option(
            help="How many more arrived that nothing is known of yet: named for the line."
        ),
    ] = 0,
    url: Url = None,
    token: Token = None,
) -> None:
    """Receive items on a purchase line: one --serial, --asset-tag or --name for each
    item that arrived, and --count for those nothing is known of yet. Each is created
    in Delivered, of the line's model."""
    arrived = [
        *({"serial_number": value} for value in serial or []),
        *({"asset_tag": value} for value in asset_tag or []),
        *({"name": value} for value in name or []),
    ]
    if not arrived and count <= 0:
        raise client.fail(
            "say what arrived: --serial, --asset-tag or --name for each item, or --count", 2
        )
    target = client.load_target(url, token)
    found = find_line(target, line)
    body: dict[str, Any] = {
        "row_version": found["row_version"],
        "items": arrived,
        "quantity": count,
    }
    if on is not None:
        body["delivered_on"] = on
    if location is not None:
        body["location_hid"] = find_place(target, location, "location")["hid"]
    received = client.call(target, "POST", f"/purchase-lines/{found['hid']}/receive", body)
    typer.echo(
        f"{len(received['items'])} items received on {received['name']}; "
        f"{received['pending_quantity']} of {received['quantity']} are still to come"
    )


# --- the portfolio of a vendor --------------------------------------------------------

HELD = ("items", "component_count", "support_weight", "est_value", "annual_support_cost")
PORTFOLIO_COLUMNS = (
    "vendor,pid,model_name,kind,type,name,hostname,serial_number,asset_tag,lifecycle_state,"
    "site,covered,covered_until,contracts,ldos,support_weight,annual_support_cost"
)


@vendors.command("portfolio")
def portfolio(
    vendor: Annotated[str, typer.Argument(help="A name or an HID.")],
    format_: Annotated[str, typer.Option("--format", help="table, csv or json")] = "table",
    output: Output = None,
    include_archived: Archived = False,
    include_drafts: Drafts = False,
    url: Url = None,
    token: Token = None,
) -> None:
    """Show everything from one vendor: the totals, the four kinds and the models. As
    csv or json, the items of the vendor, one row each, with their cover: the working
    list for a renewal."""
    _checked_format(format_)
    target = client.load_target(url, token)
    found = _one_named(target, "/vendors", "name", vendor, "vendor")
    view = {"include_archived": include_archived, "include_drafts": include_drafts}
    held = client.call(target, "GET", f"/vendors/{found['hid']}/portfolio", params=view)
    if format_ != "table":
        _export(
            target,
            "items",
            format_=format_,
            filter_=json.dumps(held["filter"]),
            sort="catalog.pid,name",
            columns=PORTFOLIO_COLUMNS,
            output=output,
            **view,
        )
        return
    totals = held["totals"]
    typer.echo(f"{'vendor:':<21}{held['vendor']['name']}")
    for name in HELD:
        typer.echo(f"{name + ':':<21}{totals[name]}")
    typer.echo(f"{'covered:':<21}{totals['covered']} of {totals['covered'] + totals['uncovered']}")
    for agreement in held["agreements"]:
        typer.echo(
            f"{'agreement:':<21}{agreement['name']}, "
            f"{_period(agreement['starts_on'], agreement['ends_on'])}, "
            f"{agreement['contracts']} contracts"
        )
    for contract in held["contracts"]:
        typer.echo(
            f"{'contract:':<21}{contract['number']}, "
            f"{_in_force_period(contract)}, "
            f"{contract['covered_items']} items"
        )
    typer.echo("")
    rows = [["kind", *HELD, "covered"]]
    for kind in held["kinds"]:
        rows.append([kind["kind"], *(str(kind[name]) for name in HELD), str(kind["covered"])])
    _table(rows)
    if held["models"]:
        typer.echo("")
        rows = [["pid", "kind", "items", "covered", "covered_until", "ldos", "annual_support_cost"]]
        for model in held["models"]:
            rows.append(
                [
                    model["pid"],
                    model["kind"],
                    str(model["items"]),
                    str(model["covered"]),
                    model["covered_until"] or "",
                    model["ldos"] or "",
                    str(model["annual_support_cost"]),
                ]
            )
        _table(rows)


# --- the reports that look ahead ------------------------------------------------------

SECTION_COLUMNS = ("name", "pid", "serial_number", "lifecycle_state", "site")


def _section_rows(found: dict[str, Any], extra: str) -> list[list[str]]:
    """Return the items of a section of a report as rows, with one column of its own."""
    rows = [[*SECTION_COLUMNS, extra]]
    for item in found["items"]:
        effective = item["effective"]
        rows.append(
            [
                _shown_name(item),
                item["catalog"]["pid"] if item["catalog"] else "",
                item["serial_number"] or "",
                effective["lifecycle_state"]["value"] or "",
                effective["location_hid"].get("site") or "",
                str(effective[extra]["value"] if extra in effective else item[extra] or ""),
            ]
        )
    return rows


def _all_of_section(target: Target, path: str, params: dict[str, Any]) -> dict[str, Any]:
    """Return a report with every item of the section that is asked for."""
    found = client.call(target, "GET", path, params={**params, "limit": 1000})
    while found["section"] and len(found["items"]) < found["total"]:
        more = client.call(
            target, "GET", path, params={**params, "limit": 1000, "offset": len(found["items"])}
        )
        if not more["items"]:
            break
        found["items"] += more["items"]
    return found


@report.command("coverage")
def coverage_report(
    filter_: Filter = None,
    section: Annotated[
        str | None,
        typer.Option(
            help="List the items of one: uncovered, out_of_service, expiring, overlapping or "
            "renewal_pending."
        ),
    ] = None,
    within_days: Annotated[
        int | None, typer.Option(help="How far ahead cover that runs out is looked for.")
    ] = None,
    include_drafts: Drafts = False,
    format_: Annotated[str, typer.Option("--format", help="table, csv or json")] = "table",
    output: Output = None,
    url: Url = None,
    token: Token = None,
) -> None:
    """Say what contracts cover today: what is in service with no cover, what is covered
    though out of service, and what runs out soon."""
    _checked_format(format_)
    target = client.load_target(url, token)
    params = {
        "filter": filter_,
        "section": section,
        "within_days": within_days,
        "include_drafts": include_drafts,
    }
    found = _all_of_section(target, "/reports/coverage", params)
    if format_ == "json":
        typer.echo(json.dumps(found, indent=2))
        return
    if section is not None:
        _rows(format_, output, _section_rows(found, "covered_until"))
        return
    names = (
        "in_service",
        "covered",
        "uncovered",
        "out_of_service",
        "expiring",
        "overlapping",
        "renewal_pending",
    )
    if format_ == "csv":
        _rows(format_, output, [list(names), [str(found["totals"][name]) for name in names]])
        return
    typer.echo(f"{'as of:':<21}{found['as_of']}")
    for name in names:
        note = f" (within {found['within_days']} days)" if name == "expiring" else ""
        typer.echo(f"{name + ':':<21}{found['totals'][name]}{note}")
    typer.echo(f"{'lapsed contracts:':<21}{found['lapsed_contracts']['count']}")


RENEWAL_LISTS = (
    "ending",
    "lapsed",
    "renewal_pending",
    "overdue",
    "ends_with_term",
    "overlapping",
)


def renewals_worklist(
    filter_: Annotated[
        str | None,
        typer.Option("--filter", help="A filter of the contract list, such as vendor:eq:Cisco."),
    ] = None,
    section: Annotated[
        str | None,
        typer.Option(
            help="List the rows of one: ending, lapsed, renewal_pending, overdue, "
            "ends_with_term or overlapping."
        ),
    ] = None,
    within_days: Annotated[
        int | None,
        typer.Option(help="How far ahead a contract counts as ending. Left out, the setting."),
    ] = None,
    include_drafts: Drafts = False,
    format_: Annotated[str, typer.Option("--format", help="table, csv or json")] = "table",
    output: Output = None,
    url: Url = None,
    token: Token = None,
) -> None:
    """Say what must be acted on to keep the cover going: the contracts that end soon,
    those that have lapsed, those whose renewal is pending and how long, and the items
    under more than one contract, each under its vendor and its agreement."""
    _checked_format(format_)
    target = client.load_target(url, token)
    params = {
        "filter": filter_,
        "section": section,
        "within_days": within_days,
        "include_drafts": include_drafts,
    }
    found = client.call(target, "GET", "/reports/renewals", params={**params, "limit": 1000})
    rows_of = "items" if section == "overlapping" else "contracts"
    while section and len(found[rows_of]) < found["total"]:
        more = client.call(
            target,
            "GET",
            "/reports/renewals",
            params={**params, "limit": 1000, "offset": len(found[rows_of])},
        )
        if not more[rows_of]:
            break
        found[rows_of] += more[rows_of]
    if format_ == "json":
        typer.echo(json.dumps(found, indent=2))
        return
    if section == "overlapping":
        _rows(format_, output, _section_rows(found, "contract_count"))
        return
    if section is not None:
        rows = [["number", "vendor", "agreement", "ends_on", "status", "pending_days", "items"]]
        for contract in found["contracts"]:
            rows.append(
                [
                    contract["number"],
                    contract["vendor"]["name"],
                    (contract["agreement"] or {}).get("name") or "",
                    contract["effective"]["ends_on"]["value"] or "",
                    contract["status"] + (" (overdue)" if contract["renewal_overdue"] else ""),
                    ""
                    if contract["renewal_pending_days"] is None
                    else str(contract["renewal_pending_days"]),
                    str(contract["covered_items"]),
                ]
            )
        _rows(format_, output, rows)
        return
    rows = [["vendor", "agreement", *RENEWAL_LISTS]]
    for group in found["groups"]:
        rows.append(
            [
                group["vendor"],
                group["agreement"] or "(by itself)",
                *(str(group["counts"][name]) for name in RENEWAL_LISTS),
            ]
        )
    rows.append(["all", "", *(str(found["totals"][name]) for name in RENEWAL_LISTS)])
    if format_ == "table":
        typer.echo(
            f"as of {found['as_of']}: ending within {found['within_days']} days, "
            f"overdue after {found['overdue_after']} days pending"
        )
    _rows(format_, output, rows)


@report.command("end-of-life")
def end_of_life_report(
    filter_: Filter = None,
    date_: Annotated[
        str | None,
        typer.Option(
            "--date",
            help="end_of_sale, end_of_sw_support, end_of_hw_support or ldos. Left out, the "
            "setting end_of_life_date.",
        ),
    ] = None,
    section: Annotated[
        str | None, typer.Option(help="List the items of one: past or approaching.")
    ] = None,
    within_days: Annotated[
        int | None, typer.Option(help="How far ahead a date counts as approaching.")
    ] = None,
    include_archived: Archived = False,
    include_drafts: Drafts = False,
    format_: Annotated[str, typer.Option("--format", help="table, csv or json")] = "table",
    output: Output = None,
    url: Url = None,
    token: Token = None,
) -> None:
    """Count the items past and approaching each end-of-life date, and those of one date
    by fiscal year."""
    _checked_format(format_)
    target = client.load_target(url, token)
    params = {
        "filter": filter_,
        "date": date_,
        "section": section,
        "within_days": within_days,
        "include_archived": include_archived,
        "include_drafts": include_drafts,
    }
    found = _all_of_section(target, "/reports/end-of-life", params)
    if format_ == "json":
        typer.echo(json.dumps(found, indent=2))
        return
    if section is not None:
        _rows(format_, output, _section_rows(found, found["date"]))
        return
    rows = [["date", "past", "past_components", "approaching", "approaching_components"]]
    for name, counted in found["dates"].items():
        rows.append(
            [
                name,
                str(counted["past"]["items"]),
                str(counted["past"]["component_count"]),
                str(counted["approaching"]["items"]),
                str(counted["approaching"]["component_count"]),
            ]
        )
    _rows(format_, output, rows)
    if format_ == "table" and found["by_fiscal_year"]:
        typer.echo("")
        years = [["fiscal_year", "starts_on", "ends_on", "items", "component_count"]]
        for year in found["by_fiscal_year"]:
            years.append(
                [
                    str(year["fiscal_year"]),
                    year["starts_on"],
                    year["ends_on"],
                    str(year["items"]),
                    str(year["component_count"]),
                ]
            )
        _table(years)


@report.command("circuit-costs")
def circuit_cost_report(
    year: Annotated[
        int | None,
        typer.Option(help="The fiscal year, named for the year it ends in. Left out, this one."),
    ] = None,
    by: Annotated[
        str,
        typer.Option(help="carrier, site, region, group, circuit_type, owner or tag."),
    ] = "carrier",
    include_drafts: Drafts = False,
    format_: Annotated[str, typer.Option("--format", help="table, csv or json")] = "table",
    output: Output = None,
    url: Url = None,
    token: Token = None,
) -> None:
    """Show what circuits cost in a fiscal year, in total and for each value of --by:
    the year's cost, with a part month counted for its days as the carrier bills it,
    and the monthly and annual figures beside it."""
    _checked_format(format_)
    target = client.load_target(url, token)
    params: dict[str, Any] = {"by": by, "include_drafts": include_drafts}
    if year is not None:
        params["fiscal_year"] = year
    found = client.call(target, "GET", "/reports/circuit-costs", params=params)
    if format_ == "json":
        typer.echo(json.dumps(found, indent=2))
        return
    rows = [[by, "circuits", "cost", "monthly_cost", "annual_cost"]]
    for row in [*found["rows"], {**found["totals"], "label": "total"}]:
        rows.append(
            [
                row["label"] or "(none)",
                str(row["circuits"]),
                row["cost"],
                row["monthly_cost"],
                row["annual_cost"],
            ]
        )
    if format_ == "table":
        typer.echo(
            f"Fiscal year {found['fiscal_year']}, {found['starts_on']} to {found['ends_on']}; "
            f"the monthly figure of {found['as_of']}, in {found['currency']}"
        )
    _rows(format_, output, rows)


@report.command("replacements")
def replacements_report(
    filter_: Filter = None,
    sort: Sort = None,
    format_: Annotated[str, typer.Option("--format", help="table, csv or json")] = "table",
    output: Output = None,
    url: Url = None,
    token: Token = None,
) -> None:
    """List the replacements: the item that left and the item that took its place."""
    _checked_format(format_)
    target = client.load_target(url, token)
    params = {"filter": filter_, "sort": sort, "limit": 1000}
    found = client.call(target, "GET", "/reports/replacements", params=params)
    while len(found["items"]) < found["total"]:
        more = client.call(
            target,
            "GET",
            "/reports/replacements",
            params={**params, "offset": len(found["items"])},
        )
        if not more["items"]:
            break
        found["items"] += more["items"]
    if format_ == "json":
        typer.echo(json.dumps(found, indent=2))
        return
    if not found["items"] and format_ == "table":
        typer.echo("no item has been replaced", err=True)
        return
    rows = [["replaced_on", "old_item", "new_item", "reason", "reference"]]
    for one in found["items"]:
        rows.append(
            [
                one["replaced_on"],
                _named(one["old_item"]),
                _named(one["new_item"]),
                one["reason_label"],
                one["reference"] or "",
            ]
        )
    _rows(format_, output, rows)
    if format_ == "table":
        counted = ", ".join(f"{one['label']} {one['count']}" for one in found["by_reason"])
        noun = "replacement" if found["total"] == 1 else "replacements"
        typer.echo(f"\n{found['total']} {noun}: {counted}")


BALANCE = (
    "support_weight",
    "items_weight",
    "places_weight",
    "circuits_weight",
    "infrastructure_demand",
    "other_demand",
    "demand",
    "supply",
    "balance",
    "coverage_pct",
    "own_units",
    "outside_units",
    "own_share_pct",
    "annual_cost",
)


@report.command("capacity")
def capacity_report(
    format_: Annotated[str, typer.Option("--format", help="table, csv or json")] = "table",
    output: Output = None,
    try_: Annotated[
        list[str] | None,
        typer.Option(
            "--try",
            help="KEY=VALUE: try a default or a minimum weight, weight_per_resource_unit or "
            "stack_discount_pct; KEY= tries a weight blank. As often as needed.",
        ),
    ] = None,
    try_staff_add: Annotated[
        list[str] | None,
        typer.Option(help="NAME=QUANTITYxUNITS: try a staff line that is not there."),
    ] = None,
    try_staff_change: Annotated[
        list[str] | None,
        typer.Option(help="LINE=QUANTITYxUNITS: try a staff line, by name or HID, so."),
    ] = None,
    try_staff_leave_out: Annotated[
        list[str] | None,
        typer.Option(help="LINE: try the balance without a staff line, by name or HID."),
    ] = None,
    url: Url = None,
    token: Token = None,
) -> None:
    """Show demand beside supply by category, the balance and the coverage, without the
    drafts and with them. With --try, the balance in force beside the one tried: nothing
    is saved."""
    _checked_format(format_)
    target = client.load_target(url, token)
    if try_ or try_staff_add or try_staff_change or try_staff_leave_out:
        body = _tried_body(
            target, try_ or [], try_staff_add or [], try_staff_change or [], try_staff_leave_out
        )
        answer = client.call(target, "POST", "/reports/capacity/try", body)
        if format_ == "json":
            typer.echo(json.dumps(answer, indent=2))
            return
        _rows(format_, output, _tried_rows(answer))
        return
    found = client.call(target, "GET", "/reports/capacity")
    if format_ == "json":
        typer.echo(json.dumps(found, indent=2))
        return
    _rows(format_, output, _capacity_rows((found["active"], found["with_drafts"])))


def _shown(value: Any) -> str:
    return "" if value is None else str(value)


def _capacity_rows(views: tuple[dict[str, Any], ...], head: list[str] | None = None) -> list:
    """Return the rows of the capacity report: a column for each view."""
    rows = [head or ["measure", "active", "with_drafts"]]
    rows += [[name, *(_shown(view[name]) for view in views)] for name in BALANCE]
    for counted in ("defaulted", "raised"):
        for kind in ("items", "sites", "circuits"):
            rows.append([f"{counted}: {kind}", *(_shown(view[counted][kind]) for view in views)])
    for category in views[0]["by_category"]:
        units = [
            next(
                (
                    one["units"]
                    for one in view["by_category"]
                    if one["category"] == category["category"]
                ),
                None,
            )
            for view in views
        ]
        rows.append([f"supply: {category['label']}", *(_shown(one) for one in units)])
    rows += _capacity_parts(views, _shown)
    return rows


# --- Try, the what-if of the capacity report (P-156) ---

TRIED_KEYS = (
    "default_item_weight",
    "minimum_item_weight",
    "default_site_weight",
    "minimum_site_weight",
    "default_circuit_weight",
    "minimum_circuit_weight",
    "weight_per_resource_unit",
    "stack_discount_pct",
)


def _quantity_by_units(text: str, option: str) -> tuple[str, str | None, str | None]:
    """Read NAME=QUANTITYxUNITS: the name, the quantity and the units of one. A blank
    part is left as it is."""
    name, mark, amounts = text.rpartition("=")
    quantity, times, units = amounts.lower().partition("x")
    if not mark or not times or not name.strip():
        raise client.fail(f"{option} takes NAME=QUANTITYxUNITS, such as 'Engineer=2x1'", 2)
    return name.strip(), quantity.strip() or None, units.strip() or None


def _staff_lines(target: Target) -> list[dict[str, Any]]:
    """Return the staff lines there are, retired ones among them, for naming them."""
    return client.call(
        target,
        "GET",
        "/capacity-lines",
        params={
            "filter": "category:eq:staff side:eq:supply",
            "include_drafts": True,
            "include_archived": True,
            "limit": 1000,
        },
    )["items"]


def _staff_line(lines: list[dict[str, Any]], named: str) -> str:
    """Return the HID of the staff line known by a name or an HID."""
    wanted = named.strip().casefold()
    for line in lines:
        if wanted in (line["hid"], line["name"].strip().casefold()):
            return line["hid"]
    raise client.fail(f"there is no staff line {named}", client.EXIT_INVALID)


def _tried_body(
    target: Target,
    tries: list[str],
    added: list[str],
    changed: list[str],
    left_out: list[str] | None,
) -> dict[str, Any]:
    """Return what a Try sends: the figures tried, and the staff lines tried."""
    body: dict[str, Any] = {}
    for one in tries:
        key, mark, value = one.partition("=")
        key = key.strip()
        if not mark or key not in TRIED_KEYS:
            raise client.fail(f"--try takes KEY=VALUE, KEY one of {', '.join(TRIED_KEYS)}", 2)
        body[key] = value.strip() or None
    lines = _staff_lines(target) if changed or left_out else []
    staff: dict[str, list[Any]] = {"add": [], "change": [], "leave_out": []}
    for one in added:
        name, quantity, units = _quantity_by_units(one, "--try-staff-add")
        if units is None:
            raise client.fail("--try-staff-add gives the units of one: NAME=QUANTITYxUNITS", 2)
        staff["add"].append({"name": name, "quantity": quantity or "1", "units_each": units})
    for one in changed:
        name, quantity, units = _quantity_by_units(one, "--try-staff-change")
        staff["change"].append(
            {"hid": _staff_line(lines, name), "quantity": quantity, "units_each": units}
        )
    staff["leave_out"] = [_staff_line(lines, one) for one in left_out or []]
    body["staff"] = staff
    return body


def _tried_rows(answer: dict[str, Any]) -> list[list[str]]:
    """Return the rows of a Try: the balance in force beside the one tried, each view."""
    views = (
        answer["in_force"]["active"],
        answer["tried"]["active"],
        answer["in_force"]["with_drafts"],
        answer["tried"]["with_drafts"],
    )
    head = ["measure", "active", "active_tried", "with_drafts", "with_drafts_tried"]
    rows = _capacity_rows(views, head)
    per_unit = [answer[side]["weight_per_resource_unit"] for side in ("in_force", "tried")]
    rows.append(["weight_per_resource_unit", per_unit[0], per_unit[1], per_unit[0], per_unit[1]])
    return rows


# --- end of Try ---


def _capacity_parts(views: tuple[dict[str, Any], ...], shown: Any) -> list[list[str]]:
    """Return the rows of the capacity report beside the balance: what each line that
    multiplies adds, and the demand and the share of each region and of what is nowhere."""
    rows = []
    gains: dict[str, dict[str, Any]] = {}
    for view in views:
        for line in view["multiplying_lines"]:
            gains.setdefault(line["hid"], line)
    for hid, line in gains.items():
        on = ", ".join(target["name"] for target in line["applies_to"])
        units = [
            next((one["units"] for one in view["multiplying_lines"] if one["hid"] == hid), "")
            for view in views
        ]
        rows.append([f"multiplies: {line['name']} ({line['factor']} on {on})", *units])
    regions: dict[str | None, str] = {}
    for view in views:
        for row in view["demand_by_region"]:
            regions.setdefault(row["region_hid"], row["path"] or "nowhere")
    for hid, path in regions.items():
        found = [
            next((row for row in view["demand_by_region"] if row["region_hid"] == hid), None)
            for view in views
        ]
        for measure, name in (("infrastructure_demand", "demand"), ("share_pct", "share")):
            rows.append([f"{name}: {path}", *(shown(row[measure]) if row else "" for row in found)])
    return rows


RECORD_FIGURES = ("demand", "supply", "balance", "coverage_pct")


@capacity.command("record")
def record_capacity(
    note: Annotated[str | None, typer.Option(help="What to say of this week's record.")] = None,
    format_: Annotated[str, typer.Option("--format", help="table or json")] = "table",
    url: Url = None,
    token: Token = None,
) -> None:
    """Record the capacity balance as it is now, in place of this week's record."""
    target = client.load_target(url, token)
    made = client.call(target, "POST", "/capacity-records", {"note": note})
    if format_ == "json":
        typer.echo(json.dumps(made, indent=2))
        return
    typer.echo(f"recorded the week of {made['week_of']}")
    for view in ("active", "with_drafts"):
        figures = ", ".join(f"{name} {made[view][name]}" for name in RECORD_FIGURES[:3])
        typer.echo(f"{view + ':':<13}{figures}")


@capacity.command("records")
def capacity_records(
    format_: Annotated[str, typer.Option("--format", help="table, csv or json")] = "table",
    output: Output = None,
    url: Url = None,
    token: Token = None,
) -> None:
    """List the records of the capacity balance, a week to a row, the oldest first."""
    _checked_format(format_)
    target = client.load_target(url, token)
    found: list[dict[str, Any]] = []
    while True:
        page = client.call(
            target, "GET", "/capacity-records", params={"limit": 1000, "offset": len(found)}
        )
        found += page["items"]
        if not page["items"] or len(found) >= page["total"]:
            break
    if format_ == "json":
        typer.echo(json.dumps(found, indent=2))
        return
    head = ["week_of"]
    head += [f"{view}.{name}" for view in ("active", "with_drafts") for name in RECORD_FIGURES]
    rows = [[*head, "adjusted", "note"]]
    for one in found:
        figures = [
            "" if one[view][name] is None else str(one[view][name])
            for view in ("active", "with_drafts")
            for name in RECORD_FIGURES
        ]
        adjusted = "true" if one["adjusted"] else "false"
        rows.append([one["week_of"], *figures, adjusted, one["note"] or ""])
    _rows(format_, output, rows)


# --- circuits and circuit groups (P-154) ---------------------------------------------

# The fields of a circuit that `circuits set` sends as they are given. The carrier, the
# owner and the two locations are named as a file names them, and found first.
CIRCUIT_FIELDS = (
    "name",
    "enterprise_circuit_id",
    "description",
    "circuit_type",
    "port_mbps",
    "down_mbps",
    "up_mbps",
    "a_note",
    "z_note",
    "cost_side",
    "carrier_circuit_number",
    "billing_account",
    "billing_contract",
    "installed_on",
    "activated_on",
    "disconnected_on",
    "production",
    "support_weight",
    "notes",
    "record_status",
)
CIRCUIT_REFERENCES = ("carrier", "owner", "a_location", "z_location", "tags")


def find_circuit(target: Target, text: str) -> dict[str, Any]:
    """Return the one circuit known by text: its HID, its enterprise circuit ID or a name
    that one circuit alone has. When more than one answers they are listed, and nothing
    is done."""
    if _is_hid(text):
        return client.call(target, "GET", f"/circuits/{text}")
    known_by = ("enterprise_circuit_id", "name")
    query = {
        "filter": {"or": [{"field": name, "op": "eq", "value": text} for name in known_by]},
        "include_archived": True,
        "include_drafts": True,
        "limit": 20,
    }
    found = client.call(target, "POST", "/circuits/query", query)["items"]
    if len(found) == 1:
        return client.call(target, "GET", f"/circuits/{found[0]['hid']}")
    if not found:
        raise client.fail(f"there is no circuit {text}", client.EXIT_INVALID)
    for one in found:
        typer.echo(f"  {one['hid']}  {one['name']}", err=True)
    raise client.fail(
        f"more than one circuit answers to {text}: name the one meant by its HID",
        client.EXIT_INVALID,
    )


def _circuit_side(circuit: dict[str, Any], side: str) -> str | None:
    """Return one side of a circuit as one line: its location's path, or its note."""
    at, note = circuit[f"{side}_side"], circuit[f"{side}_note"]
    if at is None:
        return note
    retired = " (retired)" if at["record_status"] == "retired" else ""
    return f"{at['path']}{retired}" + (f", {note}" if note else "")


def _named_contact(named: Any) -> str:
    """Return a contact in force as one line: who, and how to reach them."""
    contact = named.get("contact", named) if isinstance(named, dict) else {"name": str(named)}
    reached = " ".join(part for part in (contact.get("email"), contact.get("phone")) if part)
    retired = " (retired)" if contact.get("record_status") == "retired" else ""
    return f"{contact.get('name', '')} {reached}".rstrip() + retired


def _circuit_contacts(circuit: dict[str, Any]) -> list[tuple[str, str]]:
    """Return a line for each contact a circuit has in force: the site contacts of each
    side with the level each came from, and the account team and the support desk,
    marked `(vendor)` where they are the carrier's."""
    effective = circuit["effective"]
    lines = []
    for side in ("a", "z"):
        for role in (effective.get("site_contacts") or {}).get(side) or []:
            source = role.get("source")
            came = f" ({source})" if source and source != "own" else ""
            for named in role.get("value") or []:
                lines.append((f"{side}_side.{role.get('role')}", _named_contact(named) + came))
    for name in ("account_managers", "support_contacts"):
        in_force = effective.get(name) or {}
        marked = " (vendor)" if in_force.get("source") == "vendor" else ""
        for named in in_force.get("value") or []:
            lines.append((name, _named_contact(named) + marked))
    return lines


def _cost_line(line: dict[str, Any]) -> str:
    """Return a cost line as one line: what it is, what it costs, and when."""
    shown = f"{line['description']}: {line['monthly_cost']} a month"
    if line["vendor"]:
        shown += f", billed by {line['vendor']}"
    if line["starts_on"] or line["ends_on"]:
        shown += f", {_period(line['starts_on'], line['ends_on'])}"
    return shown + ("" if line["in_date"] else ", not billed today")


@circuits.command("show")
def show_circuit(
    circuit: Annotated[str, typer.Argument(help="An HID, an enterprise circuit ID or a name.")],
    format_: Annotated[str, typer.Option("--format", help="table or json")] = "table",
    url: Url = None,
    token: Token = None,
) -> None:
    """Show one circuit: its sides and their site contacts, its carriers and their
    numbers, the account team and the support desk in force, its devices, its cost lines
    with the monthly and annual totals, and its groups."""
    target = client.load_target(url, token)
    found = find_circuit(target, circuit)
    if format_ == "json":
        typer.echo(json.dumps(found, indent=2))
        return
    zone = _zone(target)
    carrier = found["carrier"]["name"] if found["carrier"] else None
    if carrier and found["carrier_circuit_number"]:
        carrier += f" {found['carrier_circuit_number']}"
    weight = found["effective"]["support_weight"]
    if weight["value"] is not None and weight["source"] != "own":
        weight = {**weight, "value": f"{weight['value']} ({weight['source']})"}
    lines: list[tuple[str, Any]] = [
        ("hid", found["hid"]),
        ("name", found["name"]),
        ("enterprise_circuit_id", found["enterprise_circuit_id"]),
        ("circuit_type", found["circuit_type"]),
        ("speed", found["speed"]),
        ("a_side", _circuit_side(found, "a")),
        ("z_side", _circuit_side(found, "z")),
        ("counts_at", f"{found['cost_site_path']} (the {found['cost_side'].upper()} side)"),
        ("carrier", carrier),
    ]
    for one in found["carriers"] or []:
        parts = (one["vendor"], f"({one['role']})", one["circuit_number"])
        lines.append(("carrier", " ".join(part for part in parts if part)))
    lines += [
        ("billing_account", found["billing_account"]),
        ("billing_contract", found["billing_contract"]),
        *((name, found[name]) for name in ("installed_on", "activated_on", "disconnected_on")),
        ("production", found["production"]),
        ("in_service", found["in_service"]),
        ("support_weight", weight["value"]),
        ("owner", found["owner"]["label"] if found["owner"] else None),
        ("owner_exception", found["owner_exception_reason"] or found["owner_exception"] or None),
        *_circuit_contacts(found),
    ]
    for device in found["devices"] or []:
        retired = " (retired)" if device["record_status"] == "retired" else ""
        lines.append(("device", f"{device['name']} on the {device['side'].upper()} side{retired}"))
    lines += [("cost", _cost_line(line)) for line in found["costs"] or []]
    lines += [("monthly_cost", found["monthly_cost"]), ("annual_cost", found["annual_cost"])]
    for group in found["groups"] or []:
        retired = " (retired)" if group["record_status"] == "retired" else ""
        lines.append(("group", group["name"] + retired))
    lines += [
        ("notes", found["notes"]),
        ("tags", ", ".join(found["tags"]) or None),
        ("record_status", found["record_status"]),
        ("updated_at", clock.shown(datetime.fromisoformat(found["updated_at"]), zone)),
        ("row_version", found["row_version"]),
    ]
    for name, value in lines:
        if value is not None:
            shown = str(value).lower() if isinstance(value, bool) else value
            typer.echo(f"{name + ':':<21}{shown}")


@circuits.command("set")
def set_circuit(
    circuit: Annotated[str, typer.Argument(help="An HID, an enterprise circuit ID or a name.")],
    changes: Annotated[
        list[str],
        typer.Argument(
            help="field=value to set and field= to clear, a field named as a column of a "
            "file: carrier= takes a vendor's name, owner= a label, a_location= and "
            "z_location= a path, and tags= labels joined with ;."
        ),
    ],
    url: Url = None,
    token: Token = None,
) -> None:
    """Change a circuit. cost_side=z counts it at its far end."""
    target = client.load_target(url, token)
    found = find_circuit(target, circuit)
    body: dict[str, Any] = {"row_version": found["row_version"]}
    for argument in changes:
        name, equals, value = argument.partition("=")
        name, value = name.strip(), value.strip()
        if not equals or not name:
            raise client.fail(f"{argument!r} is not field=value", 2)
        if name == "carrier":
            body["carrier_hid"] = (
                _one_named(target, "/vendors", "name", value, "vendor")["hid"] if value else None
            )
        elif name == "owner":
            body["owner_hid"] = (
                _one_named(target, "/owners", "label", value, "owner")["hid"] if value else None
            )
        elif name in ("a_location", "z_location"):
            body[f"{name}_hid"] = find_place(target, value, "location")["hid"] if value else None
        elif name == "tags":
            body["tags"] = [label.strip() for label in value.split(";") if label.strip()]
        elif name in CIRCUIT_FIELDS:
            body[name] = value or None
        else:
            known = ", ".join((*CIRCUIT_FIELDS, *CIRCUIT_REFERENCES))
            raise client.fail(f"{name} is not a field of a circuit: one of {known}", 2)
    changed = client.call(target, "PATCH", f"/circuits/{found['hid']}", body)
    typer.echo(
        f"{changed['name']}: {changed['speed'] or 'no speed'}, counted at "
        f"{changed['cost_site_path']} (the {changed['cost_side'].upper()} side), "
        f"{changed['monthly_cost']} a month"
    )


@circuits.command("retire")
def retire_circuit(
    circuit: Annotated[str, typer.Argument(help="An HID, an enterprise circuit ID or a name.")],
    url: Url = None,
    token: Token = None,
) -> None:
    """Retire a circuit. Its parts and its groups stay on record."""
    target = client.load_target(url, token)
    found = find_circuit(target, circuit)
    retired = client.call(
        target, "POST", f"/circuits/{found['hid']}/retire", {"row_version": found["row_version"]}
    )
    typer.echo(f"{retired['name']}: retired")


def find_circuit_group(target: Target, text: str) -> dict[str, Any]:
    """Return the circuit group with an HID or a name."""
    return _one_named(target, "/circuit-groups", "name", text, "circuit group")


def _group_members(target: Target, group_hid: str) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    while True:
        page = client.call(
            target,
            "GET",
            f"/circuit-groups/{group_hid}/members",
            params={"limit": 1000, "offset": len(members)},
        )
        members += page["items"]
        if not page["items"] or len(members) >= page["total"]:
            return members


@circuit_groups.command("show")
def show_circuit_group(
    group: Annotated[str, typer.Argument(help="An HID or a name.")],
    format_: Annotated[str, typer.Option("--format", help="table or json")] = "table",
    url: Url = None,
    token: Token = None,
) -> None:
    """Show one circuit group with its circuits and what they cost."""
    target = client.load_target(url, token)
    found = find_circuit_group(target, group)
    members = _group_members(target, found["hid"])
    if format_ == "json":
        typer.echo(json.dumps({**found, "members": members}, indent=2))
        return
    lines: list[tuple[str, Any]] = [
        ("hid", found["hid"]),
        ("name", found["name"]),
        ("description", found["description"]),
        ("owner", found["owner"]["label"] if found["owner"] else None),
        ("circuits", found["circuits"]),
        ("in_service", found["in_service"]),
        ("monthly_cost", found["monthly_cost"]),
        ("annual_cost", found["annual_cost"]),
        ("notes", found["notes"]),
        ("tags", ", ".join(found["tags"]) or None),
        ("record_status", found["record_status"]),
        ("row_version", found["row_version"]),
    ]
    for name, value in lines:
        if value is not None:
            typer.echo(f"{name + ':':<21}{value}")
    if members:
        typer.echo("")
        head = ["name", "enterprise_circuit_id", "circuit_type", "speed", "in_service"]
        rows = [[*head, "monthly_cost", "record_status"]]
        for member in members:
            one = member["circuit"]
            rows.append(
                [
                    one["name"],
                    one["enterprise_circuit_id"] or "",
                    one["circuit_type"] or "",
                    one["speed"] or "",
                    "true" if one["in_service"] else "false",
                    one["monthly_cost"],
                    one["record_status"],
                ]
            )
        _table(rows)


CircuitsNamed = Annotated[
    list[str],
    typer.Argument(metavar="CIRCUIT...", help="Circuits: HIDs, enterprise circuit IDs or names."),
]


@circuit_groups.command("add")
def add_to_circuit_group(
    group: Annotated[str, typer.Argument(help="The group: an HID or a name.")],
    named: CircuitsNamed,
    url: Url = None,
    token: Token = None,
) -> None:
    """Put circuits into a group, all together. A circuit is in a group once."""
    target = client.load_target(url, token)
    found = find_circuit_group(target, group)
    hids = list(dict.fromkeys(find_circuit(target, text)["hid"] for text in named))
    client.call(target, "POST", f"/circuit-groups/{found['hid']}/members", {"circuit_hids": hids})
    now = find_circuit_group(target, found["hid"])
    typer.echo(f"{now['name']}: {len(hids)} added, {now['circuits']} circuits in all")


@circuit_groups.command("remove")
def remove_from_circuit_group(
    group: Annotated[str, typer.Argument(help="The group: an HID or a name.")],
    named: CircuitsNamed,
    url: Url = None,
    token: Token = None,
) -> None:
    """Take circuits out of a group. The audit trail keeps what each membership was."""
    target = client.load_target(url, token)
    found = find_circuit_group(target, group)
    held = {member["circuit_hid"]: member for member in _group_members(target, found["hid"])}
    taken = []
    for text in named:
        one = find_circuit(target, text)
        if one["hid"] not in held:
            raise client.fail(f"{one['name']} is not in {found['name']}", client.EXIT_INVALID)
        taken.append(held[one["hid"]])
    for member in taken:
        client.call(target, "DELETE", f"/circuit-groups/{found['hid']}/members/{member['hid']}")
    now = find_circuit_group(target, found["hid"])
    typer.echo(f"{now['name']}: {len(taken)} taken out, {now['circuits']} circuits in all")
