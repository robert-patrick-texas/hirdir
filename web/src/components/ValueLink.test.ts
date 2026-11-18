import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { ValueLink } from "./ValueLink";

function html(kind: string, hid: string | null, admin = false): string {
  return renderToStaticMarkup(
    createElement(MemoryRouter, null, createElement(ValueLink, { kind, hid, admin }, "Site-2")),
  );
}

// 0.9.7: a value of a table that names a record is a link in the style of its text (P-232).
describe("ValueLink", () => {
  it("links the name to the record's page, in the one style of such links", () => {
    expect(html("site", "s 1")).toBe(
      '<a class="value-link" href="/geography/site/s%201" data-discover="true">Site-2</a>',
    );
  });

  it("is the name alone where the record has no page, or none is named", () => {
    expect(html("network", "n-1")).toBe("Site-2");
    expect(html("site", null)).toBe("Site-2");
  });

  it("opens a page only an Admin may open only on a page for an Admin", () => {
    expect(html("user_group", "g-1")).toBe("Site-2");
    expect(html("user_group", "g-1", true)).toContain('href="/admin/groups/g-1"');
  });
});
