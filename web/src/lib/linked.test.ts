import { describe, expect, it } from "vitest";
import {
  backChanged,
  blockedWords,
  bringBackBody,
  bringBackOffer,
  type Choices,
  contactGoes,
  contactUses,
  goWords,
  held,
  keptChoices,
  LINKED_LABELS,
  LIST_CHANGED,
  type Linked,
  type LinkedContact,
  type LinkedOperator,
  type LinkedUser,
  nothingLinked,
  notSaidLead,
  type On,
  operatorUses,
  othersOf,
  ownAccountGoes,
  refusedHandOvers,
  refusedRows,
  retireBody,
  retiredBehind,
  retiredWords,
  rowOf,
  sameOthers,
  startChoices,
  userState,
} from "./linked";

const USER: LinkedUser = {
  hid: "U1",
  username: "klee",
  record_status: "active",
  disabled: false,
  role: null,
};
const CONTACT: LinkedContact = {
  hid: "C1",
  name: "Kim Lee",
  email: "klee@example.com",
  record_status: "active",
  uses: 3,
};
const KL: LinkedOperator = {
  hid: "O1",
  label: "KL",
  colour: "#1f6feb",
  record_status: "active",
  uses: 12,
};
const OP2: LinkedOperator = {
  hid: "O2",
  label: "Op2",
  colour: null,
  record_status: "active",
  uses: 0,
};
const OLD: LinkedOperator = {
  hid: "O3",
  label: "Old",
  colour: null,
  record_status: "retired",
  uses: 0,
};

/** A user who is a contact behind two labels, and a third that is released. */
const PERSON: Linked = { user: USER, contact: CONTACT, operators: [KL, OP2, OLD] };

const ON_USER: On = { kind: "user", hid: "U1" };
const ON_CONTACT: On = { kind: "contact", hid: "C1" };
const ON_KL: On = { kind: "operator", hid: "O1" };

function choose(was: Choices, hid: string, action: string, contactHid = ""): Choices {
  return {
    ...was,
    operators: { ...was.operators, [hid]: { action, contactHid } },
  } as Choices;
}

describe("what a retirement has to say something of (P-297)", () => {
  it("is every linked record that is not retired, other than the one it is on", () => {
    expect(othersOf(ON_USER, PERSON)).toEqual({
      user: null,
      contact: CONTACT,
      operators: [KL, OP2],
    });
    expect(othersOf(ON_CONTACT, PERSON)).toEqual({
      user: USER,
      contact: null,
      operators: [KL, OP2],
    });
    expect(othersOf(ON_KL, PERSON)).toEqual({ user: USER, contact: CONTACT, operators: [OP2] });
  });

  it("leaves out what is retired already", () => {
    const left: Linked = {
      user: { ...USER, record_status: "retired" },
      contact: { ...CONTACT, record_status: "retired" },
      operators: [KL, OLD],
    };
    expect(othersOf(ON_KL, left)).toEqual({ user: null, contact: null, operators: [] });
    expect(nothingLinked(ON_KL, left)).toBe(true);
  });

  it("is nothing for a record that answers itself alone", () => {
    expect(nothingLinked(ON_USER, { user: USER, contact: null, operators: [] })).toBe(true);
    expect(
      nothingLinked(
        { kind: "operator", hid: "O2" },
        { user: null, contact: null, operators: [OP2] },
      ),
    ).toBe(true);
    expect(nothingLinked(ON_USER, PERSON)).toBe(false);
  });
});

describe("the confirmation opens with Retire ticked for each linked record (P-291)", () => {
  it("ticks the account and the contact, and releases each label", () => {
    expect(startChoices(ON_KL, PERSON, true)).toEqual({
      user: true,
      contact: true,
      operators: { O2: { action: "retire", contactHid: "" } },
    });
    expect(startChoices(ON_USER, PERSON, true)).toEqual({
      user: false,
      contact: true,
      operators: {
        O1: { action: "retire", contactHid: "" },
        O2: { action: "retire", contactHid: "" },
      },
    });
  });

  it("shows the account unticked to somebody who is no Admin, and so the contact stays", () => {
    const start = startChoices(ON_KL, PERSON, false);
    expect(start.user).toBe(false);
    expect(start.contact).toBe(false);
    expect(start.operators.O2).toEqual({ action: "retire", contactHid: "" });
  });

  it("lets the Inventory role retire a contact that is no user's, with its labels", () => {
    const external: Linked = { user: null, contact: CONTACT, operators: [KL] };
    expect(startChoices(ON_KL, external, false).contact).toBe(true);
    expect(blockedWords(ON_CONTACT, external, false)).toBeNull();
  });
});

