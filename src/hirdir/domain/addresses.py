"""Networks and addresses: the IPv4 and IPv6 addresses of items and of device groups.

`hirdir` is not an address manager. It records the addresses of what it tracks, each
under an optional network label, and nothing about prefixes, pools or allocation. The
same address under two networks is two addresses. The same address twice under one
network is accepted, because shared and virtual addresses are real, and is reported.
"""

import ipaddress
from typing import Any, Final, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hirdir import ids
from hirdir.db.models import Address, DeviceGroup, Item, Network
from hirdir.domain import audit, records
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Conflict, Invalid, NotFound

NETWORK_TYPE = "network"
RECORD_TYPE = "address"
KINDS = ("network", "vrf", "other")
ROLES = ("management", "loopback", "secondary", "virtual")
MANAGEMENT = "management"
NETWORK_FIELDS = ("label", "kind")
FIELDS = ("item_hid", "group_hid", "address", "network_hid", "role", "is_primary")
HOLDERS = ("item_hid", "group_hid")
UNSET: Final[Any] = object()


def canonical(text: Any) -> str:
    """Return an address in the one form it is stored in, or raise ValueError.

    A prefix length is not part of an address here, and neither is the zone of an
    IPv6 link-local address.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("an IPv4 or IPv6 address")
    given = text.strip()
    if "/" in given or "%" in given:
        raise ValueError("an IPv4 or IPv6 address, with no prefix length")
    try:
        return str(ipaddress.ip_address(given))
    except ValueError:
        raise ValueError("an IPv4 or IPv6 address, such as 192.0.2.10 or 2001:db8::10") from None


def comparable(text: str) -> str:
    """Return a whole address in its stored form, and part of one as it was written.

    A filter may look for `192.0.2.` as a prefix, which is no address, so what cannot
    be read as one is compared as the text it is.
    """
    try:
        return canonical(text)
    except ValueError:
        return text.strip().lower()


# --- networks ------------------------------------------------------------------------


def get_network(db: Session, hid: str) -> Network:
    """Return the network with hid."""
    network = db.get(Network, hid)
    if network is None:
        raise NotFound(f"there is no network {hid}")
    return network


def find_network(db: Session, text: str) -> Network | None:
    """Return the network a label names, or the one with an HID."""
    if ids.is_hid(text):
        network = db.get(Network, text)
        if network is not None:
            return network
    return db.scalar(select(Network).where(Network.label_key == records.key(text)))


def uses(db: Session, network_hids: list[str]) -> dict[str, int]:
    """Return how many addresses are under each of the networks."""
    counts = dict.fromkeys(network_hids, 0)
    if network_hids:
        counted = db.execute(
            select(Address.network_hid, func.count())
            .where(Address.network_hid.in_(network_hids))
            .group_by(Address.network_hid)
        )
        for network_hid, count in counted:
            if network_hid is not None:
                counts[network_hid] = count
    return counts


def _checked_network(
    db: Session, fields: dict[str, Any], network: Network | None
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if "label" in fields:
        label = records.clean(fields["label"])
        if label is None:
            raise Invalid("the label is not acceptable", {"label": "must not be blank"})
        taken = db.scalar(select(Network).where(Network.label_key == records.key(label)))
        if taken is not None and (network is None or taken.hid != network.hid):
            raise Conflict(
                f"there is already a network {taken.label}",
                {"label": "another network has this label"},
            )
        values["label"] = label
        values["label_key"] = records.key(label)
    if "kind" in fields:
        kind = records.key(str(fields["kind"] or KINDS[0]))
        if kind not in KINDS:
            raise Invalid("the kind is not acceptable", {"kind": f"one of {', '.join(KINDS)}"})
        values["kind"] = kind
    return values


def create_network(db: Session, context: AuditContext, fields: dict[str, Any]) -> Network:
    """Create a network label."""
    network = Network(**_checked_network(db, {"label": None, **fields}, None))
    records.created(db, context, NETWORK_TYPE, network, NETWORK_FIELDS)
    return network


def update_network(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> Network:
    """Change a network label. Every address under it is under the new label at once."""
    network = get_network(db, hid)
    values = _checked_network(db, fields, network)
    records.apply(db, context, NETWORK_TYPE, network, row_version, values)
    return network


def delete_network(db: Session, context: AuditContext, hid: str) -> None:
    """Remove a network that no address is under."""
    network = get_network(db, hid)
    count = uses(db, [hid])[hid]
    if count:
        raise Conflict(
            f"{count} addresses are under {network.label}; move or remove them first",
            {"label": "a network with addresses under it is not removed"},
        )
    audit.record(
        db,
        context,
        "delete",
        NETWORK_TYPE,
        network.hid,
        [change(name, getattr(network, name), None) for name in NETWORK_FIELDS],
    )
    db.delete(network)
    db.flush()


# --- addresses -----------------------------------------------------------------------


def get_address(db: Session, hid: str) -> Address:
    """Return the address with hid."""
    address = db.get(Address, hid)
    if address is None:
        raise NotFound(f"there is no address {hid}")
    return address


def _holder(db: Session, fields: dict[str, Any]) -> dict[str, Any]:
    """Return the item or the group a new address belongs to: exactly one of the two."""
    given = {name: fields.get(name) or None for name in HOLDERS}
    if sum(1 for hid in given.values() if hid) != 1:
        raise Invalid(
            "an address belongs to an item or to a group",
            {"item_hid": "give an item or a group, and not both"},
        )
    for name, model, what in (("item_hid", Item, "item"), ("group_hid", DeviceGroup, "group")):
        hid = given[name]
        if hid is None:
            continue
        holder = db.get(model, hid)
        if holder is None:
            raise Invalid(f"there is no such {what}", {name: f"there is no {what} {hid}"})
        if holder.record_status == "retired":
            raise Invalid(f"the {what} is retired", {name: f"this {what} is retired"})
    return given


def _checked(db: Session, fields: dict[str, Any], address: Address | None) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if "address" in fields:
        try:
            values["address"] = canonical(fields["address"])
        except ValueError as error:
            raise Invalid("the address is not acceptable", {"address": str(error)}) from None
    if "network_hid" in fields:
        hid = fields["network_hid"] or None
        if hid is not None and db.get(Network, hid) is None:
            raise Invalid("there is no such network", {"network_hid": f"there is no network {hid}"})
        values["network_hid"] = hid
    if "role" in fields:
        role = records.key(str(fields["role"] or MANAGEMENT))
        if role not in ROLES:
            raise Invalid("the role is not acceptable", {"role": f"one of {', '.join(ROLES)}"})
        values["role"] = role
    if "is_primary" in fields:
        values["is_primary"] = bool(fields["is_primary"])
    role = values.get("role", address.role if address is not None else MANAGEMENT)
    primary = values.get("is_primary", address.is_primary if address is not None else False)
    if primary and role != MANAGEMENT:
        raise Invalid(
            "only a management address is primary",
            {"is_primary": "the primary address of a record is one with the role management"},
        )
    return values


def of_holders(db: Session, field: str, hids: list[str]) -> dict[str, list[Address]]:
    """Return the addresses of each item, or of each group, the primary one first."""
    found: dict[str, list[Address]] = {hid: [] for hid in hids}
    if not hids:
        return found
    column = getattr(Address, field)
    rows = db.scalars(
        select(Address)
        .where(column.in_(hids))
        .order_by(Address.is_primary.desc(), Address.role, Address.address, Address.hid)
    )
    for address in rows:
        found[getattr(address, field)].append(address)
    return found


def family(address: str) -> Literal[4, 6]:
    """Return the family of a stored address: 4 or 6."""
    return 6 if ":" in address else 4


def _of_family(which: int) -> Any:
    """Return the condition that a stored address is of a family."""
    return Address.address.contains(":") if which == 6 else ~Address.address.contains(":")


def primary_of(db: Session, field: str, hid: str, which: int) -> Address | None:
    """Return the primary management address of one family of an item or of a group."""
    return db.scalar(
        select(Address)
        .where(getattr(Address, field) == hid, Address.is_primary, _of_family(which))
        .limit(1)
    )


def _one_primary(db: Session, context: AuditContext, address: Address) -> None:
    """Take the mark off whichever other address of the record was primary in its family.

    A device may be managed over IPv4, over IPv6 or over both, so there is one primary
    of each.
    """
    field = "item_hid" if address.item_hid else "group_hid"
    others = db.scalars(
        select(Address).where(
            getattr(Address, field) == getattr(address, field),
            Address.is_primary,
            _of_family(family(address.address)),
            Address.hid != address.hid,
        )
    )
    for other in others:
        records.apply(db, context, RECORD_TYPE, other, None, {"is_primary": False})


def create_address(db: Session, context: AuditContext, fields: dict[str, Any]) -> Address:
    """Give an item or a group an address."""
    if "address" not in fields:
        raise Invalid("the address is not acceptable", {"address": "an IPv4 or IPv6 address"})
    address = Address(**_holder(db, fields), **_checked(db, fields, None))
    records.created(db, context, RECORD_TYPE, address, FIELDS)
    if address.is_primary:
        _one_primary(db, context, address)
    return address


def update_address(
    db: Session, context: AuditContext, hid: str, row_version: int | None, fields: dict[str, Any]
) -> Address:
    """Change an address. Whose it is does not change: it is removed and given anew."""
    address = get_address(db, hid)
    for name in HOLDERS:
        if name in fields and (fields[name] or None) != getattr(address, name):
            raise Invalid(
                "whose address it is does not change",
                {name: "remove the address and give it to the other record"},
            )
    values = _checked(db, fields, address)
    records.apply(db, context, RECORD_TYPE, address, row_version, values)
    if address.is_primary:
        _one_primary(db, context, address)
    return address


def delete_address(db: Session, context: AuditContext, hid: str) -> None:
    """Remove an address. The audit event holds what it was."""
    address = get_address(db, hid)
    audit.record(
        db,
        context,
        "delete",
        RECORD_TYPE,
        address.hid,
        [
            change(name, getattr(address, name), None)
            for name in FIELDS
            if getattr(address, name) not in (None, False)
        ],
    )
    db.delete(address)
    db.flush()


def set_primary(
    db: Session,
    context: AuditContext,
    field: str,
    hid: str,
    address: str | None,
    network_hid: Any = UNSET,
    which: int | None = None,
) -> None:
    """Make an address the primary management address, of its family, of an item or a group.

    The one there is, is changed; with none, one is added. Given no address, the one
    of the family `which` is removed, and of both families when none is named. Given an
    address and a family, the address must be of that family. The network is left as
    it is unless one is named.
    """
    if address is None:
        for one in (4, 6) if which is None else (which,):
            current = primary_of(db, field, hid, one)
            if current is not None:
                delete_address(db, context, current.hid)
        return
    try:
        stored = canonical(address)
    except ValueError as error:
        raise Invalid("the address is not acceptable", {"address": str(error)}) from None
    if which is not None and family(stored) != which:
        raise Invalid(
            "the address is of the other family",
            {"address": f"an IPv{which} address; this one is IPv{family(stored)}"},
        )
    fields: dict[str, Any] = {"address": stored}
    if network_hid is not UNSET:
        fields["network_hid"] = network_hid
    current = primary_of(db, field, hid, family(stored))
    if current is not None:
        update_address(db, context, current.hid, None, fields)
    else:
        create_address(db, context, {field: hid, "role": MANAGEMENT, "is_primary": True, **fields})
