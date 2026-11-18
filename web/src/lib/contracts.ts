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
  // The term has ended and the renewal is in procurement: the vendor still gives
  // support, by escalation, and the contract covers past its end date meanwhile.
  { value: "renewal_pending", label: "Renewal pending" },
  { value: "pending", label: "Pending" },
  { value: "expired", label: "Expired" },
  { value: "cancelled", label: "Cancelled" },
];

/** The status of a contract whose renewal is late and in procurement. */
export const RENEWAL_PENDING = "renewal_pending";

/** What a person is told wherever cover is under a contract whose renewal is pending. */
export const RENEWAL_PENDING_NOTE = "Renewal pending: go through the account manager";

/** What is said of a contract or an agreement whose period ended while it still says active. */
export const LAPSED_NOTE =
  "Lapsed: its period has ended and its status still says Active. It covers nothing until it is renewed, or said to have expired.";

/** The contracts that have lapsed, in the grid of contracts. */
export const LAPSED = "lapsed:eq:true";

/** What began a part of the history of a contract or an agreement (D-181). */
export type BeganBy = Schemas["ContractTerm"]["began_by"];

const BEGAN_BY: Readonly<Record<BeganBy, string>> = {
  created: "Made",
  renewal: "A renewal",
  joined: "Joining an agreement",
  left: "Leaving its agreement",
};

/** What began a part of a contract's history, as people read it. */
export function beganByLabel(began: BeganBy | null | undefined): string {
  return began ? (BEGAN_BY[began] ?? began) : "";
}

/** The term of a contract or an agreement that is still to begin. */
export type NextTerm = NonNullable<Contract["next_term"]>;

/**
 * A term that is still to begin, in a sentence: the number it brings, where the renewal
 * gives another, the day it begins and the day it ends. Until that day the present
 * number and period stay in force.
 */
export function nextTermText(next: NextTerm): string {
  const as = next.number ? `Renews as ${next.number}` : "Renews";
  const until = next.ends_on ? `, until ${next.ends_on}` : ", with no end named";
  // A new number that waits on the agreement's next term has no dates of its own: the
  // days are the agreement's, as they stand, and it begins when that term does.
  const waits = next.with_agreement
    ? ", with the agreement's next term, whose dates these are"
    : "";
  return `${as} on ${next.starts_on}${until}${waits}`;
}

/**
 * What a page says where a change of a contract or an agreement that has a term still to
 * begin is refused as stale. From the day that term begins, the record is read with it,
 * at the version it will have once the term is written down: a change that was read
 * before is refused, and is not made to a term it was not meant for. Blank for a record
 * with no term to come, which only a person changes.
 */
export function staleCause(
  record: { next_term: { starts_on: string } | null },
  what: "contract" | "agreement",
): string {
  if (!record.next_term) return "";
  return `Someone changed it after you opened it, or its next term, from ${record.next_term.starts_on}, has begun: from that day the ${what} is read with that term, at a new version. Your change was not saved, so that it is not made to a term it was not meant for.`;
}

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
/** The fields a contract has from its agreement one by one. The contact lists of each
 * role are had from it as a whole, and are shown apart. */
export type Inherited = Exclude<
  keyof Contract["effective"],
  "account_managers" | "support_contacts"
>;

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
  /** For an override: what the agreement gives, which the contract's own takes the place of. */
  overridden: string;
  /**
   * For an override: the contract's own is the same as what the agreement gives. It is
   * still an override: it stays as it is when the agreement's changes.
   */
  same: boolean;
}

/**
 * What the agreement gives for one field of a contract today, as text, whether the
 * contract overrides it or not: the server answers it beside the value in force, and
 * the reseller by its name. Blank for a contract in no agreement, and where the
 * agreement has nothing.
 */
export function agreementGives(contract: Pick<Contract, "effective">, field: Inherited): string {
  if (field === "reseller_hid") {
    const reseller = contract.effective.reseller_hid;
    return reseller.from_agreement_label ?? reseller.from_agreement ?? "";
  }
  return contract.effective[field].from_agreement ?? "";
}