describe("a contact is not retired while its account or a label stands on it (P-291)", () => {
  it("retires the account with the contact, and keeps no label", () => {
    const start = startChoices(ON_KL, PERSON, true);
    const asked = choose({ ...start, user: false }, "O2", "keep");
    // The contact is still ticked: the account is not kept, nor the label.
    const firm = held(ON_KL, PERSON, asked, true);
    expect(firm.user).toBe(true);
    expect(firm.operators.O2?.action).toBe("retire");
    expect(contactGoes(ON_KL, PERSON, firm)).toBe(true);
  });

  it("lets both be kept once the contact is unticked", () => {
    const start = startChoices(ON_KL, PERSON, true);
    const asked = choose({ ...start, contact: false, user: false }, "O2", "keep");
    const firm = held(ON_KL, PERSON, asked, true);
    expect(firm).toEqual({
      user: false,
      contact: false,
      operators: { O2: { action: "keep", contactHid: "" } },
    });
    expect(contactGoes(ON_KL, PERSON, firm)).toBe(false);
  });

  it("holds the rule on the contact's own page, where the contact always goes", () => {
    const asked = choose({ user: false, contact: false, operators: {} }, "O1", "keep");
    const firm = held(ON_CONTACT, PERSON, asked, true);
    expect(firm.user).toBe(true);
    expect(firm.operators.O1?.action).toBe("retire");
    expect(contactGoes(ON_CONTACT, PERSON, firm)).toBe(true);
  });

  it("keeps a label handed over or left open with the contact going", () => {
    let asked = startChoices(ON_CONTACT, PERSON, true);
    asked = choose(asked, "O1", "hand_over", "C9");
    asked = choose(asked, "O2", "open");
    const firm = held(ON_CONTACT, PERSON, asked, true);
    expect(firm.operators).toEqual({
      O1: { action: "hand_over", contactHid: "C9" },
      O2: { action: "open", contactHid: "" },
    });
  });

  it("tells somebody who is no Admin to ask one, on the page of a contact with an account", () => {
    expect(blockedWords(ON_CONTACT, PERSON, false)).toBe(
      "An Admin retires an account, and a contact is not retired while its account stands on it. Ask an Admin to retire klee with this contact.",
    );
    expect(blockedWords(ON_CONTACT, PERSON, true)).toBeNull();
    expect(blockedWords(ON_KL, PERSON, false)).toBeNull();
    // An account that is retired already stands on nothing.
    const left: Linked = { ...PERSON, user: { ...USER, record_status: "retired" } };
    expect(blockedWords(ON_CONTACT, left, false)).toBeNull();
  });
});

