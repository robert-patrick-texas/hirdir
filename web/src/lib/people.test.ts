import { describe, expect, it } from "vitest";
import {
  contactFinder,
  NO_NEW_PERSON,
  newPersonErrors,
  numbersText,
  personChoice,
  personLabel,
  readPerson,
  SCOPES,
  scopeHint,
  scopeLabel,
} from "./people";

describe("an operator internal or external (P-172)", () => {
  it("is internal where its person is a user, external where not, and neither where nobody is", () => {
    expect(SCOPES.map((scope) => scope.value)).toEqual(["internal", "external"]);
    expect(scopeLabel("internal")).toBe("Internal");
    expect(scopeLabel("external")).toBe("External");
    expect(scopeLabel(null)).toBe("");
    expect(scopeLabel(undefined)).toBe("");
    expect(scopeHint("internal")).toMatch(/is a user/);
    expect(scopeHint("external")).toMatch(/is not a user/);
    expect(scopeHint(null)).toBe("");
  });
});

describe("the person a form gives a user or an operator (P-172)", () => {
  it("is nobody, and sends neither a contact nor a new person", () => {
    expect(readPerson(personChoice("none"))).toEqual({ ok: true, contactHid: null, person: null });
  });

  it("is a contact chosen, which has to be chosen", () => {
    expect(readPerson(personChoice("contact", "ct-1"))).toEqual({
      ok: true,
      contactHid: "ct-1",
      person: null,
    });
    expect(readPerson(personChoice("user", "ct-2"))).toEqual({
      ok: true,
      contactHid: "ct-2",
      person: null,
    });
    expect(readPerson(personChoice("contact"))).toEqual({
      ok: false,
      field: "contact_hid",
      error: "Choose a contact.",
    });
    expect(readPerson(personChoice("user"))).toEqual({
      ok: false,
      field: "contact_hid",
      error: "Choose a user.",
    });
  });

  it("is a new person with a name, the rest sent only where it is typed", () => {
    const typed = {
      ...personChoice("new"),
      person: {
        ...NO_NEW_PERSON,
        name: "  Robin Achterberg ",
        email: " robin.achterberg@example.net",
        phone: "+1 555 0123",
        phone2: "   ",
      },
    };
    expect(readPerson(typed)).toEqual({
      ok: true,
      contactHid: null,
      person: {
        name: "Robin Achterberg",
        email: "robin.achterberg@example.net",
        phone: "+1 555 0123",
      },
    });
    const all = {
      ...personChoice("new"),
      person: {
        name: "Network Operations",
        email: "noc@example.org",
        organization: "Infrastructure Operations",
        phone: "+1 555 0100",
        phone2: "+1 555 0101",
      },
    };
    expect(readPerson(all)).toEqual({ ok: true, contactHid: null, person: all.person });
  });

  it("refuses a new person with no name, on the name", () => {
    const nameless = {
      ...personChoice("new"),
      person: { ...NO_NEW_PERSON, name: "  ", email: "someone@example.org" },
    };
    expect(readPerson(nameless)).toEqual({
      ok: false,
      field: "name",
      error: "A new person needs a name.",
    });
  });
});

describe("what the server refuses of a new person", () => {
  it("is said beside the field of the person, named with contact. or plainly", () => {
    expect(
      newPersonErrors({
        "contact.email": "another contact has this email address",
        "contact.phone2": "at most 50 characters",
        username: "taken",
      }),
    ).toEqual({
      email: "another contact has this email address",
      phone2: "at most 50 characters",
    });
    expect(newPersonErrors({ name: "must not be blank", role: "no such role" })).toEqual({
      name: "must not be blank",
    });
    expect(newPersonErrors({})).toEqual({});
  });
});

describe("the contacts a search offers", () => {
  it("are found by every word typed, and are users, or not, or either", () => {
    expect(contactFinder("")).toBeNull();
    expect(contactFinder("   ", true)).toBeNull();
    const either = contactFinder("lee");
    expect(either).toEqual({
      or: [
        { field: "name", op: "contains", value: "lee" },
        { field: "email", op: "contains", value: "lee" },
      ],
    });
    expect(contactFinder("lee", true)).toEqual({
      and: [either, { field: "is_user", op: "eq", value: true }],
    });
    expect(contactFinder("lee", false)).toEqual({
      and: [either, { field: "is_user", op: "eq", value: false }],
    });
  });

  it("are offered by name, address and the user each is", () => {
    expect(
      personLabel({
        name: "Lee Marchetti",
        email: "lee.marchetti@example.net",
        user: { username: "lmarchetti" },
      }),
    ).toBe("Lee Marchetti (lee.marchetti@example.net), user lmarchetti");
    expect(personLabel({ name: "Lee Marchetti", email: "lee.marchetti@example.net" })).toBe(
      "Lee Marchetti (lee.marchetti@example.net)",
    );
    expect(personLabel({ name: "Facilities Help Desk", email: null, user: null })).toBe(
      "Facilities Help Desk",
    );
  });
});

describe("the two numbers of a person", () => {
  it("are one line, the first first, with what is blank left out", () => {
    expect(numbersText("+1 555 0100", "+1 555 0101")).toBe("+1 555 0100 · +1 555 0101");
    expect(numbersText(null, "+1 555 0101")).toBe("+1 555 0101");
    expect(numbersText("+1 555 0100", "")).toBe("+1 555 0100");
    expect(numbersText(null, undefined)).toBe("");
  });
});
