// The renewal worklist and the alert after sign-in, as words. The server works out which
// contracts are on each list, as of today, and gives for each list the filter that lists
// the same rows on the list of contracts, or of items for `overlapping`: a count leads to
// its rows. Nothing is worked out here but how to say it and where it leads.

import type { Schemas } from "../api/client";
import type { FilterNode } from "./filter";
import { viewFilter } from "./filter";
import { plural } from "./format";
import { allows } from "./roles";

export type RenewalsReport = Schemas["RenewalsReport"];
export type RenewalGroup = Schemas["RenewalGroup"];
export type RenewalAlert = Schemas["RenewalAlert"];
export type RenewalSection = NonNullable<RenewalsReport["section"]>;
export type RenewalTotals = Schemas["RenewalTotals"];

export interface SectionInfo {
  value: RenewalSection;
  label: string;
  about: string;
  /** What the rows of the list are: contracts, or the items of `overlapping`. */
  of: "contracts" | "items";
}

/** The lists of the worklist, in the order they are acted on. */
export const RENEWAL_SECTIONS: readonly SectionInfo[] = [
  {
    value: "lapsed",
    label: "Lapsed",
    about:
      "Their period has ended while they still say Active: they cover nothing. Renew each, or say that it has expired or that its renewal is pending.",
    of: "contracts",
  },
  {
    value: "renewal_pending",
    label: "Renewal pending",
    about:
      "The term has ended and the renewal is in procurement: they cover on meanwhile, and support goes through the account manager. Each says how long it has been pending.",
    of: "contracts",
  },
  {
    value: "overdue",
    label: "Pending too long",
    about:
      "Of those whose renewal is pending, the ones pending for longer than the setting renewal_pending_overdue_days: somebody should ask why.",
    of: "contracts",
  },
  {
    value: "ending",
    label: "Ending soon",
    about:
      "They cover today and their period ends within the days asked for, with no renewal entered that is still to begin, their own or their agreement's, and the team has not marked them not to renew.",
    of: "contracts",
  },
  {
    value: "ends_with_term",
    label: "Marked not to renew",
    about:
      "The team marked them not to renew, as when a site closes, and they end within the days asked for or have ended: listed until a person says they have expired or retires them, so that what is let go is seen. The mark changes nothing by itself, and the alert never counts them.",
    of: "contracts",
  },
  {
    value: "to_review",
    label: "To review after a renewal",
    about:
      "Members of an agreement that was renewed and runs on that still say their renewal is pending or that they have expired: no renewal of an agreement changes them. Make each active, take it out of the agreement, or retire it.",
    of: "contracts",
  },
  {
    value: "overlapping",
    label: "Under more than one contract",
    about:
      "Items that more than one contract covers today: a list to look at before a renewal, and not a fault.",
    of: "items",
  },
];

export function isRenewalSection(value: string | null | undefined): value is RenewalSection {
  return RENEWAL_SECTIONS.some((section) => section.value === value);
}

export function sectionInfo(section: RenewalSection): SectionInfo {
  return (
    RENEWAL_SECTIONS.find((one) => one.value === section) ?? (RENEWAL_SECTIONS[0] as SectionInfo)
  );
}

/** The agreements counted on the lists by themselves: renewing one renews its members. */
export const AGREEMENT_SECTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "lapsed", label: "Lapsed" },
  { value: "renewal_pending", label: "Renewal pending" },
  { value: "ending", label: "Ending soon" },
];

/** The page of the worklist. */
export const RENEWALS_PATH = "/contracts/renewals";

/** What the address of the worklist may say besides its view: the list open, and the group. */
export interface Opened {
  section: RenewalSection;
  /** The vendor of the group the list is narrowed to, or blank for the whole list. */
  vendor?: string;
  /** The agreement of that group, or `none` for the contracts that stand by themselves. */
  agreement?: string;
}

/** The key of a group of the worklist in an address: its vendor, and its agreement or none. */
export function groupKey(group: Pick<RenewalGroup, "vendor_hid" | "agreement_hid">): {
  vendor: string;
  agreement: string;
} {
  return { vendor: group.vendor_hid, agreement: group.agreement_hid ?? "none" };
}

