import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { fieldErrors, fieldLine, refusalOf, sentence } from "./problems";

describe("what a refusal says of a field that has no input", () => {
  it("names the field as the page calls it", () => {
    expect(
      fieldLine("parent_region_hid", "regions nest at most 16 deep", {
        parent_region_hid: "The region it is in",
      }),
    ).toBe("The region it is in: regions nest at most 16 deep");
  });

  it("lets the message stand alone, as a sentence, for a field the page does not name", () => {
    expect(
      fieldLine("record_status", "bring Central back first: it is retired", { record_status: "" }),
    ).toBe("Bring Central back first: it is retired.");
    expect(
      fieldLine("record_status", "give the item another location, or none, with the change", {
        record_status: "",
      }),
    ).toBe("Give the item another location, or none, with the change.");
  });

  it("names a field the page has no word for as the server names it", () => {
    expect(fieldLine("tags.0", "there is no tag core")).toBe("tags.0: there is no tag core");
  });

  it("writes a sentence with a capital and a full stop, once", () => {
    expect(sentence(" the label is taken ")).toBe("The label is taken.");
    expect(sentence("Reload it.")).toBe("Reload it.");
    expect(sentence("")).toBe("");
  });
});

const stale = new ApiError({
  status: 409,
  title: "Stale version",
  detail: "this record is at version 4, and the change was made against version 3",
});
const conflict = new ApiError({
  status: 409,
  title: "Conflict",
  detail:
    "there is already an item with the asset tag AT-000123: 0193a1f4-6c2e-7b41-9d0a-5e3f8c1a7b22",
});
const invalid = new ApiError({
  status: 422,
  title: "Invalid input",
  detail: "the lifecycle rules do not allow this",
  fields: { disposition: "an item in Prod is one of Production, Spare, not Excess" },
});

describe("refusalOf", () => {
  it("tells a stale version from a collision, though both are 409", () => {
    expect(refusalOf(stale)).toBe("stale");
    expect(refusalOf(conflict)).toBe("conflict");
  });

  it("names the other refusals a form meets", () => {
    expect(refusalOf(invalid)).toBe("invalid");
    expect(refusalOf(new ApiError({ status: 403, title: "Not allowed" }))).toBe("forbidden");
    expect(refusalOf(new ApiError({ status: 404, title: "Not found" }))).toBe("missing");
    expect(refusalOf(new ApiError({ status: 0, title: "No answer" }))).toBe("unreachable");
    expect(refusalOf(new ApiError({ status: 500, title: "Internal Server Error" }))).toBe("other");
  });

  it("does not take a 409 with another title for a stale version", () => {
    expect(refusalOf(new ApiError({ status: 409, title: "stale version" }))).toBe("conflict");
    expect(refusalOf(new ApiError({ status: 422, title: "Stale version" }))).toBe("invalid");
  });
});

describe("fieldErrors", () => {
  const known = ["disposition", "expected_online", "est_value", "tags"];

  it("puts a message beside the field the server named", () => {
    expect(fieldErrors(invalid, known)).toEqual({
      shown: { disposition: "an item in Prod is one of Production, Spare, not Excess" },
      rest: [],
    });
  });

  it("keeps a message about a field the form does not show, to be listed above it", () => {
    const error = new ApiError({
      status: 422,
      title: "Invalid input",
      fields: { est_value: "a number that is not negative", row_version: "Field required" },
    });
    expect(fieldErrors(error, known)).toEqual({
      shown: { est_value: "a number that is not negative" },
      rest: [["row_version", "Field required"]],
    });
  });

  it("matches an entry of a list, and a query parameter, to the field of that name", () => {
    const error = new ApiError({
      status: 422,
      title: "Invalid input",
      fields: {
        "tags.0": "String should have at most 100 characters",
        "tags.3": "Input should be a valid string",
        "query.limit": "Input should be less than or equal to 1000",
      },
    });
    const sorted = fieldErrors(error, [...known, "limit"]);
    expect(sorted.shown).toEqual({
      tags: "String should have at most 100 characters; Input should be a valid string",
      limit: "Input should be less than or equal to 1000",
    });
    expect(sorted.rest).toEqual([]);
  });

  it("has nothing to show for a stale version, a collision, or no error", () => {
    expect(fieldErrors(stale, known)).toEqual({ shown: {}, rest: [] });
    expect(fieldErrors(conflict, known)).toEqual({ shown: {}, rest: [] });
    expect(fieldErrors(null, known)).toEqual({ shown: {}, rest: [] });
  });
});
