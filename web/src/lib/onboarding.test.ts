import { describe, expect, it } from "vitest";
import {
  accessCodeHint,
  behindOperator,
  briefMark,
  briefText,
  CONTACTS_GAPS,
  colourOnShow,
  contactsAddress,
  followedLabel,
  followUsername,
  gapShown,
  goneGroups,
  goneWords,
  groupGrants,
  labelProblem,
  leastCodeLength,
  NEW_USER_FIELDS,
  type NewUserForm,
  newUserBody,
  newUserErrors,
  operatorLabelOf,
  operatorsCell,
  queryOf,
  refusedField,
  typeLabel,
  USERS_GAPS,
  usersAddress,
  usersGapOf,
  usersGapQuery,
} from "./onboarding";
import { NO_NEW_PERSON, personChoice } from "./people";

describe("a group's box says what the group grants (P-282)", () => {
  it("names each role as people read it, or that it grants none", () => {
    expect(groupGrants(["inventory"])).toBe("grants Inventory");
    expect(groupGrants(["viewer", "admin"])).toBe("grants View-only, Admin");
    expect(groupGrants([])).toBe("grants nothing");
    // The box is named by it in the New user form, beside the field Role.
    for (const roles of [[], ["admin"], ["viewer", "inventory"]]) {
      expect(groupGrants(roles)).not.toMatch(/role/i);
    }
  });
});

describe("a group deleted under an open form is said so by its name (P-282)", () => {
  const listed = [
    { hid: "G1", name: "ex-network" },
    { hid: "G2", name: "ex-servers" },
    { hid: "G3", name: "ex-lab" },
  ];

  it("names the groups asked for that the server no longer has", () => {
    expect(goneGroups(listed, [{ hid: "G1" }], ["G1", "G2"])).toEqual(["ex-servers"]);
    expect(goneGroups(listed, [{ hid: "G1" }], ["G1"])).toEqual([]);
    expect(goneGroups(listed, [], ["G2", "G3"])).toEqual(["ex-servers", "ex-lab"]);
  });

  it("says it in words, one group or several", () => {
    expect(goneWords(["ex-lab"])).toBe(
      "The group ex-lab is gone: it was deleted after this was read, and its box is taken away.",
    );
    expect(goneWords(["ex-lab", "ex-servers"])).toMatch(/^The groups ex-lab, ex-servers are gone/);
  });
});

describe("the label of a new user's operator follows the username (P-283)", () => {
  it("follows as the username is typed", () => {
    let label = followedLabel("");
    for (const typed of ["e", "ex", "ex-ops"]) label = followUsername(label, typed);
    expect(label).toEqual({ label: "ex-ops", filled: "ex-ops" });
  });

  it("stays as typed over, whatever the username becomes", () => {
    let label = followUsername(followedLabel(""), "ex-ops");
    label = typeLabel(label, "EO");
    label = followUsername(label, "ex-ops2");
    expect(label.label).toBe("EO");
  });

  it("follows again once what was typed over it is blank", () => {
    let label = typeLabel(followUsername(followedLabel(""), "ex"), "EO");
    label = typeLabel(label, "");
    expect(followUsername(label, "ex-ops").label).toBe("ex-ops");
  });

  it("follows while what was typed is what the form had filled in", () => {
    const label = typeLabel(followUsername(followedLabel(""), "ex-ops"), "ex-ops");
    expect(followUsername(label, "ex-ops2").label).toBe("ex-ops2");
  });
});

describe("Make an operator labels it by the person (P-284)", () => {
  it("is the username where the contact is a user, else the contact's name", () => {
    expect(operatorLabelOf({ name: "Example Person", user: { username: "ex-ops" } })).toBe(
      "ex-ops",
    );
    expect(operatorLabelOf({ name: "Example Person", user: null })).toBe("Example Person");
    expect(operatorLabelOf({ name: "Example Person" })).toBe("Example Person");
  });

  it("says what is wrong with a label in plain words, before anything is sent", () => {
    expect(labelProblem("ex-ops")).toBeNull();
    expect(labelProblem("x".repeat(40))).toBeNull();
    expect(labelProblem("x".repeat(41))).toBe(
      "A label is at most 40 characters, and this one has 41: choose a shorter one.",
    );
    expect(labelProblem(" ")).toMatch(/^A label is needed/);
    expect(labelProblem("ex;ops")).toMatch(/no semicolon/);
  });

  it("opens its fields for a refusal of the label or the colour, not of the whole", () => {
    expect(refusedField({ label: "another operator has this label" })).toBe(true);
    expect(refusedField({ colour: "in the form #1f6feb" })).toBe(true);
    expect(refusedField({ "operator.label": "too long" })).toBe(true);
    expect(refusedField({ contact_hid: "this contact is retired" })).toBe(false);
    expect(refusedField({})).toBe(false);
  });
});