/** The group an address names, or undefined where it names none or one there is not. */
export function findGroup(
  groups: readonly RenewalGroup[],
  vendor: string | null | undefined,
  agreement: string | null | undefined,
): RenewalGroup | undefined {
  if (!vendor) return undefined;
  return groups.find(
    (group) =>
      group.vendor_hid === vendor && (group.agreement_hid ?? "none") === (agreement ?? "none"),
  );
}

/** The worklist with one list open, as a path of the app, from the alert or a count. */
export function renewalsPath(opened: Opened, keep: Record<string, string> = {}): string {
  const query = new URLSearchParams(keep);
  query.set("section", opened.section);
  if (opened.vendor) {
    query.set("vendor", opened.vendor);
    query.set("agreement", opened.agreement ?? "none");
  } else {
    query.delete("vendor");
    query.delete("agreement");
  }
  return `${RENEWALS_PATH}?${query.toString()}`;
}

/** The filter that lists the rows of a list, of the whole worklist or of one group of it. */
export function listFilter(
  report: Pick<RenewalsReport, "sections">,
  section: RenewalSection,
  group?: RenewalGroup,
): FilterNode | null {
  if (group) return viewFilter(group.filters[section]);
  return viewFilter(report.sections[section]?.filter);
}

/** What a group is called: its vendor, and its agreement or that its contracts stand alone. */
export function groupLabel(group: Pick<RenewalGroup, "vendor" | "agreement">): string {
  return group.agreement
    ? `${group.vendor} · ${group.agreement}`
    : `${group.vendor} · standing by themselves`;
}

/** How long a renewal has been pending, as a cell says it. Blank for one that is not. */
export function pendingText(days: number | null | undefined): string {
  if (days === null || days === undefined) return "";
  if (days === 0) return "Not yet ended";
  return plural(days, "day");
}

// --- the alert after sign-in ------------------------------------------------------------

/** One count of the alert, with the list of the worklist it leads to. */
export interface AlertLine {
  section: RenewalSection;
  /** How many contracts are on the list. */
  count: number;
  /** How many of them were not on the list when the person last dismissed the alert. */
  fresh: number;
  /** The count of contracts as a sentence, for its link: blank where there are none. */
  text: string;
  /** Of a renewal pending: how many of them are overdue, which leads to its own list. */
  overdue?: { count: number; text: string };
  /** The agreements on the same list, beside the contracts, where there are any. */
  agreements?: { count: number; text: string };
}

/** Where the counts of the agreements lead: their part of the worklist. */
export const AGREEMENTS_PATH = "/contracts/renewals#renewal-agreements";

/** Whether a person is shown the alert: Inventory and Admin, when the server says to. */
export function alertShown(alert: RenewalAlert | undefined, role: string | null | undefined) {
  return Boolean(alert?.show) && allows(role, "inventory");
}

/** Whether a person is asked for the alert at all: a View-only person never sees it. */
export function asksForAlert(role: string | null | undefined): boolean {
  return allows(role, "inventory");
}

/** How many agreements the alert counts on a list: none where it says nothing of them. */
function agreementsOn(alert: RenewalAlert, list: string): number {
  const count = alert.agreements?.[list];
  return typeof count === "number" && count > 0 ? count : 0;
}

/**
 * The counts of the alert, each as a sentence and with the list it leads to: the
 * contracts and the agreements that have lapsed, that have a renewal pending, of which
 * overdue, and that end within the warning period. A list with nothing on it is left out.
 */
