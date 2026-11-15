import { describe, expect, it } from "vitest";
import {
  alertLines,
  alertShown,
  applyToSelected,
  asksForAlert,
  findGroup,
  freshText,
  groupKey,
  groupLabel,
  isRenewalSection,
  leftBehindText,
  listFilter,
  type MemberOf,
  memberDrafts,
  memberLabels,
  membersBody,
  membersText,
  membersToReviewText,
  pendingText,
  RENEWAL_SECTIONS,
  type RenewalAlert,
  type RenewalGroup,
  renewalsPath,
  sharesPeriod,
  toConfirm,
  toReviewText,
  updatedText,
} from "./renewals";

const counts = {
  ending: 0,
  lapsed: 0,
  renewal_pending: 0,
  overdue: 0,
  ends_with_term: 0,
  to_review: 0,
  overlapping: 0,
};

function alert(over: Partial<RenewalAlert> = {}): RenewalAlert {
  return {
    as_of: "2026-11-15",
    within_days: 90,
    overdue_after: 60,
    show: true,
    version: "v-1",
    lapsed: { count: 1, new: 1, section: "lapsed" },
    renewal_pending: { count: 3, new: 0, section: "renewal_pending" },
    overdue: 1,
    ending: { count: 4, new: 2, section: "ending" },
    agreements: { ending: 0, lapsed: 0, renewal_pending: 0 },
    ...over,
  };
}

function group(over: Partial<RenewalGroup> = {}): RenewalGroup {
  return {
    vendor_hid: "v-1",
    vendor: "Example Networks",
    agreement_hid: "a-1",
    agreement: "Example Enterprise Agreement",
    counts: { ...counts, ending: 2 },
    filters: { ending: { field: "agreement_hid", op: "eq", value: "a-1" } },
    ...over,
  };
}

describe("the lists of the worklist", () => {
  it("are the six the server answers, with the items under more than one contract last", () => {
    expect(RENEWAL_SECTIONS.map((one) => one.value)).toEqual([
      "lapsed",
      "renewal_pending",
      "overdue",
      "ending",
      "ends_with_term",
      "to_review",
      "overlapping",
    ]);
    expect(RENEWAL_SECTIONS.filter((one) => one.of === "items").map((one) => one.value)).toEqual([
      "overlapping",
    ]);
    for (const one of RENEWAL_SECTIONS) expect(one.about).not.toBe("");
  });

  it("are known by their names, and nothing else is", () => {
    expect(isRenewalSection("ending")).toBe(true);
    expect(isRenewalSection("overdue")).toBe(true);
    expect(isRenewalSection("to_review")).toBe(true);
    expect(isRenewalSection("uncovered")).toBe(false);
    expect(isRenewalSection(null)).toBe(false);
  });

  it("lead from a count to the list on the page, keeping the view", () => {
    expect(renewalsPath({ section: "lapsed" })).toBe("/contracts/renewals?section=lapsed");
    expect(renewalsPath({ section: "ending" }, { days: "30" })).toBe(
      "/contracts/renewals?days=30&section=ending",
    );
    const one = group();
    expect(renewalsPath({ section: "ending", ...groupKey(one) })).toBe(
      "/contracts/renewals?section=ending&vendor=v-1&agreement=a-1",
    );
    // The contracts that stand by themselves are a group with no agreement.
    expect(groupKey(group({ agreement_hid: null, agreement: null }))).toEqual({
      vendor: "v-1",
      agreement: "none",
    });
  });

  it("find the group an address names, and its filter, or the whole list's", () => {
    const alone = group({ agreement_hid: null, agreement: null, filters: {} });
    const groups = [group(), alone];
    expect(findGroup(groups, "v-1", "a-1")).toBe(groups[0]);
    expect(findGroup(groups, "v-1", "none")).toBe(alone);
    expect(findGroup(groups, "v-2", "none")).toBeUndefined();
    expect(findGroup(groups, null, null)).toBeUndefined();
    const report = {
      sections: {
        ending: {
          count: 4,
          filter: { field: "status", op: "eq", value: "active" },
          include_archived: false,
          include_drafts: false,
        },
      },
    };
    expect(listFilter(report, "ending")).toEqual({ field: "status", op: "eq", value: "active" });
    expect(listFilter(report, "ending", groups[0])).toEqual({
      field: "agreement_hid",
      op: "eq",
      value: "a-1",
    });
    // A list the server gives no filter for, as for a view whose filter is as large as one
    // may be, has none.
    expect(listFilter(report, "lapsed")).toBeNull();
    expect(listFilter(report, "ending", alone)).toBeNull();
  });

  it("name a group by its vendor and its agreement, or say its contracts stand alone", () => {
    expect(groupLabel(group())).toBe("Example Networks · Example Enterprise Agreement");
    expect(groupLabel(group({ agreement: null }))).toBe(
      "Example Networks · standing by themselves",
    );
  });

  it("say how long a renewal has been pending", () => {
    expect(pendingText(null)).toBe("");
    expect(pendingText(0)).toBe("Not yet ended");
    expect(pendingText(1)).toBe("1 day");
    expect(pendingText(75)).toBe("75 days");
  });
});

