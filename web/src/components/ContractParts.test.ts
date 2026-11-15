import { createElement, type ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import type { Agreement, Contract, InForce } from "../lib/contracts";
import { agreementSpecs, contractSpecs, InForceValue, Lines, SupportLink } from "./ContractParts";

const AGREEMENT = { hid: "0193a1f4-0000-7000-8000-00000000a001", name: "Example Agreement" };

function html(element: ReactElement): string {
  return renderToStaticMarkup(createElement(MemoryRouter, null, element));
}

function shown(value: InForce, agreement: typeof AGREEMENT | null = AGREEMENT): string {
  return html(createElement(InForceValue, { value, agreement }));
}

describe("a value of a contract as it is in force", () => {
  it("is lighter and marked Inherited, with the agreement it came from as a link", () => {
    const out = shown({ standing: "inherited", text: "2027-12-31", overridden: "", same: false });
    expect(out).toContain('data-standing="inherited"');
    expect(out).toContain('class="inherited"');
    expect(out).toContain("2027-12-31");
    expect(out).toContain(">Inherited</span>");
    expect(out).toContain(`href="/agreements/${AGREEMENT.hid}"`);
    expect(out).toContain("Example Agreement");
  });

  it("is marked Overrides, with what it overrides, where it is the contract's own", () => {
    const out = shown({
      standing: "override",
      text: "8x5, next business day",
      overridden: "24x7, four-hour response",
      same: false,
    });
    expect(out).toContain('data-standing="override"');
    expect(out).toContain('data-same="false"');
    expect(out).toContain("8x5, next business day");
    expect(out).toContain(">Overrides</span>");
    expect(out).toContain("24x7, four-hour response");
    expect(out).toContain("Set here");
    expect(out).not.toContain("which is the same");
  });

  it("is still marked Overrides where its own is the same as the agreement's, and says so", () => {
    const out = shown({
      standing: "override",
      text: "24x7, four-hour response",
      overridden: "24x7, four-hour response",
      same: true,
    });
    expect(out).toContain('data-standing="override"');
    expect(out).toContain('data-same="true"');
    expect(out).toContain(">Overrides</span>");
    expect(out).toContain("which is the same: set here, it stays as it is when the agreement");
  });

  it("is plain for a value of its own, and says Set here only beside an agreement", () => {
    const value: InForce = { standing: "own", text: "2026-07-01", overridden: "", same: false };
    expect(shown(value)).toContain("Set here");
    const alone = shown(value, null);
    expect(alone).toContain('data-standing="own"');
    expect(alone).toContain("2026-07-01");
    expect(alone).not.toContain("Set here");
  });

  it("is a dash where there is none", () => {
    const out = shown({ standing: "none", text: "", overridden: "", same: false });
    expect(out).toContain('data-standing="none"');
    expect(out).toContain("—");
  });

  it("shows what the page gives in place of the text: a link, or several lines", () => {
    const out = html(
      createElement(
        InForceValue,
        {
          value: {
            standing: "inherited",
            text: "https://support.example.com",
            overridden: "",
            same: false,
          },
          agreement: AGREEMENT,
        },
        createElement(SupportLink, { url: "https://support.example.com" }),
      ),
    );
    expect(out).toContain('<a href="https://support.example.com"');
    expect(out).toContain(">Inherited</span>");
  });
});

describe("where support is reached online", () => {
  it("is a link that opens apart and tells the other site nothing of this one", () => {
    const out = html(createElement(SupportLink, { url: "https://support.example.com/enterprise" }));
    expect(out).toContain('href="https://support.example.com/enterprise"');
    expect(out).toContain('target="_blank"');
    expect(out).toContain('rel="noopener noreferrer"');
  });

  it("is text, and no link, when it is not an address of the web", () => {
    const out = html(createElement(SupportLink, { url: "javascript:alert(1)" }));
    expect(out).not.toContain("<a ");
    expect(out).toContain("javascript:alert(1)");
    expect(html(createElement(SupportLink, { url: "support.example.com" }))).not.toContain("<a ");
  });

  it("is a dash when there is none", () => {
    expect(html(createElement(SupportLink, { url: null }))).toContain("—");
  });
});

describe("free text of several lines", () => {
  it("keeps its lines, and is put in as text", () => {
    const out = html(createElement(Lines, { text: "Support desk\n+1 555 0100 <b>" }));
    expect(out).toContain('class="lines"');
    expect(out).toContain("Support desk\n+1 555 0100 &lt;b&gt;");
    expect(html(createElement(Lines, { text: "" }))).toContain("—");
  });
});

describe("the forms of an agreement and of a contract", () => {
  const lists = { vendors: [{ value: "v-1", label: "Cisco" }], tags: ["renewal-2027"] };

  it("ask for every field of an agreement that can be set", () => {
    expect(agreementSpecs(lists).map((spec) => spec.name)).toEqual([
      "name",
      "number",
      "vendor_hid",
      "status",
      "reseller_hid",
      "starts_on",
      "ends_on",
      "support_level",
      "account_manager",
      "support_contact",
      "support_url",
      "purchase_reference",
      "annual_cost",
      "notes",
      "record_status",
      "tags",
    ]);
  });

  it("ask for every field of a contract but the agreement, which has an action of its own", () => {
    const names = contractSpecs(lists).map((spec) => spec.name);
    expect(names).toContain("number");
    expect(names).toContain("support_url");
    expect(names).toContain("tags");
    expect(names).not.toContain("agreement_hid");
  });

  it("offer the tags a record already has, though the list no longer has them", () => {
    const agreement = { tags: ["old-tag"] } as unknown as Agreement;
    const tags = agreementSpecs(lists, agreement).find((spec) => spec.name === "tags");
    expect(tags?.options?.map((option) => option.value)).toEqual(["renewal-2027", "old-tag"]);
  });

  it("say under each field a contract may have from its agreement what a blank brings", () => {
    const contract = {
      tags: [],
      agreement: { hid: AGREEMENT.hid, name: AGREEMENT.name, number: null },
      effective: {
        reseller_hid: { value: null, label: null, source: "none", source_hid: null },
        starts_on: { value: "2025-01-01", source: "agreement", source_hid: AGREEMENT.hid },
        ends_on: { value: "2027-12-31", source: "agreement", source_hid: AGREEMENT.hid },
        support_level: {
          value: "8x5",
          source: "own",
          source_hid: "c-1",
          from_agreement: "24x7, four-hour response",
        },
        account_manager: { value: null, source: "none", source_hid: null },
        support_contact: { value: null, source: "none", source_hid: null },
        support_url: { value: null, source: "none", source_hid: null },
      },
    } as unknown as Contract;
    const specs = contractSpecs(lists, contract);
    const hint = (name: string) => specs.find((spec) => spec.name === name)?.hint;
    expect(hint("ends_on")).toBe("Blank has 2027-12-31 from Example Agreement.");
    // What an own value is in place of is what the server says the agreement gives.
    expect(hint("support_level")).toBe(
      "Set here, in place of 24x7, four-hour response from Example Agreement. Clear it to have that.",
    );
    // The heading of those fields names the agreement.
    expect(specs.find((spec) => spec.name === "reseller_hid")?.heading).toBe(
      "What it may have from Example Agreement",
    );
  });
});
