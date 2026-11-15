"""The routes of contracts, and of the coverage of items under them."""

from typing import Any

from fastapi import APIRouter

from hirdir.api import lists, shapes
from hirdir.api import records as r
from hirdir.api.deps import Audit, Db, Inventory, Viewer
from hirdir.api.idempotent import IdempotentRoute
from hirdir.api.lists import Listed
from hirdir.api.schemas import Page
from hirdir.db.models import ContractCoverage
from hirdir.domain import contracts
from hirdir.io import fields

agreements = APIRouter(prefix="/agreements", tags=["Contracts"], route_class=IdempotentRoute)
router = APIRouter(prefix="/contracts", tags=["Contracts"], route_class=IdempotentRoute)
coverage = APIRouter(prefix="/contract-coverage", tags=["Contracts"])


def _changes(body: r.Model) -> dict:
    return body.model_dump(exclude={"row_version"}, exclude_unset=True)


def _page(items: list[Any], total: int, listed: lists.ListRequest, model: Any) -> Any:
    return lists.narrowed(
        Page(items=items, total=total, limit=listed.limit, offset=listed.offset), listed, model
    )


@agreements.get("")
def list_agreements(_: Viewer, db: Db, listed: Listed) -> Page[r.AgreementOut]:
    """List support agreements, by name unless a sort says otherwise."""
    page, total = lists.read(db, fields.AGREEMENTS, listed)
    return _page(shapes.agreements_out(db, page), total, listed, r.AgreementOut)


@agreements.post("", status_code=201)
def create_agreement(
    body: r.AgreementCreate, _: Inventory, context: Audit, db: Db
) -> r.AgreementOut:
    """Create a support agreement with a vendor, such as an enterprise agreement.
    Contracts are grouped into it by their `agreement_hid`."""
    made = contracts.create_agreement(db, context, body.model_dump())
    return shapes.agreements_out(db, [made])[0]


@agreements.get("/{hid}")
def get_agreement(hid: str, _: Viewer, db: Db) -> r.AgreementOut:
    """Return one support agreement. Its contracts are `GET /contracts` with
    `agreement_hid` in the filter."""
    return shapes.agreements_out(db, [contracts.get_agreement(db, hid)])[0]


@agreements.patch("/{hid}")
def update_agreement(
    hid: str, body: r.AgreementPatch, _: Inventory, context: Audit, db: Db
) -> r.AgreementOut:
    """Change an agreement. Every contract in it that says nothing of its own has the
    change at once, and so has every item under those contracts: none is written to."""
    changed = contracts.update_agreement(db, context, hid, body.row_version, _changes(body))
    return shapes.agreements_out(db, [changed])[0]


@agreements.post("/{hid}/renew")
def renew_agreement(
    hid: str, body: r.AgreementRenew, _: Inventory, context: Audit, db: Db
) -> r.AgreementRenewed:
    """Renew an agreement: its new period, and its new number where it has one.

    The contracts that share its period follow it, each as `members` says: under its
    number (`same`, the default), with a new number that begins with the new term
    (`new_number`), or let go with the present term (`ends`), and the items under them,
    but those that are not to be renewed, whose coverage ends with the present term. A
    period that begins after today is kept as the next term, and the present one runs
    on until then. `withdraw` withdraws a term that is still to begin, and the new
    numbers that wait on it.
    """
    changes = _changes(body)
    members = changes.pop("members", None) or []
    renewed = contracts.renew_agreement(db, context, hid, body.row_version, changes, members)
    out = shapes.agreements_out(db, [renewed.record])[0]
    return r.AgreementRenewed(
        **out.model_dump(),
        left_behind=renewed.left_behind,
        members=[
            r.MemberRenewedOut.model_validate(one, from_attributes=True) for one in renewed.members
        ],
    )


@agreements.get("/{hid}/terms")
def agreement_terms(hid: str, _: Viewer, db: Db) -> list[r.AgreementTerm]:
    """List the terms an agreement had before it was renewed, the latest first: its
    purchase history."""
    return shapes.agreement_terms_out(db, contracts.get_agreement(db, hid))


@agreements.post("/{hid}/retire")
def retire_agreement(
    hid: str, body: r.RowVersion, _: Inventory, context: Audit, db: Db
) -> r.AgreementOut:
    """Retire an agreement, once no contract that is not retired is in it."""
    retired = contracts.retire_agreement(db, context, hid, body.row_version)
    return shapes.agreements_out(db, [retired])[0]


@router.get("")
def list_contracts(_: Viewer, db: Db, listed: Listed) -> Page[r.ContractOut]:
    """List contracts, by number unless a sort says otherwise."""
    page, total = lists.read(db, fields.CONTRACTS, listed)
    return _page(shapes.contracts_out(db, page), total, listed, r.ContractOut)