const PERSON: NewUserForm = {
  username: " ex-ops ",
  service: false,
  alsoContact: true,
  person: { ...personChoice("new"), person: { ...NO_NEW_PERSON, name: "Example Person" } },
  alsoOperator: true,
  label: "ex-ops",
  colour: "#1f6feb",
  role: "inventory",
  groupHids: ["G1", "G2"],
  notes: " For the network team. ",
  accessCode: "",
};

describe("one Create sends what a new person needs (P-281 to P-283)", () => {
  it("sends the user, a new contact, the operator, the role, the groups and the notes", () => {
    expect(newUserBody(PERSON)).toEqual({
      ok: true,
      body: {
        username: "ex-ops",
        is_service_account: false,
        contact: { name: "Example Person" },
        operator: { label: "ex-ops", colour: "#1f6feb" },
        role: "inventory",
        group_hids: ["G1", "G2"],
        notes: "For the network team.",
      },
    });
  });

  it("sends the colour on show: the one chosen, or the next as it was read", () => {
    expect(colourOnShow(null, "#0169cd")).toBe("#0169cd");
    expect(colourOnShow("#a35303", "#0169cd")).toBe("#a35303");
    expect(colourOnShow("", "#0169cd")).toBe("");
    expect(colourOnShow(null, undefined)).toBeNull();
    const read = newUserBody({ ...PERSON, colour: colourOnShow(null, "#0169cd") });
    expect(read.ok && read.body.operator).toEqual({ label: "ex-ops", colour: "#0169cd" });
  });

  it("leaves a blank label, and a colour while none is shown, to the server", () => {
    const read = newUserBody({ ...PERSON, label: " ", colour: null });
    expect(read.ok && read.body.operator).toEqual({});
  });

  it("reads the colour as the picker does: none sent where it is no colour", () => {
    const wrong = newUserBody({ ...PERSON, colour: "rubbish" });
    expect(wrong).toMatchObject({ ok: false, field: "colour" });
    expect(!wrong.ok && wrong.error).not.toBe("");
    const upper = newUserBody({ ...PERSON, colour: " #1F6FEB " });
    expect(upper.ok && upper.body.operator).toEqual({ label: "ex-ops", colour: "#1f6feb" });
    // Without an operator, the colour is not read at all.
    expect(newUserBody({ ...PERSON, alsoOperator: false, colour: "rubbish" }).ok).toBe(true);
  });

  it("sends a colour chosen blank as none", () => {
    const read = newUserBody({ ...PERSON, colour: " " });
    expect(read.ok && read.body.operator).toEqual({ label: "ex-ops", colour: null });
  });

  it("sends a contact there is by its HID", () => {
    const read = newUserBody({ ...PERSON, person: personChoice("contact", "C1") });
    expect(read.ok && read.body.contact_hid).toBe("C1");
    expect(read.ok && "contact" in read.body).toBe(false);
  });

  it("sends no operator where its box is unticked, and neither without a contact", () => {
    const noOperator = newUserBody({ ...PERSON, alsoOperator: false });
    expect(noOperator.ok && "operator" in noOperator.body).toBe(false);
    const nobody = newUserBody({ ...PERSON, alsoContact: false });
    expect(nobody.ok && ("operator" in nobody.body || "contact" in nobody.body)).toBe(false);
  });

  it("sends a service account with neither, nor an access code", () => {
    const read = newUserBody({ ...PERSON, service: true, accessCode: "kept-out" });
    expect(read).toEqual({
      ok: true,
      body: {
        username: "ex-ops",
        is_service_account: true,
        role: "inventory",
        group_hids: ["G1", "G2"],
        notes: "For the network team.",
      },
    });
  });

  it("leaves out no group, no role, blank notes, and sends an access code given", () => {
    const read = newUserBody({ ...PERSON, groupHids: [], role: "", notes: " ", accessCode: "x" });
    expect(read.ok && read.body).toMatchObject({ access_code: "x" });
    expect(read.ok && ["group_hids", "role", "notes"].some((key) => key in read.body)).toBe(false);
  });

  it("says what is missing of the person before anything is sent", () => {
    expect(newUserBody({ ...PERSON, person: personChoice("new") })).toEqual({
      ok: false,
      field: "name",
      error: "A new person needs a name.",
    });
    expect(newUserBody({ ...PERSON, person: personChoice("contact") })).toMatchObject({
      ok: false,
      field: "contact_hid",
    });
  });
});