describe("one Retire sends one request that says every linked record (P-297)", () => {
  it("says each, the kept among them, and not the record it is on", () => {
    let asked = startChoices(ON_CONTACT, PERSON, true);
    asked = choose(asked, "O1", "hand_over", "C9");
    expect(retireBody(ON_CONTACT, PERSON, asked, 4, true)).toEqual({
      ok: true,
      body: {
        row_version: 4,
        linked: {
          user: "retire",
          operators: [
            { hid: "O1", action: "hand_over", contact_hid: "C9" },
            { hid: "O2", action: "retire" },
          ],
        },
      },
    });
  });

  it("says keep of what is unticked", () => {
    let asked = { ...startChoices(ON_KL, PERSON, true), contact: false, user: false };
    asked = choose(asked, "O2", "keep");
    expect(retireBody(ON_KL, PERSON, asked, 7, true)).toEqual({
      ok: true,
      body: {
        row_version: 7,
        linked: { user: "keep", contact: "keep", operators: [{ hid: "O2", action: "keep" }] },
      },
    });
  });

  it("sends the version alone where nothing is linked", () => {
    const alone: Linked = { user: USER, contact: null, operators: [] };
    expect(retireBody(ON_USER, alone, startChoices(ON_USER, alone, true), 2, true)).toEqual({
      ok: true,
      body: { row_version: 2 },
    });
  });

  it("sends nothing while a label is handed over to nobody, or to the person it has", () => {
    let asked = startChoices(ON_USER, PERSON, true);
    asked = choose(asked, "O1", "hand_over");
    asked = choose(asked, "O2", "hand_over", "C1");
    expect(retireBody(ON_USER, PERSON, asked, 4, true)).toEqual({
      ok: false,
      errors: {
        "operator O1": "Choose the person the label is handed over to, or another choice.",
        "operator O2": "This is the person behind the label now: choose another person.",
      },
    });
  });

  it("says Keep only where Keep is a choice: with the contact kept (review 6)", () => {
    // With the contact going, as above, Keep is not offered, and is not said.
    let asked = { ...startChoices(ON_USER, PERSON, true), contact: false };
    asked = choose(asked, "O2", "hand_over", "C1");
    expect(retireBody(ON_USER, PERSON, asked, 4, true)).toEqual({
      ok: false,
      errors: {
        "operator O2": "This is the person behind the label now: choose another person, or Keep.",
      },
    });
  });

  it("keeps the account, and so the contact, for somebody who is no Admin", () => {
    const asked = { ...startChoices(ON_KL, PERSON, false), user: true, contact: true };
    const built = retireBody(ON_KL, PERSON, asked, 1, false);
    expect(built.ok && built.body.linked).toEqual({
      user: "keep",
      contact: "keep",
      operators: [{ hid: "O2", action: "retire" }],
    });
  });
});

describe("a refusal is said in the confirmation, at the record it names", () => {
  it("puts what is said of the account and of the contact at the row of each", () => {
    const found = refusedRows({
      "linked.user": "the contact is retired, so the user klee is retired with it",
      "linked.contact": "say what becomes of the contact Kim Lee: retire or keep",
      "linked.operators": "the contact is retired, so KL is retired, opened or handed over",
      row_version: "is needed",
    });
    expect(found.rows).toEqual({
      [rowOf("user")]: "the contact is retired, so the user klee is retired with it",
      [rowOf("contact")]: "say what becomes of the contact Kim Lee: retire or keep",
    });
    expect(found.shown).toEqual(["linked.user", "linked.contact"]);
  });

  it("leaves above the rows what is said of the labels as a whole, as a sentence", () => {
    expect(refusedRows({ "linked.operators": "say what becomes of KL and Op2" })).toEqual({
      rows: {},
      shown: [],
    });
    expect(LINKED_LABELS["linked.operators"]).toBe("");
  });

  it("puts what is said of the labels at each hand-over it is given", () => {
    const fields = { "linked.operators": "the operator KL: the contact Sam Okafor is retired" };
    expect(refusedRows(fields, ["O1"])).toEqual({
      rows: { [rowOf("operator", "O1")]: "the operator KL: the contact Sam Okafor is retired" },
      shown: ["linked.operators"],
    });
  });

  it("keeps what was chosen when the list is read again, and ticks what is new", () => {
    const before: Linked = { user: USER, contact: CONTACT, operators: [KL] };
    let asked = { ...startChoices(ON_USER, before, true), contact: false };
    asked = choose(asked, "O1", "keep");
    const now = keptChoices(ON_USER, { linked: before, choices: asked }, PERSON, true);
    expect(now).toEqual({
      user: false,
      contact: false,
      operators: {
        O1: { action: "keep", contactHid: "" },
        O2: { action: "retire", contactHid: "" },
      },
    });
    // A contact given to the account since is ticked, as at the start.
    const bare: Linked = { user: USER, contact: null, operators: [] };
    const start = startChoices(ON_USER, bare, true);
    expect(keptChoices(ON_USER, { linked: bare, choices: start }, PERSON, true).contact).toBe(true);
  });
});

