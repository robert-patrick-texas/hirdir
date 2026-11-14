// Support agreements, the contracts grouped into them, and the coverage of items under
// a contract, as words. A contract is one record that is applied to many items, and what
// a contract in an agreement says nothing of, it has from the agreement: the server
// resolves that when the contract is read and says where each value came from. Nothing
// is worked out here but how to say it, and what a form sends.

import type { Schemas } from "../api/client";
import { type FilterNode, filterText } from "./filter";
import type { FieldSpec, Option } from "./patch";

export type Agreement = Schemas["AgreementOut"];
export type Contract = Schemas["ContractOut"];
export type Coverage = Schemas["CoverageOut"];
export type CoverageRef = Schemas["CoverageRef"];
export type Term = Schemas["ContractTerm"];
export type ContractRenew = Schemas["ContractRenew"];

/** What a person says of a contract or of an agreement. The clock never changes it. */
export const CONTRACT_STATUSES: readonly Option[] = [
  { value: "active", label: "Active" },
  { value: "pending", label: "Pending" },
  { value: "expired", label: "Expired" },
  { value: "cancelled", label: "Cancelled" },
];

export function contractPath(hid: string): string {
  return `/contracts/${encodeURIComponent(hid)}`;
}

export function agreementPath(hid: string): string {
  return `/agreements/${encodeURIComponent(hid)}`;
}

/** The contracts of one agreement, in the grid of contracts. */
export function contractsOfPath(agreementHid: string): string {
  return `/contracts?filter=${encodeURIComponent(`agreement_hid:eq:${agreementHid}`)}`;
}

/** The contracts that stand by themselves, in the grid of contracts. */
export const STANDALONE = "agreement_hid:empty:true";

/** The items a contract covers today, in the grid of items. */
export function coveredItemsPath(contractHid: string): string {
  const filter: FilterNode = { field: "contract.hid", op: "eq", value: contractHid };
  return `/items?filter=${encodeURIComponent(filterText(filter))}&minor=1`;
}

/** The fields a contract may have from its agreement, each by itself. */
export type Inherited = keyof Contract["effective"];

/** Those fields as people read them, in the order a page shows them. */
export const INHERITED: ReadonlyArray<{ field: Inherited; label: string }> = [
  { field: "reseller_hid", label: "Reseller" },
  { field: "starts_on", label: "Starts on" },
  { field: "ends_on", label: "Ends on" },
  { field: "support_level", label: "Support level" },
  { field: "account_manager", label: "Account manager" },
  { field: "support_contact", label: "Support contact" },
  { field: "support_url", label: "Support URL" },
];

/**
 * How a value in force stands: the contract's own, had from its agreement, its own where
 * the agreement has one too, or nothing at all.
 */
export type Standing = "own" | "inherited" | "override" | "none";

export interface InForce {
  standing: Standing;
  /** The value in force, as text: a reseller by its name. Blank when there is none. */
  text: string;
  /** For an override: what the agreement has, which the contract's own takes the place of. */
  overridden: string;
}

/** What an agreement itself says of one of the fields its contracts may have from it. */
export function agreementValue(
  agreement: Pick<Agreement, Exclude<Inherited, "reseller_hid"> | "reseller"> | null | undefined,
  field: Inherited,
): string {
  if (!agreement) return "";
  if (field === "reseller_hid") return agreement.reseller?.name ?? "";
  return agreement[field] ?? "";
}

/**
 * One field of a contract as it is in force, with how it stands. The server says where
 * the value came from; that an own value overrides one of the agreement's is seen from
 * the agreement, when the page has read it.
 */
export function inForce(
  contract: Pick<Contract, "effective">,
  field: Inherited,
  agreement?: Parameters<typeof agreementValue>[0],
): InForce {
  const effective = contract.effective[field];
  const value = effective.value;
  const text =
    field === "reseller_hid"
      ? (contract.effective.reseller_hid.label ?? (typeof value === "string" ? value : ""))
      : typeof value === "string"
        ? value
        : "";
  if (effective.source === "agreement" && text !== "") {
    return { standing: "inherited", text, overridden: "" };
  }
  if (effective.source === "own" && text !== "") {
    const above = agreementValue(agreement, field);
    return above === ""
      ? { standing: "own", text, overridden: "" }
      : { standing: "override", text, overridden: above };
  }
  return { standing: "none", text: "", overridden: "" };
}

