"""The tables that are paged and are no list of records: what each is sorted by.

A list of records takes a filter and a sort and is read in `hirdir.io.listing`. The
users, the audit trail, the stored previews and their rows, the duplicates report, the
members of one group, the minor items of one item and its history are tables of another
kind: paged by the server, with no filter of the grammar. Each takes the `sort` that a
list takes, over the columns its page shows.

Each keeps the order it always had. That order is what its rows are in when no sort is
asked for, and what settles the rows that a sort leaves tied, so that paging never
repeats or skips one. Nothing here is in a statement unless a sort asks for it.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, case, func, or_, select

from hirdir.auth.roles import Role
from hirdir.db import dialect
from hirdir.db.models import (
    Address,
    AuditEvent,
    CatalogEntry,
    DeviceGroup,
    DeviceGroupMember,
    ImportJob,
    ImportRow,
    Item,
    Network,
    RoleGrant,
    User,
    UserGroup,
    UserGroupMember,
)
from hirdir.domain.records import AnySelect, Arrange
from hirdir.io import filters
from hirdir.io.fields import ITEMS, shown_name
from hirdir.io.filters import Field


def _as_it_is(query: AnySelect) -> AnySelect:
    return query


@dataclass(frozen=True)
class Table:
    """One such table: the record its rows are read from, the fields they are sorted
    by, and the joins those need."""

    record: Any
    fields: Mapping[str, Field]
    joined: Callable[[AnySelect], AnySelect] = _as_it_is
    # What the contract says of its `sort`, where the names are too many to list.
    said: str = ""

    @property
    def help(self) -> str:
        """What the contract says of the `sort` of this table."""
        names = self.said or ", ".join(f"`{name}`" for name in self.fields)
        return (
            f"What to sort by: {names}. `-` in front for descending. Repeat or separate by commas."
        )


def arrange(table: Table, sort: list[str] | None) -> Arrange | None:
    """Return what puts the rows of a table in the order a sort asks for.

    It is given the statement that reads the table and returns it sorted, for the
    statement's own order to follow. With no sort it is nothing, and the statement is
    left as it always was. A field the table does not have is refused, as a list does.
    """
    keys = filters.parse_sort(sort, table.fields)
    if not keys:
        return None
    terms = filters.order_by(keys, table.fields)
    return lambda query: table.joined(query).order_by(*terms)


# --- users ---------------------------------------------------------------------------

_GROUPS_OF_USER = (
    select(UserGroupMember.group_hid).where(UserGroupMember.user_hid == User.hid).correlate(User)
)

USERS = Table(
    User,
    {
        "username": Field("text", User.username),
        "display_name": Field("text", func.nullif(User.display_name, "")),
        # The role in force, the highest that the user or a group of theirs is granted:
        # the lowest first, and a user with none last.
        "role": Field(
            "choice",
            ordered_by=select(
                func.max(case(*((RoleGrant.role == role.value, role.rank) for role in Role)))
            )
            .where(or_(RoleGrant.user_hid == User.hid, RoleGrant.group_hid.in_(_GROUPS_OF_USER)))
            .correlate(User)
            .scalar_subquery(),
        ),
        # The first of the user's groups, by name.
        "groups": Field(
            "text",
            ordered_by=select(func.min(UserGroup.name_key))
            .join(UserGroupMember, UserGroupMember.group_hid == UserGroup.hid)
            .where(UserGroupMember.user_hid == User.hid)
            .correlate(User)
            .scalar_subquery(),
        ),
        "is_service_account": Field("boolean", User.is_service_account),
        "disabled": Field("boolean", User.disabled),
        "last_sign_in_at": Field("timestamp", User.last_sign_in_at),
    },
)

# --- the audit trail, and the history of one record ------------------------------------


def _username(hid: Any, of: Any) -> Any:
    return select(User.username).where(User.hid == hid).correlate(of).scalar_subquery()


AUDIT_EVENTS = Table(
    AuditEvent,
    {
        "at": Field("timestamp", AuditEvent.at),
        "actor_name": Field("text", _username(AuditEvent.actor_hid, AuditEvent)),
        "via": Field("text", AuditEvent.via),
        "action": Field("text", AuditEvent.action),
        "record_type": Field("text", func.nullif(AuditEvent.record_type, "")),
        "record_hid": Field("reference", AuditEvent.record_hid),
    },
)
# An event's changes stay together: the history is sorted by its events.
HISTORY = Table(
    AuditEvent, {name: AUDIT_EVENTS.fields[name] for name in ("at", "actor_name", "action")}
)

# --- stored previews and their rows ----------------------------------------------------

IMPORT_JOBS = Table(
    ImportJob,
    {
        "created_at": Field("timestamp", ImportJob.created_at),
        "file_name": Field("text", ImportJob.file_name),
        "entity": Field("choice", ImportJob.entity),
        "mode": Field("choice", ImportJob.mode),
        "status": Field("choice", ImportJob.status),
        "row_count": Field("integer", ImportJob.row_count),
        "created": Field("integer", ImportJob.created),
        "updated": Field("integer", ImportJob.updated),
        "unchanged": Field("integer", ImportJob.unchanged),
        "rejected": Field("integer", ImportJob.rejected),
        "created_by_name": Field("text", _username(ImportJob.created_by, ImportJob)),
    },
)

IMPORT_ROWS = Table(
    ImportRow,
    {
        "row": Field("integer", ImportRow.row),
        # How the row names its record, or else the record it matched.
        "key": Field("text", func.coalesce(func.nullif(ImportRow.key, ""), ImportRow.record_hid)),
        "outcome": Field("choice", ImportRow.outcome),
    },
)

# --- the members of one group, and the minor items of one item ------------------------

GROUP_MEMBERS = Table(
    DeviceGroupMember,
    {
        "position": Field("integer", DeviceGroupMember.position),
        "item.name": Field("text", shown_name(Item)),
        "item.pid": Field("text", CatalogEntry.pid),
        "item.serial_number": Field("text", Item.serial_number),
        "role": Field("choice", DeviceGroupMember.role),
        # The current member that is seen as master comes first, either way round: the
        # others have nothing in that column.
        "observed_master": Field(
            "boolean",
            ordered_by=case(
                (
                    and_(
                        DeviceGroupMember.left_on.is_(None),
                        DeviceGroup.observed_master_hid == DeviceGroupMember.item_hid,
                    ),
                    1,
                )
            ),
        ),
        "joined_on": Field("date", DeviceGroupMember.joined_on),
        "left_on": Field("date", DeviceGroupMember.left_on),
    },
    joined=lambda query: (
        query.join(Item, Item.hid == DeviceGroupMember.item_hid)
        .outerjoin(CatalogEntry, CatalogEntry.hid == Item.catalog_entry_hid)
        .join(DeviceGroup, DeviceGroup.hid == DeviceGroupMember.group_hid)
    ),
)

# The minor items of an item are items: they are sorted by what the item list is.
CHILDREN = Table(
    Item,
    ITEMS.fields,
    joined=ITEMS.joined,
    said=(
        "any field the item list is sorted by, such as `position`, `name`, `catalog.pid`, "
        "`serial_number`, `effective.lifecycle_state`, `owner.label`, `location.name` and "
        "`minor_items`"
    ),
)

# --- the duplicates report -------------------------------------------------------------

# Each row is one address under one network, with those that hold it: what it is sorted
# by is said of them all together.
DUPLICATES = Table(
    Address,
    {
        "address": Field("address", ordered_by=dialect.as_address(Address.address)),
        "network": Field("text", ordered_by=func.min(Network.label_key)),
        "count": Field("integer", ordered_by=func.count()),
        # The first of its holders, by name: an item by its name or hostname.
        "holders": Field(
            "text",
            ordered_by=func.min(
                dialect.folded(
                    case(
                        (
                            Address.item_hid.is_not(None),
                            func.coalesce(Item.name, Item.hostname),
                        ),
                        else_=DeviceGroup.name,
                    )
                )
            ),
        ),
    },
    joined=lambda query: (
        query.outerjoin(Network, Network.hid == Address.network_hid)
        .outerjoin(Item, Item.hid == Address.item_hid)
        .outerjoin(DeviceGroup, DeviceGroup.hid == Address.group_hid)
    ),
)

TABLES: tuple[Table, ...] = (
    USERS,
    AUDIT_EVENTS,
    HISTORY,
    IMPORT_JOBS,
    IMPORT_ROWS,
    GROUP_MEMBERS,
    CHILDREN,
    DUPLICATES,
)


def warm() -> int:
    """Build the statement of every table once, sorted by every field it has, before a
    request is answered, as `hirdir.io.fields.warm` does for the lists and for the
    same reason. Return how many statements were built."""
    for table in TABLES:
        names = [name for name, field in table.fields.items() if filters.sorted_by(field)]
        arranged = arrange(table, names)
        if arranged is not None:
            str(arranged(select(table.record)).compile())
    return len(TABLES)