describe("how much each is on is said beside it", () => {
  it("counts what names a contact and what a label is given to", () => {
    expect(contactUses(0)).toBe("named nowhere");
    expect(contactUses(1)).toBe("named by 1 record");
    expect(contactUses(1234)).toBe("named by 1,234 records");
    expect(operatorUses(0)).toBe("given to nothing");
    expect(operatorUses(1)).toBe("given to 1 item, group or place");
    expect(operatorUses(12)).toBe("given to 12 items, groups and places");
  });
});

describe("the state of an account in a word (P-292)", () => {
  it("is Retired before it is Disabled or Active", () => {
    expect(userState({ record_status: "active", disabled: false })).toBe("Active");
    expect(userState({ record_status: "active", disabled: true })).toBe("Disabled");
    expect(userState({ record_status: "retired", disabled: false })).toBe("Retired");
    expect(userState({ record_status: "retired", disabled: true })).toBe("Retired");
    expect(userState({ disabled: false })).toBe("Active");
  });
});

describe("what a page says once a retirement is done", () => {
  it("names the record, what went with it, and what became of each label", () => {
    let asked = startChoices(ON_CONTACT, PERSON, true);
    asked = choose(asked, "O1", "hand_over", "C9");
    expect(retiredWords(ON_CONTACT, PERSON, asked, true, { O1: "Sam Okafor" })).toBe(
      "Kim Lee was retired, with the account klee. KL was handed over to Sam Okafor and Op2 was released.",
    );
  });

  it("says what stays", () => {
    let asked = { ...startChoices(ON_KL, PERSON, true), contact: false, user: false };
    asked = choose(asked, "O2", "keep");
    expect(retiredWords(ON_KL, PERSON, asked, true)).toBe(
      "KL was released. The account klee, the contact Kim Lee and the label Op2 stay.",
    );
    asked = choose(asked, "O2", "open");
    expect(retiredWords(ON_USER, PERSON, { ...asked, contact: true }, true)).toBe(
      "klee was retired, with the contact Kim Lee. KL was released and Op2 was left open.",
    );
  });

  it("says the record alone where nothing is linked", () => {
    const alone: Linked = { user: USER, contact: null, operators: [] };
    expect(retiredWords(ON_USER, alone, startChoices(ON_USER, alone, true), true)).toBe(
      "klee was retired.",
    );
  });
});

describe("Bring back of a user offers its retired contact and that contact's labels (P-298)", () => {
  const left: Linked = {
    user: { ...USER, record_status: "retired" },
    contact: { ...CONTACT, record_status: "retired" },
    operators: [{ ...KL, record_status: "retired" }, OP2, OLD],
  };

  it("offers the contact where it is retired, and the labels that are", () => {
    expect(bringBackOffer(left)).toEqual({
      contact: left.contact,
      operators: [{ ...KL, record_status: "retired" }, OLD],
    });
    expect(bringBackOffer({ ...left, contact: CONTACT }).contact).toBeNull();
    expect(bringBackOffer({ user: left.user, contact: null, operators: [] })).toEqual({
      contact: null,
      operators: [],
    });
  });

  it("sends the contact, which is needed, and only the labels ticked", () => {
    expect(bringBackBody(left, [], 5)).toEqual({
      row_version: 5,
      linked: { contact: "bring_back" },
    });
    expect(bringBackBody(left, ["O3", "O2"], 5)).toEqual({
      row_version: 5,
      linked: { contact: "bring_back", operators: [{ hid: "O3", action: "bring_back" }] },
    });
  });

  it("sends the version alone for an account with nothing retired to bring", () => {
    const alone: Linked = { user: left.user, contact: null, operators: [] };
    expect(bringBackBody(alone, [], 3)).toEqual({ row_version: 3 });
  });

  it("sends the role chosen, and none where none is (P-299)", () => {
    const alone: Linked = { user: left.user, contact: null, operators: [] };
    expect(bringBackBody(alone, [], 3, "viewer")).toEqual({ row_version: 3, role: "viewer" });
    expect(bringBackBody(left, [], 5, "admin")).toEqual({
      row_version: 5,
      linked: { contact: "bring_back" },
      role: "admin",
    });
    expect(bringBackBody(alone, [], 3, "")).toEqual({ row_version: 3 });
  });
});

