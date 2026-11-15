"""Reset: clearing the inventory so that a site can start over.

This is the one place where records are deleted. It is reached from `hirdir admin
reset` on the server and from nowhere else: no route calls it. A site loads test data,
tries things out, clears it, and enters its own.

Every table is named here, as one that a reset clears or one that it keeps. A table
that is in neither list fails a test, so that a release which adds a record has to say
which it is.
"""

from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from hirdir.db.models import (
    Address,
    Agreement,
    AuditEvent,
    CapacityLine,
    CapacityLineTarget,
    CapacityRecord,
    CatalogEntry,
    Choice,
    Circuit,
    CircuitCarrier,
    CircuitContact,
    CircuitCost,
    CircuitDevice,
    CircuitGroup,
    CircuitGroupMember,
    Contact,
    ContactAssignment,
    Contract,
    ContractContact,
    ContractCoverage,
    DeviceGroup,
    DeviceGroupMember,
    ExternalSystem,
    IdempotencyKey,
    ImportJob,
    ImportRow,
    Item,
    ItemReplacement,
    LifecycleRule,
    Location,
    Network,
    Operator,
    Owner,
    OwnerMember,
    PurchaseLine,
    PurchaseRequest,
    Region,
    Registration,
    RenewalAlertView,
    RoleGrant,
    ServiceToken,
    Setting,
    Site,
    Tag,
    TagLink,
    User,
    UserGroup,
    UserGroupMember,
    Vendor,
    VendorContact,
)
from hirdir.domain import audit
from hirdir.domain.audit import AuditContext, change

# The inventory, in an order in which each table can be emptied: what refers to a
# record goes before the record.
CLEARED: tuple[Any, ...] = (
    TagLink,
    CircuitGroupMember,
    CircuitGroup,
    CircuitContact,
    CircuitDevice,
    CircuitCost,
    CircuitCarrier,
    Circuit,
    VendorContact,
    ImportRow,
    ImportJob,
    IdempotencyKey,
    RenewalAlertView,
    CapacityRecord,
    CapacityLineTarget,
    CapacityLine,
    Registration,
    ExternalSystem,
    ContractCoverage,
    ContractContact,
    Contract,
    Agreement,
    Address,
    Network,
    DeviceGroupMember,
    DeviceGroup,
    ItemReplacement,
    Item,
    PurchaseLine,
    PurchaseRequest,
    CatalogEntry,
    OwnerMember,
    Owner,
    ContactAssignment,
    Location,
    Site,
    Region,
    Operator,
    Contact,
    Vendor,
    Tag,
)
# Who may sign in and how the installation is set up. The audit trail is kept too, but
# for the events of the records that are cleared.
KEPT: tuple[Any, ...] = (
    User,
    UserGroup,
    UserGroupMember,
    RoleGrant,
    ServiceToken,
    Choice,
    Setting,
    LifecycleRule,
    AuditEvent,
)
# The `record_type` of the audit events that go with the records.
RECORD_TYPES = (
    "item",
    "item_replacement",
    "device_group",
    "device_group_member",
    "network",
    "address",
    "catalog_entry",
    "vendor",
    "owner",
    "owner_member",
    "region",
    "site",
    "location",
    "contact",
    "operator",
    "contact_assignment",
    "tag",
    "import_job",
    "agreement",
    "contract",
    "contract_coverage",
    "purchase_request",
    "purchase_line",
    "external_system",
    "registration",
    "capacity_line",
    "capacity_record",
    "contract_contact",
)


def counts(db: Session) -> dict[str, int]:
    """Return how many rows each table that a reset clears holds."""
    return {
        model.__tablename__: db.scalar(select(func.count()).select_from(model)) or 0
        for model in CLEARED
    }


def clear_inventory(db: Session, context: AuditContext, backup: str) -> dict[str, int]:
    """Remove the inventory and its history, and record that it was done.

    Accounts, roles, settings, choices and lifecycle rules are left as they are. One
    audit event says what was removed and names the backup that still holds it.
    """
    removed = counts(db)
    # A catalog entry may name another as its successor, an item may be in another, a
    # group, a region and a location within another, so no order empties those tables.
    db.execute(update(CatalogEntry).values(successor_hid=None))
    db.execute(update(Item).values(parent_item_hid=None))
    db.execute(update(DeviceGroup).values(parent_group_hid=None))
    db.execute(update(Region).values(parent_region_hid=None))
    db.execute(update(Location).values(parent_location_hid=None))
    for model in CLEARED:
        db.execute(delete(model))
    removed["audit_events"] = (
        db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.record_type.in_(RECORD_TYPES))
        )
        or 0
    )
    db.execute(delete(AuditEvent).where(AuditEvent.record_type.in_(RECORD_TYPES)))
    audit.record(
        db,
        context,
        "reset",
        "inventory",
        None,
        [
            *(change(name, count, 0) for name, count in removed.items() if count),
            change("backup", None, backup),
        ],
    )
    return removed