export function alertLines(alert: RenewalAlert): AlertLine[] {
  const lines: AlertLine[] = [];
  const { lapsed, renewal_pending: pending, ending } = alert;
  const days = plural(alert.within_days, "day");
  const of = (list: string, one: string, many: string) => {
    const count = agreementsOn(alert, list);
    return count > 0 ? { agreements: { count, text: plural(count, one, many) } } : {};
  };
  if (lapsed.count > 0 || agreementsOn(alert, "lapsed") > 0) {
    lines.push({
      section: lapsed.section,
      count: lapsed.count,
      fresh: lapsed.new,
      text:
        lapsed.count > 0 ? `${plural(lapsed.count, "contract has", "contracts have")} lapsed` : "",
      ...of("lapsed", "agreement has lapsed", "agreements have lapsed"),
    });
  }
  if (pending.count > 0 || agreementsOn(alert, "renewal_pending") > 0) {
    lines.push({
      section: pending.section,
      count: pending.count,
      fresh: pending.new,
      text:
        pending.count > 0
          ? `${plural(pending.count, "contract has its", "contracts have their")} renewal pending`
          : "",
      ...(alert.overdue > 0
        ? {
            overdue: {
              count: alert.overdue,
              text: `${alert.overdue} of ${pending.count === 1 ? "it" : "them"} overdue`,
            },
          }
        : {}),
      ...of(
        "renewal_pending",
        "agreement has its renewal pending",
        "agreements have their renewal pending",
      ),
    });
  }
  if (ending.count > 0 || agreementsOn(alert, "ending") > 0) {
    lines.push({
      section: ending.section,
      count: ending.count,
      fresh: ending.new,
      text:
        ending.count > 0
          ? `${plural(ending.count, "contract ends", "contracts end")} within ${days}`
          : "",
      ...of("ending", `agreement ends within ${days}`, `agreements end within ${days}`),
    });
  }
  return lines;
}

/** What is new on the alert since it was last seen, as a few words beside a count. */
export function freshText(fresh: number): string {
  return fresh > 0 ? `${fresh} new` : "";
}

// --- an agreement renewed with its members (P-122, P-129) -------------------------------

export type MemberChoice = "same" | "new_number" | "ends";
type MemberRenewal = Schemas["MemberRenewal"];
type MemberRenewed = Schemas["MemberRenewedOut"];

/** What a renewal of an agreement may do with a member, as the form offers it. */
export const MEMBER_CHOICES: ReadonlyArray<{ value: MemberChoice; label: string; about: string }> =
  [
    {
      value: "same",
      label: "Keep its number",
      about: "It follows the agreement into the new term under the number it has.",
    },
    {
      value: "new_number",
      label: "A new number",
      about:
        "The vendor gave it another number: it begins with the agreement's new term, with no dates of its own.",
    },
    {
      value: "ends",
      label: "End with this term",
      about:
        "It is let go, as when a site closes: it takes the agreement's present end as its own, and its start where it has none, stays in the agreement, and is marked not to renew; the new term does not carry it.",
    },
  ];

/** A contract as a renewal of its agreement needs it. */
export interface MemberOf {
  hid: string;
  number: string;
  record_status: string;
  starts_on: string | null;
  ends_on: string | null;
  ends_with_term: boolean;
  covered_items: number;
}

/**
 * Whether a contract shares its agreement's period, and so is a member that a renewal of
 * the agreement asks about: it is not retired and its end is the agreement's, having no
 * end of its own, whatever its start (P-129).
 */
export function sharesPeriod(contract: MemberOf): boolean {
  return contract.record_status !== "retired" && !contract.ends_on;
}

/** One member on the form of a renewal: what is to be done with it, and its new term. */
export interface MemberDraft {
  hid: string;
  number: string;
  covered: number;
  /** The team marked it not to renew: carried into the new term, it is to be reviewed. */
  marked: boolean;
  choice: MemberChoice;
  /** For a new number: the number, its annual cost and what it was bought under. */
  newNumber: string;
  annualCost: string;
  purchaseReference: string;
}

/**
 * The members of an agreement on the form of its renewal, each with what the server does
 * with one left out: keep its number. One the team marked not to renew says so, as it
 * is then among those to review.
 */
export function memberDrafts(contracts: readonly MemberOf[]): MemberDraft[] {
  return contracts.filter(sharesPeriod).map((contract) => ({
    hid: contract.hid,
    number: contract.number,
    covered: contract.covered_items,
    marked: contract.ends_with_term,
    choice: "same",
    newNumber: "",
    annualCost: "",
    purchaseReference: "",
  }));
}