describe("the linked records a refusal names (P-297)", () => {
  it("says that they are listed now, one or several", () => {
    expect(notSaidLead(1)).toBe(
      "Linked, and not listed when this opened. It is listed now: say what becomes of it.",
    );
    expect(notSaidLead(2)).toBe(
      "2 are linked, and were not listed when this opened. They are listed now: say what becomes of each.",
    );
  });
});

describe("an Admin who retires their own account is told so, and signed out by it", () => {
  it("is so on the account's own page, and where the account is ticked on another", () => {
    const start = startChoices(ON_CONTACT, PERSON, true);
    expect(ownAccountGoes(ON_USER, PERSON, start, true, "U1")).toBe(true);
    expect(ownAccountGoes(ON_USER, PERSON, start, true, "U7")).toBe(false);
    expect(ownAccountGoes(ON_CONTACT, PERSON, start, true, "U1")).toBe(true);
    expect(ownAccountGoes(ON_CONTACT, PERSON, start, true, "U7")).toBe(false);
  });

  it("is not so where the account is kept", () => {
    const kept = { ...startChoices(ON_KL, PERSON, true), contact: false, user: false };
    expect(ownAccountGoes(ON_KL, PERSON, kept, true, "U1")).toBe(false);
    // Somebody who is no Admin retires no account, their own neither.
    expect(ownAccountGoes(ON_KL, PERSON, startChoices(ON_KL, PERSON, false), false, "U1")).toBe(
      false,
    );
  });
});

describe("a label is not brought back onto a retired contact (P-298)", () => {
  const existing = { record_type: "contact", hid: "C1", label: "Kim Lee" };
  const refused = {
    status: 409,
    fields: { record_status: "a label is not brought back onto a retired contact" },
    existing,
  };

  it("names the contact the server refused it for", () => {
    expect(retiredBehind(refused)).toEqual({ hid: "C1", name: "Kim Lee" });
  });

  it("names none for another refusal, or for none", () => {
    expect(retiredBehind(null)).toBeNull();
    expect(retiredBehind({ ...refused, status: 403 })).toBeNull();
    expect(retiredBehind({ ...refused, fields: { label: "another operator has it" } })).toBeNull();
    const other = { record_type: "operator", hid: "O9", label: "KL" };
    expect(retiredBehind({ ...refused, existing: other })).toBeNull();
    expect(retiredBehind({ ...refused, existing: null })).toBeNull();
  });
});

describe("a list that changed while the confirmation was open (review 3)", () => {
  it("is the same list where the records to be said are the same, whatever else changed", () => {
    expect(sameOthers(ON_USER, PERSON, { ...PERSON, operators: [OP2, KL, OLD] })).toBe(true);
    const renamed: Linked = { ...PERSON, contact: { ...CONTACT, name: "Kim Okafor", uses: 9 } };
    expect(sameOthers(ON_USER, PERSON, renamed)).toBe(true);
  });

  it("is another list where a record is parted, retired or added", () => {
    // The label is parted from the contact.
    expect(sameOthers(ON_USER, PERSON, { ...PERSON, operators: [OP2, OLD] })).toBe(false);
    // The contact is taken off the account.
    expect(sameOthers(ON_USER, PERSON, { user: USER, contact: null, operators: [] })).toBe(false);
    // A label is released by somebody else.
    const released: Linked = { ...PERSON, operators: [{ ...KL, record_status: "retired" }, OP2] };
    expect(sameOthers(ON_CONTACT, PERSON, released)).toBe(false);
    // A label is added.
    const more: Linked = { ...PERSON, operators: [KL, OP2, { ...OLD, record_status: "active" }] };
    expect(sameOthers(ON_CONTACT, PERSON, more)).toBe(false);
  });

  it("says so in plain words, with no name of a field", () => {
    expect(LIST_CHANGED).toMatch(/^The linked records have changed since this was opened\./);
    expect(LIST_CHANGED).not.toMatch(/linked\.|row_version/);
  });
});