/**
 * One field of a contract as it is in force, with how it stands. The server says where
 * the value came from, and what the agreement gives for it: an own value is an override
 * where the agreement gives one too, also where the two are the same.
 */
export function inForce(contract: Pick<Contract, "effective">, field: Inherited): InForce {
  const effective = contract.effective[field];
  const value = effective.value;
  const text =
    field === "reseller_hid"
      ? (contract.effective.reseller_hid.label ?? (typeof value === "string" ? value : ""))
      : typeof value === "string"
        ? value
        : "";
  if (effective.source === "agreement" && text !== "") {
    return { standing: "inherited", text, overridden: "", same: false };
  }
  if (effective.source === "own" && text !== "") {
    const above = agreementGives(contract, field);
    if (above === "") return { standing: "own", text, overridden: "", same: false };
    // A reseller is the same by its HID; any other value by its text.
    const same =
      field === "reseller_hid"
        ? value === contract.effective.reseller_hid.from_agreement
        : text === above;
    return { standing: "override", text, overridden: above, same };
  }
  return { standing: "none", text: "", overridden: "", same: false };
}

/** The fields of a contract that are its own where its agreement gives one too. */
export function overrides(contract: Pick<Contract, "effective">): Inherited[] {
  return INHERITED.map(({ field }) => field).filter(
    (field) => inForce(contract, field).standing === "override",
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
  const name = contract.agreement.name;
  const mine = inForce(contract, field);
  if (mine.standing === "override") {
    return mine.same
      ? `Set here, and the same as ${name} gives. Clear it to follow ${name} when that changes.`
      : `Set here, in place of ${mine.overridden} from ${name}. Clear it to have that.`;
  }
  if (mine.standing === "own") {
    return `Set here. ${name} gives nothing for it.`;
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
    hint: "The number of the new term. Left as it is, the number stays.",
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

/** True for a renewal whose period begins after today: it is kept as the next term. */
export function startsLater(body: Pick<ContractRenew, "starts_on">, today: string): boolean {
  return typeof body.starts_on === "string" && body.starts_on > today;
}

/**
 * The body of a renewal as it is sent. A renewal whose period begins after today is the
 * next term, and says the day that term ends, or that it names none: the end the form
 * holds goes with it also where it was left as it stood, since the old end is seldom
 * the new one and the server asks for it.
 */
export function renewBody(
  built: ContractRenew,
  endsOn: string | null,
  today: string,
): ContractRenew {
  if (!startsLater(built, today) || "ends_on" in built) return built;
  return { ...built, ends_on: endsOn };
}

/**
 * What is wrong with the period of a renewal, found before it is sent: a term that is
 * still to begin ends on or after the day it starts, so the end the term before had
 * cannot stay.
 */
export function renewPeriodProblem(body: ContractRenew, today: string): string {
  if (!startsLater(body, today)) return "";
  const { starts_on: starts, ends_on: ends } = body;
  if (typeof starts === "string" && typeof ends === "string" && ends < starts) {
    return `A term that begins on ${starts} cannot end on ${ends}. Give the day the new term ends, or leave it blank for none.`;
  }
  return "";
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

/**
 * The most items one request puts under a contract until the setting is read: the
 * default of `max_items_per_request`.
 */
export const COVER_AT_ONCE = 1000;
/** The most items the page puts under a contract in one go, a request after another. */
export const COVER_MOST = 10_000;

/**
 * How many items one request may cover, add to a group or receive: the
 * `max_items_per_request` setting as `GET /settings` answers it, which the server holds
 * to, or its default until it is read or where it is not a whole number above zero.
 */
export function pieceSize(
  settings: ReadonlyArray<{ key: string; value: unknown }> | undefined,
): number {
  const value = settings?.find((setting) => setting.key === "max_items_per_request")?.value;
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : COVER_AT_ONCE;
}

/** The items to cover, in the pieces one request takes: `size` to a request. */
export function coverBatches(
  itemHids: readonly string[],
  size: number = COVER_AT_ONCE,
): string[][] {
  const piece = Number.isInteger(size) && size > 0 ? size : COVER_AT_ONCE;
  const batches: string[][] = [];
  for (let at = 0; at < itemHids.length; at += piece) {
    batches.push(itemHids.slice(at, at + piece));
  }
  return batches;
}

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

/** 0.9.6 (P-213): how an item is left out of a renewal, where an end on the last day is not. */
export const LEAVE_OUT_NOTE =
  "To leave an item out of a renewal, mark it not to be renewed before the contract is renewed (Not to be renewed, in the item's details or its model's), or end its coverage on an earlier day.";

/**
 * 0.9.6 (P-213): whether ending a coverage on `day` would change nothing, because the
 * day is the contract's own last day. The server keeps such a day as blank (D-156): the
 * coverage keeps the contract's period and follows it into a renewal. The contract's
 * end is given where the page has it; otherwise a coverage that has no end of its own
 * has the contract's in force. A coverage that has the day as its own already keeps it,
 * as the end a renewal gave an item not to be renewed (D-182).
 */
export function followsOnEnd(
  coverage: Pick<Coverage, "ends_on" | "effective_ends_on">,
  day: string,
  contractEnds?: string | null,
): boolean {
  if (day === "" || coverage.ends_on === day) return false;
  if (contractEnds) return day === contractEnds;
  return !coverage.ends_on && coverage.effective_ends_on === day;
}

/**
 * 0.9.6 (P-213): what the page says once coverages were sent an end of `day`, read from
 * what the server answered for each: a coverage whose own end is now that day was
 * ended; one the server kept with no end of its own, or with another, was not.
 */
export function endedText(day: string, answers: ReadonlyArray<Pick<Coverage, "ends_on">>): string {
  const kept = answers.filter((answer) => answer.ends_on === day).length;
  const open = answers.length - kept;
  const said: string[] = [];
  if (kept > 0) {
    said.push(
      `${kept.toLocaleString("en-US")} ${kept === 1 ? "coverage was" : "coverages were"} ended on ${day}. Nothing was removed.`,
    );
  }
  if (open > 0) {
    const which =
      kept === 0
        ? open === 1
          ? "The coverage was not ended"
          : `None of the ${open.toLocaleString("en-US")} coverages was ended`
        : `${open.toLocaleString("en-US")} ${open === 1 ? "was" : "were"} not ended`;
    said.push(
      `${which}: ${day} is the contract's own last day, so the server kept the contract's period, which follows a renewal. ${LEAVE_OUT_NOTE}`,
    );
  }
  return said.join(" ");
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

/**
 * The numbers of the contracts that still count an item that is out of service, each
 * once, as the server lists them: those that cover it past today, and those whose
 * coverage of it was ended because it left while their term still runs. The list to
 * send the vendor. Blank for an item in service.
 */
export function countedUnder(item: { out_of_service_contracts: readonly { number: string }[] }) {
  return [...new Set(item.out_of_service_contracts.map((contract) => contract.number))].join(", ");
}

/** What is said of an item that a contract still counts while it is out of service. */
export const COUNTED_NOTE =
  "Out of service, and still counted by these contracts: the list to send the vendor. A contract counts it where it covers it past today, or where its coverage was ended because the item left, until the vendor has been told, while the term of the contract runs.";

/**
 * The statuses of the contracts that cover an item today, each once, as the item grid
 * shows them: Active, or Renewal pending where the renewal is late.
 */
export function coveringStatuses(coverage: readonly CoverageRef[]): string {
  const statuses: string[] = [];
  for (const one of coverage) {
    const label =
      CONTRACT_STATUSES.find((status) => status.value === one.contract.status)?.label ??
      one.contract.status;
    if (one.in_force && !statuses.includes(label)) statuses.push(label);
  }
  return statuses.join(", ");
}

/** True for an item that a contract covers today while the renewal of that contract is pending. */
export function renewalPending(coverage: readonly CoverageRef[]): boolean {
  return coverage.some((one) => one.in_force && one.contract.status === RENEWAL_PENDING);
}
