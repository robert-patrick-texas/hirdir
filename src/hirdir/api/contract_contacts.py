"""The routes of the contacts of agreements and of contracts: contact records named in a
role, account manager or support contact."""

from fastapi import APIRouter

from hirdir.api import lists, shapes
from hirdir.api import records as r
from hirdir.api.deps import Audit, Db, Inventory, Viewer
from hirdir.api.idempotent import IdempotentRoute
from hirdir.api.schemas import Page
from hirdir.db.models import Contact, ContractContact
from hirdir.domain import contract_contacts as named

agreements = APIRouter(prefix="/agreements", tags=["Contracts"], route_class=IdempotentRoute)
contracts = APIRouter(prefix="/contracts", tags=["Contracts"], route_class=IdempotentRoute)


def _changes(body: r.Model) -> dict:
    return body.model_dump(exclude={"row_version"}, exclude_unset=True)


def _listed(field: str, hid: str, db: Db, limit: int, offset: int) -> Page[r.ContractContactOut]:
    named.holder(db, field, hid)
    found = shapes.contract_contacts_out(db, field, hid)
    return Page(items=found[offset : offset + limit], total=len(found), limit=limit, offset=offset)


def _out(db: Db, link: ContractContact) -> r.ContractContactOut:
    contact = db.get_one(Contact, link.contact_hid)
    return shapes.contract_contact_out((link, contact))


@agreements.get("/{hid}/contacts")
def list_agreement_contacts(
    hid: str, _: Viewer, db: Db, limit: lists.Limit = 100, offset: lists.Offset = 0
) -> Page[r.ContractContactOut]:
    """List the contact records an agreement names: by role, then by priority. Every
    contract in it that names nobody of its own in a role has these."""
    return _listed(named.AGREEMENT, hid, db, limit, offset)


@agreements.post("/{hid}/contacts", status_code=201)
def add_agreement_contact(
    hid: str, body: r.ContractContactAdd, _: Inventory, context: Audit, db: Db
) -> r.ContractContactOut:
    """Name a contact record for an agreement, as an account manager or a support
    contact. A contact is named once for one agreement and one role."""
    return _out(db, named.add(db, context, named.AGREEMENT, hid, body.model_dump()))


@agreements.patch("/{hid}/contacts/{link_hid}")
def update_agreement_contact(
    hid: str, link_hid: str, body: r.ContractContactPatch, _: Inventory, context: Audit, db: Db
) -> r.ContractContactOut:
    """Change the role, the priority or the contact of a naming of an agreement."""
    changed = named.update(
        db, context, named.AGREEMENT, hid, link_hid, body.row_version, _changes(body)
    )
    return _out(db, changed)


@agreements.delete("/{hid}/contacts/{link_hid}", status_code=204)
def remove_agreement_contact(hid: str, link_hid: str, _: Inventory, context: Audit, db: Db) -> None:
    """Remove a naming of an agreement that was a mistake. The audit event of the
    removal holds what it was."""
    named.remove(db, context, named.AGREEMENT, hid, link_hid)


@contracts.get("/{hid}/contacts")
def list_contract_contacts(
    hid: str, _: Viewer, db: Db, limit: lists.Limit = 100, offset: lists.Offset = 0
) -> Page[r.ContractContactOut]:
    """List the contact records a contract names of its own: by role, then by
    priority. Those in force, its own or its agreement's, are in `effective` on the
    contract."""
    return _listed(named.CONTRACT, hid, db, limit, offset)


@contracts.post("/{hid}/contacts", status_code=201)
def add_contract_contact(
    hid: str, body: r.ContractContactAdd, _: Inventory, context: Audit, db: Db
) -> r.ContractContactOut:
    """Name a contact record for a contract, as an account manager or a support
    contact. Once it names anybody in a role, it has its own in that role in place of
    its agreement's."""
    return _out(db, named.add(db, context, named.CONTRACT, hid, body.model_dump()))


@contracts.patch("/{hid}/contacts/{link_hid}")
def update_contract_contact(
    hid: str, link_hid: str, body: r.ContractContactPatch, _: Inventory, context: Audit, db: Db
) -> r.ContractContactOut:
    """Change the role, the priority or the contact of a naming of a contract."""
    changed = named.update(
        db, context, named.CONTRACT, hid, link_hid, body.row_version, _changes(body)
    )
    return _out(db, changed)


@contracts.delete("/{hid}/contacts/{link_hid}", status_code=204)
def remove_contract_contact(hid: str, link_hid: str, _: Inventory, context: Audit, db: Db) -> None:
    """Remove a naming of a contract that was a mistake. The audit event of the removal
    holds what it was. A contract that names nobody left in a role has its agreement's."""
    named.remove(db, context, named.CONTRACT, hid, link_hid)


ROUTERS = (agreements, contracts)