describe("a hand-over the server refuses is said at its field (review 3)", () => {
  const handed = (hids: string[]) => {
    let asked = startChoices(ON_CONTACT, PERSON, true);
    for (const hid of hids) asked = choose(asked, hid, "hand_over", "C9");
    return asked;
  };

  it("marks the label the sentence names, among those handed over", () => {
    const message = "the operator KL: the contact Sam Okafor is retired";
    expect(refusedHandOvers(message, ON_CONTACT, PERSON, handed(["O1", "O2"]))).toEqual(["O1"]);
  });

  it("marks each hand-over where the sentence names none of them", () => {
    const message = "a label is handed over to a contact that is not retired";
    expect(refusedHandOvers(message, ON_CONTACT, PERSON, handed(["O1", "O2"]))).toEqual([
      "O1",
      "O2",
    ]);
  });

  it("marks none where nothing is handed over, or nothing is refused of the labels", () => {
    expect(refusedHandOvers("the operator KL is kept", ON_CONTACT, PERSON, handed([]))).toEqual([]);
    expect(refusedHandOvers(undefined, ON_CONTACT, PERSON, handed(["O1"]))).toEqual([]);
  });
});

describe("Bring back says what changed while it was open (review 5)", () => {
  const user: LinkedUser = { ...USER, record_status: "retired" };
  const gone: LinkedContact = { ...CONTACT, record_status: "retired" };
  const label: LinkedOperator = { ...KL, record_status: "retired" };
  const was: Linked = { user, contact: gone, operators: [label] };

  it("says that the contact is back already, where somebody else brought it back", () => {
    expect(backChanged(was, { user, contact: CONTACT, operators: [label] })).toBe(
      "The contact Kim Lee is back already: it was brought back since this was opened. Press Bring back again to bring the account back.",
    );
  });

  it("says that the linked records have changed, where it is something else", () => {
    // A label is back, or the contact was taken off the account.
    expect(backChanged(was, { user, contact: gone, operators: [KL] })).toBe(LIST_CHANGED);
    expect(backChanged(was, { user, contact: null, operators: [] })).toBe(LIST_CHANGED);
  });

  it("says nothing where what is offered is what it was", () => {
    expect(
      backChanged(was, { user, contact: { ...gone, uses: 7 }, operators: [label] }),
    ).toBeNull();
  });
});

describe("the button that goes ahead says what it will do (review 9)", () => {
  it("counts what is retired with a label as it opens: the account, the contact, the other label", () => {
    expect(goWords(ON_KL, PERSON, startChoices(ON_KL, PERSON, true), true)).toBe(
      "Release KL and retire 3 more",
    );
  });

  it("follows the ticks, and says only where nothing else is retired", () => {
    let asked = { ...startChoices(ON_KL, PERSON, true), contact: false };
    expect(goWords(ON_KL, PERSON, asked, true)).toBe("Release KL and retire 2 more");
    asked = { ...asked, user: false };
    expect(goWords(ON_KL, PERSON, asked, true)).toBe("Release KL and retire 1 more");
    // A label handed over, left open or kept is not retired.
    for (const action of ["open", "hand_over", "keep"]) {
      expect(goWords(ON_KL, PERSON, choose(asked, "O2", action, "C9"), true)).toBe(
        "Release KL only",
      );
    }
  });

  it("is of the same manner on the page of the account and of the contact", () => {
    expect(goWords(ON_USER, PERSON, startChoices(ON_USER, PERSON, true), true)).toBe(
      "Retire klee and 3 more",
    );
    let kept = { ...startChoices(ON_USER, PERSON, true), contact: false };
    kept = choose(choose(kept, "O1", "keep"), "O2", "keep");
    expect(goWords(ON_USER, PERSON, kept, true)).toBe("Retire klee only");
    const open = choose(startChoices(ON_CONTACT, PERSON, true), "O2", "open");
    expect(goWords(ON_CONTACT, PERSON, open, true)).toBe("Retire Kim Lee and 2 more");
  });

  it("counts no account for somebody who is no Admin, who retires none", () => {
    expect(goWords(ON_KL, PERSON, startChoices(ON_KL, PERSON, false), false)).toBe(
      "Release KL and retire 1 more",
    );
  });
});