/**
 * What a renewal of the agreement sends of its members, or what is wrong with the form:
 * every member, with its choice, and a new number with its number, and its cost and its
 * purchase reference where they are given.
 */
export function membersBody(
  drafts: readonly MemberDraft[],
): { ok: true; value: MemberRenewal[] } | { ok: false; error: string } {
  const members: MemberRenewal[] = [];
  for (const draft of drafts) {
    if (draft.choice !== "new_number") {
      members.push({ contract_hid: draft.hid, renewal: draft.choice });
      continue;
    }
    const number = draft.newNumber.trim();
    if (number === "") return { ok: false, error: `Give the new number of ${draft.number}.` };
    if (number.length > 200) {
      return {
        ok: false,
        error: `The new number of ${draft.number} is longer than 200 characters.`,
      };
    }
    const cost = draft.annualCost.trim();
    if (cost !== "" && !/^\d+(\.\d{1,2})?$/.test(cost)) {
      return {
        ok: false,
        error: `The annual cost of ${draft.number} is a number that is not negative, with at most 2 digits after the point.`,
      };
    }
    const reference = draft.purchaseReference.trim();
    members.push({
      contract_hid: draft.hid,
      renewal: "new_number",
      number,
      ...(cost === "" ? {} : { annual_cost: cost }),
      ...(reference === "" ? {} : { purchase_reference: reference }),
    });
  }
  return { ok: true, value: members };
}

/** What the fields of each member are called, where the server refuses one of them. */
export function memberLabels(drafts: readonly MemberDraft[]): Record<string, string> {
  const labels: Record<string, string> = { members: "The members" };
  drafts.forEach((draft, place) => {
    labels[`members.${place}`] = draft.number;
    labels[`members.${place}.contract_hid`] = draft.number;
    labels[`members.${place}.renewal`] = `What is done with ${draft.number}`;
    labels[`members.${place}.number`] = `The new number of ${draft.number}`;
    labels[`members.${place}.annual_cost`] = `The annual cost of ${draft.number}`;
    labels[`members.${place}.purchase_reference`] = `The purchase reference of ${draft.number}`;
  });
  return labels;
}

/** How many coverages a renewal left behind, as a sentence. Blank for none. */
export function leftBehindText(count: number): string {
  if (count <= 0) return "";
  return `${plural(count, "coverage of an item not to be renewed was", "coverages of items not to be renewed were")} ended with the present term.`;
}

/**
 * What a renewal of an agreement did with each member, as the server answered it, a
 * sentence each: `numbers` holds what each was called before, by its HID.
 */
export function membersText(
  members: readonly MemberRenewed[],
  numbers: Readonly<Record<string, string>>,
): string {
  return members
    .map((member) => {
      const was = numbers[member.contract_hid] ?? member.number;
      if (member.renewal === "new_number") {
        return `${was} takes the new number ${member.number} with the new term.`;
      }
      if (member.renewal === "ends") return `${was} ends with this term.`;
      return `${was} keeps its number.`;
    })
    .join(" ");
}

/**
 * What is said of the members a renewal of an agreement left to be reviewed: those that
 * still say their renewal is pending or that they have expired, which no renewal of an
 * agreement changes, and those marked not to renew that it carried on. Blank for none.
 */
export function toReviewText(count: number): string {
  if (count <= 0) return "";
  return `${plural(count, "member still says", "members still say")} renewal pending or expired, or ${count === 1 ? "is" : "are"} marked not to renew: review ${count === 1 ? "it" : "them"}.`;
}

/**
 * What is said of the members of an agreement to review, as its record lists them: those
 * that still say their renewal is pending or that they have expired while it runs on.
 */
export function membersToReviewText(count: number): string {
  if (count <= 0) return "";
  return `${plural(count, "member still says", "members still say")} renewal pending or expired while the agreement runs on: make each active, take it out of the agreement, or retire it.`;
}