describe("who is what, on the lists of people (P-280)", () => {
  const brief = (label: string, record_status: "active" | "retired" | "draft") => ({
    hid: `O-${label}`,
    label,
    colour: "#1f6feb",
    record_status,
  });

  it("marks an operator by its label in its colour, released where it is retired", () => {
    expect(briefMark(brief("ex-ops", "active"))).toEqual({
      hid: "O-ex-ops",
      label: "ex-ops",
      colour: "#1f6feb",
      person: "",
      open: false,
      released: false,
    });
    expect(briefMark(brief("ex-ops", "retired")).released).toBe(true);
    expect(briefMark({ ...brief("ex-ops", "active"), colour: "red" }).colour).toBeNull();
  });

  it("marks an operator open where the contact behind it is retired", () => {
    const left = briefMark(brief("ex-ops", "active"), {
      name: "Example Person",
      record_status: "retired",
    });
    expect(left).toMatchObject({ open: true, person: "Example Person", released: false });
    const there = briefMark(brief("ex-ops", "active"), {
      name: "Example Person",
      record_status: "active",
    });
    expect(there).toMatchObject({ open: false, person: "" });
    expect(briefMark(brief("ex-ops", "active"), null).open).toBe(false);
  });

  it("writes a contact's operators on the list: released ones marked, none in words", () => {
    expect(operatorsCell([])).toEqual({ text: "", links: [] });
    const cell = operatorsCell([brief("old", "retired"), brief("new", "active")]);
    expect(cell.text).toBe("old (released), new");
    expect(cell.links).toEqual([
      { text: "old (released)", path: "/operators/O-old" },
      { text: "new", path: "/operators/O-new" },
    ]);
    expect(briefText(brief("new", "draft"))).toBe("new");
  });

  it("counts a person behind retired operators alone as behind none", () => {
    expect(behindOperator([])).toBe(false);
    expect(behindOperator([brief("old", "retired")])).toBe(false);
    expect(behindOperator([brief("old", "retired"), brief("new", "draft")])).toBe(true);
  });

  it("keeps the gap of the users in the address, and asks the server for it", () => {
    expect(USERS_GAPS.map((gap) => gap.value)).toEqual([
      "",
      "no-contact",
      "no-operator",
      "retired",
    ]);
    expect(usersGapOf(new URLSearchParams("contact=none"))).toBe("no-contact");
    expect(usersGapOf(new URLSearchParams("operator=none&q=ex"))).toBe("no-operator");
    expect(usersGapOf(new URLSearchParams("contact=some"))).toBe("");
    expect(usersGapQuery("no-contact")).toEqual({ contact: "none" });
    expect(usersGapQuery("no-operator")).toEqual({ operator: "none" });
    expect(usersGapQuery("")).toEqual({});
    expect(queryOf(usersAddress("ex ops", "no-operator", 50))).toBe(
      "?q=ex+ops&operator=none&offset=50",
    );
    expect(queryOf(usersAddress("", "", 0))).toBe("");
  });

  it("keeps the retired accounts, asked for by themselves, in the address (P-292)", () => {
    expect(USERS_GAPS.find((gap) => gap.value === "retired")?.label).toBe("Retired users");
    expect(usersGapOf(new URLSearchParams("retired=only"))).toBe("retired");
    // Retired with the rest is no view of the page, and a retired account is in no gap.
    expect(usersGapOf(new URLSearchParams("retired=yes"))).toBe("");
    expect(usersGapOf(new URLSearchParams("retired=only&contact=none"))).toBe("retired");
    expect(usersGapQuery("retired")).toEqual({ retired: "only" });
    expect(queryOf(usersAddress("lee", "retired", 50))).toBe("?q=lee&retired=only&offset=50");
  });

  it("marks a gap of a grid only while the grid's filter is that gap's", () => {
    const behindNone = { field: "is_operator", op: "eq", value: "false" } as const;
    // Before the grid has asked, as the address started it; a plain visit is the whole.
    expect(gapShown("is_operator:eq:false", undefined, "is_operator:eq:false")).toBe(true);
    expect(gapShown("", undefined, null)).toBe(true);
    expect(gapShown("is_operator:eq:false", undefined, null)).toBe(false);
    // Once it has asked: what it asked, whatever the address still says.
    expect(gapShown("is_operator:eq:false", behindNone, "is_operator:eq:false")).toBe(true);
    const noUser = { field: "is_user", op: "eq", value: "false" } as const;
    expect(gapShown("is_operator:eq:false", noUser, "is_operator:eq:false")).toBe(false);
    expect(gapShown("is_user:eq:false", noUser, "is_operator:eq:false")).toBe(true);
    expect(gapShown("", null, "is_operator:eq:false")).toBe(true);
    expect(gapShown("", behindNone, "")).toBe(false);
    // A filter the short form cannot say is no gap's.
    expect(gapShown("", { or: [behindNone, noUser] }, "")).toBe(false);
  });

  it("starts the list of contacts at each gap, and the whole with a blank filter", () => {
    expect(CONTACTS_GAPS.map((gap) => contactsAddress(gap.filter))).toEqual([
      "/contacts?filter=",
      "/contacts?filter=is_user%3Aeq%3Afalse",
      "/contacts?filter=is_operator%3Aeq%3Afalse",
    ]);
  });
});

