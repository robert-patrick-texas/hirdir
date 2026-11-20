"""Reset: clearing the inventory so that a site can start over.

This is the one place where records are deleted. It is reached from `hirdir admin
reset` on the server and from nowhere else: no route calls it. A site loads test data,
tries things out, clears it, and enters its own.

Every table is named here, as one that a reset clears or one that it keeps. A table
that is in neither list fails a test, so that a release which adds a record has to say
which it is.
"""

from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
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
    KeptAnswer,
    LifecycleRule,
    Location,
    Network,
    Operator,
    Owner,
    OwnerMember,
    PurchaseLine,
    PurchaseRequest,
    ReferenceAttachment,
    ReferenceFile,
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
    # References and the records they are on (P-158); their content goes with them.
    ReferenceAttachment,
    ReferenceFile,
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
    KeptAnswer,
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
    # Circuits, their carriers, cost lines and devices, and circuit groups (0.8.0).
    "circuit",
    "circuit_carrier",
    "circuit_cost",
    "circuit_device",
    "circuit_group",
    "circuit_group_member",
    # The contacts of carriers and of circuits (P-149).
    "vendor_contact",
    "circuit_contact",
    # References (P-158).
    "reference_file",
)


# What a reset clears that is no record of the inventory: what was asked of it, and
# what the server keeps of it for itself. An inventory that holds only these is empty,
# as `hirdir admin load-examples` asks it to be (P-166): a preview that was never
# applied, a sign-in that saw the renewal alert, or the week's record of a capacity
# balance of nothing mixes nothing with the examples.
BOOKKEEPING: tuple[Any, ...] = (
    ImportRow,
    ImportJob,
    IdempotencyKey,
    KeptAnswer,
    RenewalAlertView,
    CapacityRecord,
)


def _which(model: Any) -> tuple[Any, ...]:
    """Return what picks the rows of a table that a reset clears: all of them, but for the
    contacts that are users', which are kept with the accounts, as the person each user is
    (P-172)."""
    if model is Contact:
        return (Contact.hid.not_in(select(User.contact_hid).where(User.contact_hid.is_not(None))),)
    return ()


def _count(db: Session, model: Any) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*_which(model))) or 0


def counts(db: Session) -> dict[str, int]:
    """Return how many rows each table that a reset clears holds."""
    return {model.__tablename__: _count(db, model) for model in CLEARED}


def held(db: Session) -> dict[str, int]:
    """Return how many records of the inventory each table holds, of those that hold any:
    every table that a reset clears, but for its bookkeeping. Nothing, when it is empty."""
    found = {}
    for model in CLEARED:
        if model in BOOKKEEPING:
            continue
        count = _count(db, model)
        if count:
            found[model.__tablename__] = count
    return found


def clear_inventory(db: Session, context: AuditContext, backup: str) -> dict[str, int]:
    """Remove the inventory and its history, and record that it was done.

    Accounts, roles, settings, choices and lifecycle rules are left as they are, and so
    is the contact each user is, with its history. One audit event says what was removed
    and names the backup that still holds it.
    """
    removed = counts(db)
    # A catalog entry may name another as its successor, an item may be in another, a
    # group, a region and a location within another, so no order empties those tables.
    # And an item may run on a group, which a group's master that was seen names an
    # item against: neither of the two tables can go first while one names the other.
    db.execute(update(CatalogEntry).values(successor_hid=None))
    db.execute(
        update(Item).values(
            parent_item_hid=None,
            host_item_hid=None,
            host_group_hid=None,
            observed_host_hid=None,
            host_observed_at=None,
        )
    )
    db.execute(update(DeviceGroup).values(parent_group_hid=None))
    db.execute(update(Region).values(parent_region_hid=None))
    db.execute(update(Location).values(parent_location_hid=None))
    people = select(User.contact_hid).where(User.contact_hid.is_not(None))
    for model in CLEARED:
        db.execute(delete(model).where(*_which(model)))
    # The history of a contact that is kept stays with it.
    gone = and_(
        AuditEvent.record_type.in_(RECORD_TYPES),
        or_(AuditEvent.record_type != "contact", AuditEvent.record_hid.not_in(people)),
    )
    removed["audit_events"] = (
        db.scalar(select(func.count()).select_from(AuditEvent).where(gone)) or 0
    )
    db.execute(delete(AuditEvent).where(gone))
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