/** The fields of a contract that are its own where its agreement has one too. */
export function overrides(
  contract: Pick<Contract, "effective">,
  agreement: Parameters<typeof agreementValue>[0],
): Inherited[] {
  return INHERITED.map(({ field }) => field).filter(
    (field) => inForce(contract, field, agreement).standing === "override",
  );
}

/**
 * A period as text. A blank start is from the beginning and a blank end until further
 * notice, as a contract has them.
 */
export function periodText(
  starts: string | boolean | null | undefined,
  ends: string | boolean | null | undefined,
): string {
  const from = typeof starts === "string" ? starts : "";
  const to = typeof ends === "string" ? ends : "";
  if (from && to) return `${from} to ${to}`;
  if (from) return `From ${from}`;
  if (to) return `Until ${to}`;
  return "Open";
}

/** What to say under the input of a field a contract may have from its agreement. */
export function agreementHint(contract: Contract | null, field: Inherited): string | undefined {
  if (!contract?.agreement) return undefined;
  const mine = inForce(contract, field);
  if (mine.standing === "own" || mine.standing === "override") {
    return `Set here. Clear it to have what ${contract.agreement.name} says.`;
  }
  if (mine.standing === "inherited") {
    return `Blank has ${mine.text} from ${contract.agreement.name}.`;
  }
  return `Blank, and ${contract.agreement.name} says nothing of it either.`;
}

/** The fields the form of a renewal asks for: what a new term usually changes. */
export const RENEW_SPECS: readonly FieldSpec[] = [
  {
    name: "number",
    label: "New number",
    kind: "text",
    maxLength: 200,
    hint: "The number of the new term. Left as it is, the contract keeps its number.",
  },
  { name: "starts_on", label: "New period: starts on", kind: "date" },
  { name: "ends_on", label: "New period: ends on", kind: "date" },
  {
    name: "purchase_reference",
    label: "Purchase reference",
    kind: "text",
    maxLength: 200,
    hint: "The request or the tracking number the new term is bought under. The one of the term before stays with that term.",
  },
  { name: "annual_cost", label: "Annual cost", kind: "decimal", places: 2 },
  { name: "support_level", label: "Support level", kind: "text", maxLength: 200 },
];

/**
 * Why a renewal cannot be sent as it stands, or blank when it can: it gives the contract
 * a new number, a new period, or both, and the server refuses one that gives neither.
 */
export function renewProblem(changed: readonly string[]): string {
  const renews = ["number", "starts_on", "ends_on"].some((name) => changed.includes(name));
  return renews ? "" : "A renewal gives the contract a new number, a new period, or both.";
}

/**
 * The body of `POST /contracts/{hid}/coverage` for several items at once, each for the
 * same days. A date left blank is left out, and the coverage then has the contract's,
 * whatever that becomes when the contract is renewed.
 */
export function coverBody(
  itemHids: readonly string[],
  starts: string,
  ends: string,
): Schemas["CoverageAdd"] {
  const from = starts.trim();
  const to = ends.trim();
  return {
    items: itemHids.map((item_hid) => ({
      item_hid,
      ...(from === "" ? {} : { starts_on: from }),
      ...(to === "" ? {} : { ends_on: to }),
    })),
  };
}

/** The most items one request puts under a contract, as the server has it. */
export const COVER_AT_ONCE = 10_000;

/**
 * The days of a coverage as a cell shows them: the day in force, and whether it is the
 * coverage's own or the contract's.
 */
export function coverageDay(
  own: string | null | undefined,
  effective: string | null | undefined,
): { text: string; inherited: boolean } {
  if (own) return { text: own, inherited: false };
  return { text: effective ?? "", inherited: Boolean(effective) };
}

/** Whether a coverage can still be ended: it has no end of its own that has passed. */
export function endable(coverage: Pick<Coverage, "ends_on">, today: string): boolean {
  return !coverage.ends_on || coverage.ends_on >= today;
}

/** A contract as a search offers it: its number, then its vendor. */
export function contractLabel(contract: {
  number: string;
  vendor: { name: string } | string;
}): string {
  const vendor = typeof contract.vendor === "string" ? contract.vendor : contract.vendor.name;
  return [contract.number, vendor].filter(Boolean).join(" · ");
}

/**
 * The numbers of the contracts that cover an item today, each once, as the Contracts
 * column of the item grid shows them.
 */
export function coveringNumbers(coverage: readonly CoverageRef[]): string {
  const numbers: string[] = [];
  for (const one of coverage) {
    if (one.in_force && !numbers.includes(one.contract.number)) numbers.push(one.contract.number);
  }
  return numbers.join(", ");
}