describe("a refusal of a new user is said at its field (P-283)", () => {
  it("puts each part where the form shows it", () => {
    expect(
      newUserErrors({
        username: "taken",
        "contact.email": "another contact has this email",
        "operator.label": "another operator has this label",
        "operator.colour": "in the form #1f6feb",
        operator: "needs a contact",
        "group_hids.1": "no such group",
        notes: "too long",
      }),
    ).toEqual({
      username: "taken",
      email: "another contact has this email",
      label: "another operator has this label",
      colour: "in the form #1f6feb",
      operator: "needs a contact",
      group_hids: "no such group",
      notes: "too long",
    });
  });

  it("names every field the server may refuse as one the form shows", () => {
    for (const field of ["operator.label", "group_hids", "contact.name", "notes", "operator"]) {
      expect(NEW_USER_FIELDS).toContain(field);
    }
  });
});

describe("a typed access code has a least length, which the form says (P-295)", () => {
  it("reads the length from the settings, a whole number of 1 or more", () => {
    const settings = [
      { key: "currency", value: "USD" },
      { key: "access_code_min_length", value: 12 },
    ];
    expect(leastCodeLength(settings)).toBe(12);
    expect(leastCodeLength([{ key: "access_code_min_length", value: 1 }])).toBe(1);
    // Not read yet, not there, or no length: the form says none.
    expect(leastCodeLength(undefined)).toBeNull();
    expect(leastCodeLength([{ key: "currency", value: "USD" }])).toBeNull();
    for (const value of ["12", 0, 12.5, null]) {
      expect(leastCodeLength([{ key: "access_code_min_length", value }])).toBeNull();
    }
  });

  it("says the length under the field, and that an empty one is generated", () => {
    expect(accessCodeHint(12)).toBe(
      "Leave empty to have one generated. One typed here has at least 12 characters.",
    );
    expect(accessCodeHint(1)).toBe(
      "Leave empty to have one generated. One typed here has at least 1 character.",
    );
    expect(accessCodeHint(null)).toBe("Leave empty to have one generated");
  });
});
