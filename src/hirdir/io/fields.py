"""The fields each list can be filtered and sorted by, and how the list is read.

A field named here is one a filter may use on that list. Dotted names reach a related
record (`catalog.pid`, `owner.label`), and `effective.<field>` is the value in force of
a field that inherits.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Select, func, or_, select

from hirdir.db.models import CatalogEntry, Item, Owner, Tag, TagLink, Vendor
from hirdir.domain import inheritance, lifecycle, records
from hirdir.domain.items import mac_digits
from hirdir.io.filters import Field


@dataclass(frozen=True)
class Listing:
    """How one list is read: its record, its fields, and what it leaves out by default."""

    model: Any
    fields: Mapping[str, Field]
    joined: Callable[[Select[Any]], Select[Any]]
    default_sort: tuple[str, ...]
    has_status: bool = True


def _tagged(record_type: str, hid: Any) -> Callable[[str], ColumnElement[bool]]:
    """Return the test that a record carries a tag: the one with a label, or any at all."""

    def test(label: str) -> ColumnElement[bool]:
        linked = (
            select(TagLink.tag_hid)
            .join(Tag, Tag.hid == TagLink.tag_hid)
            .where(TagLink.record_type == record_type, TagLink.record_hid == hid)
        )
        if label:
            linked = linked.where(Tag.label_key == records.key(label))
        return linked.exists()

    return test


def _columns(model: Any, kind: str, *names: str) -> dict[str, Field]:
    return {name: Field(kind, getattr(model, name)) for name in names}


def _bookkeeping(model: Any) -> dict[str, Field]:
    return {
        "hid": Field("reference", model.hid),
        "row_version": Field("integer", model.row_version),
        **_columns(model, "timestamp", "created_at", "updated_at"),
    }


def _effective(name: str) -> Field:
    own = getattr(Item, name)
    kind = (
        "date"
        if name in ("end_of_sale", "end_of_sw_support", "end_of_hw_support", "ldos")
        else "number"
    )
    return Field(kind, func.coalesce(own, getattr(CatalogEntry, name), type_=own.type))


_INHERITED_DATES = ("end_of_sale", "end_of_sw_support", "end_of_hw_support", "ldos")
_INHERITED_AMOUNTS = ("est_value", "support_weight", "annual_support_cost")

ITEMS = Listing(
    model=Item,
    fields={
        **_bookkeeping(Item),
        **_columns(Item, "reference", "catalog_entry_hid", "owner_hid"),
        **_columns(
            Item,
            "text",
            "serial_number",
            "asset_tag",
            "hostname",
            "fqdn",
            "description",
            "comments",
        ),
        # A blank name shows the hostname, so that is what a filter and a sort see.
        "name": Field("text", func.coalesce(Item.name, Item.hostname)),
        "mac_address": Field("mac", Item.mac_address, convert=mac_digits),
        "quantity": Field("integer", Item.quantity),
        **_columns(
            Item, "choice", "lifecycle_state", "disposition", "state_reason", "record_status"
        ),
        "expected_online": Field("boolean", Item.expected_online),
        "state_changed_at": Field("timestamp", Item.state_changed_at),
        **_columns(
            Item,
            "date",
            "procured_on",
            "delivered_on",
            "in_service_on",
            "warranty_start",
            "warranty_end",
            *_INHERITED_DATES,
        ),
        **_columns(Item, "number", *_INHERITED_AMOUNTS),
        **{f"effective.{name}": _effective(name) for name in inheritance.ITEM_FIELDS},
        "catalog.pid": Field("text", CatalogEntry.pid),
        "catalog.model_name": Field("text", CatalogEntry.model_name),
        "catalog.vendor": Field("text", Vendor.name),
        "catalog.kind": Field("choice", CatalogEntry.kind),
        "catalog.type": Field("choice", CatalogEntry.type),
        "catalog.function": Field("choice", CatalogEntry.function),
        "owner.label": Field("text", Owner.label),
        "tags": Field("tags", test=_tagged("item", Item.hid)),
    },
    joined=lambda query: (
        query.outerjoin(CatalogEntry, CatalogEntry.hid == Item.catalog_entry_hid)
        .outerjoin(Vendor, Vendor.hid == CatalogEntry.vendor_hid)
        .outerjoin(Owner, Owner.hid == Item.owner_hid)
    ),
    default_sort=("name",),
)

CATALOG_ENTRIES = Listing(
    model=CatalogEntry,
    fields={
        **_bookkeeping(CatalogEntry),
        **_columns(CatalogEntry, "reference", "vendor_hid", "successor_hid"),
        "vendor": Field("text", Vendor.name),
        **_columns(CatalogEntry, "text", "pid", "model_name", "description"),
        **_columns(
            CatalogEntry, "choice", "kind", "type", "function", "review_status", "record_status"
        ),
        **_columns(CatalogEntry, "date", *_INHERITED_DATES),
        **_columns(CatalogEntry, "number", *_INHERITED_AMOUNTS, "stack_discount_pct"),
        "tags": Field("tags", test=_tagged("catalog_entry", CatalogEntry.hid)),
    },
    joined=lambda query: query.join(Vendor, Vendor.hid == CatalogEntry.vendor_hid),
    default_sort=("vendor", "pid"),
)

VENDORS = Listing(
    model=Vendor,
    fields={**_bookkeeping(Vendor), **_columns(Vendor, "text", "name", "notes")},
    joined=lambda query: query,
    default_sort=("name",),
    has_status=False,
)

OWNERS = Listing(
    model=Owner,
    fields={
        **_bookkeeping(Owner),
        **_columns(Owner, "text", "label", "organization", "exception_reason"),
        "is_external": Field("boolean", Owner.is_external),
        "record_status": Field("choice", Owner.record_status),
    },
    joined=lambda query: query,
    default_sort=("label",),
)


def default_view(
    listing: Listing, include_archived: bool, include_drafts: bool
) -> list[ColumnElement[bool]]:
    """Return what a list leaves out unless asked: drafts, and retired and archived records."""
    if not listing.has_status:
        return []
    model = listing.model
    left_out: list[ColumnElement[bool]] = []
    if not include_drafts:
        left_out.append(model.record_status != "draft")
    if not include_archived:
        left_out.append(model.record_status != "retired")
        if model is Item:
            left_out.append(
                or_(Item.lifecycle_state.is_(None), Item.lifecycle_state != lifecycle.ARCHIVED)
            )
    return left_out