describe("the alert after sign-in", () => {
  it("is shown to Inventory and Admin when the server says so, and never to View-only", () => {
    expect(alertShown(alert(), "inventory")).toBe(true);
    expect(alertShown(alert(), "admin")).toBe(true);
    expect(alertShown(alert(), "viewer")).toBe(false);
    expect(alertShown(alert({ show: false }), "admin")).toBe(false);
    expect(alertShown(undefined, "admin")).toBe(false);
    expect(asksForAlert("viewer")).toBe(false);
    expect(asksForAlert(null)).toBe(false);
    expect(asksForAlert("inventory")).toBe(true);
  });

  it("says each count with the list it leads to, the overdue ones among those pending", () => {
    const lines = alertLines(alert());
    expect(lines.map((line) => [line.section, line.text, line.fresh])).toEqual([
      ["lapsed", "1 contract has lapsed", 1],
      ["renewal_pending", "3 contracts have their renewal pending", 0],
      ["ending", "4 contracts end within 90 days", 2],
    ]);
    expect(lines[1]?.overdue).toEqual({ count: 1, text: "1 of them overdue" });
    expect(lines[0]?.overdue).toBeUndefined();
    expect(freshText(2)).toBe("2 new");
    expect(freshText(0)).toBe("");
  });

  it("counts the agreements on each list beside the contracts", () => {
    const lines = alertLines(
      alert({
        lapsed: { count: 0, new: 0, section: "lapsed" },
        agreements: { ending: 1, lapsed: 2, renewal_pending: 0 },
      }),
    );
    expect(lines.map((line) => [line.section, line.text, line.agreements?.text])).toEqual([
      ["lapsed", "", "2 agreements have lapsed"],
      ["renewal_pending", "3 contracts have their renewal pending", undefined],
      ["ending", "4 contracts end within 90 days", "1 agreement ends within 90 days"],
    ]);
  });

  it("leaves out a list with nothing on it", () => {
    const lines = alertLines(
      alert({
        lapsed: { count: 0, new: 0, section: "lapsed" },
        renewal_pending: { count: 1, new: 1, section: "renewal_pending" },
        overdue: 0,
        ending: { count: 0, new: 0, section: "ending" },
      }),
    );
    expect(lines.map((line) => line.text)).toEqual(["1 contract has its renewal pending"]);
    expect(lines[0]?.overdue).toBeUndefined();
  });
});

describe("several contracts of an agreement updated at once", () => {
  const label = (status: string) => (status === "active" ? "Active" : status);

  it("says what was done, and names each contract refused with why", () => {
    expect(
      updatedText(
        { kind: "status", status: "active" },
        { done: ["CON-1", "CON-2"], refused: [{ number: "CON-3", message: "It changed." }] },
        label,
      ),
    ).toBe("CON-1, CON-2 now say Active. Refused: CON-3, It changed.");
    expect(
      updatedText({ kind: "status", status: "active" }, { done: ["CON-1"], refused: [] }, label),
    ).toBe("CON-1 now says Active.");
    expect(updatedText({ kind: "take_out" }, { done: ["CON-1"], refused: [] }, label)).toBe(
      "CON-1 was taken out of the agreement, and stands by itself.",
    );
    expect(updatedText({ kind: "retire" }, { done: ["CON-1", "CON-2"], refused: [] }, label)).toBe(
      "CON-1, CON-2 were retired.",
    );
    expect(updatedText({ kind: "retire" }, { done: [], refused: [] }, label)).toBe(
      "Nothing was selected.",
    );
  });
});