@router.post("", status_code=201)
def create_contract(body: r.ContractCreate, _: Inventory, context: Audit, db: Db) -> r.ContractOut:
    """Create a contract, by itself or in an agreement. Items are put under it with
    its coverage."""
    given = body.model_dump()
    if given["vendor_hid"] is None:
        del given["vendor_hid"]
    return shapes.contract_out(db, contracts.create_contract(db, context, given))


@router.get("/{hid}")
def get_contract(hid: str, _: Viewer, db: Db) -> r.ContractOut:
    """Return one contract."""
    return shapes.contract_out(db, contracts.get_contract(db, hid))


@router.patch("/{hid}")
def update_contract(
    hid: str, body: r.ContractPatch, _: Inventory, context: Audit, db: Db
) -> r.ContractOut:
    """Change a contract. Every item under it shows the change at once, and no item
    and no coverage is written to."""
    changed = contracts.update_contract(db, context, hid, body.row_version, _changes(body))
    return shapes.contract_out(db, changed)


@router.post("/{hid}/renew")
def renew_contract(
    hid: str, body: r.ContractRenew, _: Inventory, context: Audit, db: Db
) -> r.ContractRenewed:
    """Renew a contract: give it its new number, its new period, or both.

    It is one change of the one record, and nothing is written to any item. A period
    that begins today or earlier is in force at once. One that begins after today is
    kept as the next term: the present number and period stay in force until that
    day, so the items are covered throughout, and from that day the contract has the
    new ones. `withdraw` withdraws a term that is still to begin. The terms it had
    are kept in the audit trail, and are listed by `GET /contracts/{hid}/terms`.
    """
    renewed = contracts.renew_contract(db, context, hid, body.row_version, _changes(body))
    out = shapes.contract_out(db, renewed.record)
    return r.ContractRenewed(**out.model_dump(), left_behind=renewed.left_behind)


@router.get("/{hid}/terms")
def contract_terms(hid: str, _: Viewer, db: Db) -> list[r.ContractTerm]:
    """List the terms a contract had before it was renewed, the latest first: its
    purchase history. Each has the dates it had in force: where the contract had none
    of its own, those of the agreement's term that was in force when it began."""
    return shapes.terms_out(db, contracts.get_contract(db, hid))


@router.post("/{hid}/retire")
def retire_contract(
    hid: str, body: r.RowVersion, _: Inventory, context: Audit, db: Db
) -> r.ContractOut:
    """Retire a contract. Its coverages stay on record, and cover nothing any more."""
    return shapes.contract_out(db, contracts.retire_contract(db, context, hid, body.row_version))


@router.get("/{hid}/coverage")
def list_coverage(hid: str, _: Viewer, db: Db, listed: Listed) -> Page[r.CoverageOut]:
    """List the items under a contract, with the days of each: filtered, sorted and
    paged as a list is. `in_force:eq:true` keeps to what it covers today."""
    contracts.get_contract(db, hid)
    page, total = lists.read(
        db, fields.COVERAGE, listed, also=[ContractCoverage.contract_hid == hid]
    )
    return _page(shapes.coverage_out(db, page), total, listed, r.CoverageOut)


@router.post("/{hid}/coverage", status_code=201)
def add_coverage(
    hid: str, body: r.CoverageAdd, _: Inventory, context: Audit, db: Db
) -> list[r.CoverageOut]:
    """Put items under a contract, several at a time: all of them, or none.

    A coverage with no dates of its own is for the contract's period, whatever that
    becomes when the contract is renewed.
    """
    made = contracts.add_coverage(
        db, context, hid, [entry.model_dump(exclude_unset=True) for entry in body.items]
    )
    return shapes.coverage_out(db, made)


@router.patch("/{hid}/coverage/{coverage_hid}")
def update_coverage(
    hid: str, coverage_hid: str, body: r.CoveragePatch, _: Inventory, context: Audit, db: Db
) -> r.CoverageOut:
    """Change the days of a coverage. It is ended by giving it `ends_on`. Clearing
    `left_service` says that the vendor has been told the item has left."""
    changed = contracts.update_coverage(
        db, context, hid, coverage_hid, body.row_version, _changes(body)
    )
    return shapes.coverage_out(db, [changed])[0]


@router.delete("/{hid}/coverage/{coverage_hid}", status_code=204)
def remove_coverage(hid: str, coverage_hid: str, _: Inventory, context: Audit, db: Db) -> None:
    """Remove a coverage that was a mistake: an item put under the wrong contract. The
    audit event of the removal holds what it was. A coverage that was true for a time
    is ended with a date instead."""
    contracts.remove_coverage(db, context, hid, coverage_hid)


@coverage.get("")
def list_all_coverage(_: Viewer, db: Db, listed: Listed) -> Page[r.CoverageOut]:
    """List coverage under every contract: that of one item with `item_hid` in the
    filter, that of one contract with `contract_hid`."""
    page, total = lists.read(db, fields.COVERAGE, listed)
    return _page(shapes.coverage_out(db, page), total, listed, r.CoverageOut)


ROUTERS = (agreements, router, coverage)
