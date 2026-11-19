import { describe, expect, it } from "vitest";
import {
  fewNames,
  handedOverText,
  handOverLabel,
  hostsNothingHint,
  notReportedText,
  TO_REVIEW,
  toReviewPath,
  toReviewText,
} from "./hostFollows";

describe("the box of Replace for what runs on the item that leaves (P-247)", () => {
  it("says how many go to the new one", () => {
    expect(handOverLabel(3)).toBe("The 3 things that run on it go to the new one");
    expect(handOverLabel(1)).toBe("The 1 thing that runs on it goes to the new one");
  });

  it("is ticked for an item that may host, and unticked for one of a kind that hosts nothing", () => {
    expect(hostsNothingHint("site2-lic-01", "software")).toMatch(
      /^Unticked: site2-lic-01 is of the kind software, which hosts nothing\./,
    );
  });

  it("names them beneath where they are few, and none where there are more", () => {
    const ten = Array.from({ length: 10 }, (_, n) => `site2-vm-${n}`);
    expect(fewNames(ten)).toHaveLength(10);
    expect(fewNames([...ten, "site2-vm-10"])).toEqual([]);
  });

  it("says afterwards where they went, or that they stayed", () => {
    expect(handedOverText(3, true, "site2-esx-02")).toBe(
      " The 3 things that ran on it run on site2-esx-02 now.",
    );
    expect(handedOverText(1, false, "site2-esx-02")).toBe(
      " The 1 thing that runs on it stays on it.",
    );
    expect(handedOverText(0, true, "site2-esx-02")).toBe("");
  });
});

describe("what a tool's report marks as not reported (P-248)", () => {
  const job = {
    complete: true,
    status: "previewed",
    not_reported: 1,
    rejected: 0,
    system: { name: "Example vCenter" },
  };

  it("says how many the preview would mark", () => {
    expect(notReportedText(job)).toBe(
      "1 item registered with Example vCenter is not named by the file, and will be marked as not reported once it is applied whole:",
    );
    expect(notReportedText({ ...job, not_reported: 0 })).toBe(
      "Every item registered with Example vCenter is named by the file: none will be marked as not reported.",
    );
  });

  it("says a file with a row rejected marks nothing", () => {
    expect(notReportedText({ ...job, rejected: 2, not_reported: 0 })).toMatch(
      /^Nothing will be marked as not reported: a row is rejected/,
    );
  });

  it("says how many were marked once applied", () => {
    expect(notReportedText({ ...job, status: "applied", not_reported: 4 })).toBe(
      "4 items were marked as not reported by Example vCenter, each to be looked at.",
    );
  });

  it("says nothing of a file that is not everything a system reports", () => {
    expect(notReportedText({ ...job, complete: false })).toBe("");
    expect(notReportedText({ ...job, complete: null, system: null })).toBe("");
  });
});

describe("the first page's count of what is to be looked at (P-249)", () => {
  it("is a link to the item list with that filter", () => {
    const path = new URL(toReviewPath(), "http://localhost");
    expect(path.pathname).toBe("/items");
    expect(path.searchParams.get("filter")).toBe(TO_REVIEW);
    expect(TO_REVIEW).toBe("review:empty:false");
  });

  it("says how many", () => {
    expect(toReviewText(1).link).toBe("1 item is");
    expect(toReviewText(1200).link).toBe("1,200 items are");
  });
});
