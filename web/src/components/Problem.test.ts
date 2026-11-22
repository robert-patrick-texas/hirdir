// What a refusal names of the record that has a value already (P-207), as the review of
// the web of 0.9.18 found it on Admin › Choices (finding 12): a record with no page of
// its own that the message names already is not named a second time beneath it; one
// with a page is named, as a link to it.

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { Problem } from "./Problem";

function shown(error: ApiError, fields: string[] = []): string {
  return renderToStaticMarkup(
    createElement(MemoryRouter, null, createElement(Problem, { error, shown: fields })),
  );
}

describe("the record a refusal names as having the value", () => {
  it("is not named again where it has no page and the message names it (finding 12)", () => {
    const markup = shown(
      new ApiError({
        status: 409,
        title: "Conflict",
        detail: "the code XQ is taken by Example Land",
        fields: { code: "another country has it" },
        existing: { record_type: "country", hid: "c-xq", label: "Example Land" },
      }),
      ["code"],
    );
    expect(markup).toContain("The code XQ is taken by Example Land.");
    expect(markup).not.toContain("that has it");
    // The message of the field is beside its input, not here.
    expect(markup).not.toContain("another country has it");
  });

  it("is named where the message does not name it", () => {
    const markup = shown(
      new ApiError({
        status: 409,
        title: "Conflict",
        detail: "the code is taken",
        existing: { record_type: "state", hid: "s-tx", label: "Texas" },
      }),
    );
    expect(markup).toContain("The state that has it:");
    expect(markup).toContain("Texas");
  });

  it("is named as a link where it has a page, though the message names it", () => {
    const markup = shown(
      new ApiError({
        status: 409,
        title: "Conflict",
        detail: "the asset tag AT-1 is held by core-sw-01",
        existing: { record_type: "item", hid: "i-1", label: "core-sw-01" },
      }),
    );
    expect(markup).toContain("The item that has it:");
    expect(markup).toContain('href="/items/i-1"');
  });
});