describe("an agreement renewed with its members", () => {
  const contract = (over: Partial<MemberOf>): MemberOf => ({
    hid: "c-1",
    number: "CON-1",
    status: "active",
    record_status: "active",
    starts_on: null,
    ends_on: null,
    ends_with_term: false,
    covered_items: 2,
    ...over,
  });

  it("asks about the contracts that share its period: not retired, with no end of their own", () => {
    expect(sharesPeriod(contract({}))).toBe(true);
    expect(sharesPeriod(contract({ ends_on: "2027-06-30" }))).toBe(false);
    // Its end is the agreement's, whatever its start.
    expect(sharesPeriod(contract({ starts_on: "2026-01-01" }))).toBe(true);
    expect(sharesPeriod(contract({ record_status: "retired" }))).toBe(false);
    expect(sharesPeriod(contract({ record_status: "draft" }))).toBe(true);
  });

  it("starts each as the server has one left out: its number kept, the mark said", () => {
    const drafts = memberDrafts([
      contract({}),
      contract({ hid: "c-2", number: "CON-2", ends_with_term: true }),
      contract({ hid: "c-3", number: "CON-3", ends_on: "2027-06-30" }),
    ]);
    expect(
      drafts.map((draft) => [draft.number, draft.choice, draft.covered, draft.marked]),
    ).toEqual([
      ["CON-1", "same", 2, false],
      ["CON-2", "same", 2, true],
    ]);
  });

  it("sends every member with its choice, and a new number with what is given of it", () => {
    const [kept, renumbered, ended] = memberDrafts([
      contract({}),
      contract({ hid: "c-2", number: "CON-2" }),
      contract({ hid: "c-3", number: "CON-3" }),
    ]);
    if (!kept || !renumbered || !ended) throw new Error("three drafts");
    const body = membersBody([
      kept,
      {
        ...renumbered,
        choice: "new_number",
        newNumber: " CON-2B ",
        annualCost: "1200.50",
        purchaseReference: "",
      },
      { ...ended, choice: "ends" },
    ]);
    expect(body).toEqual({
      ok: true,
      value: [
        { contract_hid: "c-1", renewal: "same" },
        { contract_hid: "c-2", renewal: "new_number", number: "CON-2B", annual_cost: "1200.50" },
        { contract_hid: "c-3", renewal: "ends" },
      ],
    });
  });

  it("sends the status a member is to have where the operator confirms one, and none else", () => {
    const [moving, waiting] = memberDrafts([
      contract({ status: "renewal_pending" }),
      contract({ hid: "c-2", number: "CON-2", status: "expired" }),
    ]);
    if (!moving || !waiting) throw new Error("two drafts");
    expect(toConfirm(moving)).toBe(true);
    expect(toConfirm(waiting)).toBe(true);
    expect(toConfirm({ current: "active" })).toBe(false);
    expect(membersBody([{ ...moving, status: "active" }, waiting])).toEqual({
      ok: true,
      value: [
        { contract_hid: "c-1", renewal: "same", status: "active" },
        { contract_hid: "c-2", renewal: "same" },
      ],
    });
  });

  it("sets those selected at once, a choice, a status or both, and leaves the others", () => {
    const drafts = memberDrafts([
      contract({ status: "renewal_pending" }),
      contract({ hid: "c-2", number: "CON-2", status: "renewal_pending" }),
      contract({ hid: "c-3", number: "CON-3", status: "renewal_pending" }),
    ]);
    const chosen = new Set(["c-1", "c-2"]);
    const active = applyToSelected(drafts, chosen, { choice: "", status: "active" });
    expect(active.map((draft) => [draft.number, draft.choice, draft.status])).toEqual([
      ["CON-1", "same", "active"],
      ["CON-2", "same", "active"],
      ["CON-3", "same", ""],
    ]);
    const ended = applyToSelected(active, new Set(["c-2"]), { choice: "ends", status: "keep" });
    expect(ended.map((draft) => [draft.number, draft.choice, draft.status])).toEqual([
      ["CON-1", "same", "active"],
      ["CON-2", "ends", ""],
      ["CON-3", "same", ""],
    ]);
    expect(applyToSelected(drafts, new Set(), { choice: "ends", status: "active" })).toEqual(
      drafts,
    );
  });

  it("asks for the new number, and a cost that is an amount", () => {
    const [draft] = memberDrafts([contract({})]);
    if (!draft) throw new Error("one draft");
    expect(membersBody([{ ...draft, choice: "new_number" }])).toEqual({
      ok: false,
      error: "Give the new number of CON-1.",
    });
    const wrong = membersBody([
      { ...draft, choice: "new_number", newNumber: "CON-1B", annualCost: "12,00" },
    ]);
    expect(wrong.ok).toBe(false);
    expect(membersBody([])).toEqual({ ok: true, value: [] });
  });

  it("names the fields of each member where the server refuses one", () => {
    const labels = memberLabels(memberDrafts([contract({})]));
    expect(labels["members.0.number"]).toBe("The new number of CON-1");
    expect(labels["members.0.contract_hid"]).toBe("CON-1");
  });

  it("says what was done with each, and how many coverages were left behind", () => {
    expect(
      membersText(
        [
          {
            contract_hid: "c-1",
            number: "CON-1",
            renewal: "same",
            left_behind: 0,
            to_review: true,
          },
          {
            contract_hid: "c-2",
            number: "CON-2B",
            renewal: "new_number",
            left_behind: 1,
            to_review: false,
          },
          {
            contract_hid: "c-3",
            number: "CON-3",
            renewal: "ends",
            left_behind: 0,
            to_review: false,
          },
        ],
        { "c-1": "CON-1", "c-2": "CON-2", "c-3": "CON-3" },
      ),
    ).toBe(
      "CON-1 keeps its number. CON-2 takes the new number CON-2B with the new term. CON-3 ends with this term.",
    );
    expect(leftBehindText(0)).toBe("");
    expect(leftBehindText(1)).toBe(
      "1 coverage of an item not to be renewed was ended with the present term.",
    );
    expect(leftBehindText(3)).toBe(
      "3 coverages of items not to be renewed were ended with the present term.",
    );
  });

  it("says how many members are to be reviewed after it, and on the agreement", () => {
    expect(toReviewText(0)).toBe("");
    expect(toReviewText(1)).toBe(
      "1 member still says renewal pending or expired, or is marked not to renew: review it.",
    );
    expect(toReviewText(2)).toBe(
      "2 members still say renewal pending or expired, or are marked not to renew: review them.",
    );
    expect(membersToReviewText(0)).toBe("");
    expect(membersToReviewText(2)).toContain("2 members still say renewal pending or expired");
  });
});
