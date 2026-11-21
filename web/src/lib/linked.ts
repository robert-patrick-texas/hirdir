// 0.9.14: the user, the contact and the operators of one person, retired together or
// parted first (P-291, P-297), and brought back by an Admin (P-298). The server answers
// who a record belongs to in `linked`, and a retirement says what becomes of each linked
// record. This holds what the confirmation works out before anything is sent: what is
// asked of each record, the one rule it holds, the request, and where a refusal is said.

import type { Schemas } from "../api/client";

/** The account of a person, as `linked` answers it. */
export type LinkedUser = Schemas["LinkedUser"];

/** The contact a person is, as `linked` answers it, with how much names it. */
export type LinkedContact = Schemas["LinkedContact"];

/** A label of a person, as `linked` answers it, with how much it is given to. */
export type LinkedOperator = Schemas["LinkedOperator"];

/** The person a record belongs to: `GET /users|contacts|operators/{hid}/linked`. */
export type Linked = Schemas["Person"];

/** Which of the three a page is of. */
export type PersonKind = "user" | "contact" | "operator";

/** The record a retirement is asked on: it is retired, and is not said in `linked`. */
export interface On {
  kind: PersonKind;
  hid: string;
}

/** What becomes of a label: released, handed over, left open, or kept. */
export type OperatorAction = "retire" | "hand_over" | "open" | "keep";

export interface OperatorChoice {
  action: OperatorAction;
  /** The contact a label is handed over to, or blank while none is chosen. */
  contactHid: string;
}

/** What the confirmation holds of each linked record. */
export interface Choices {
  /** Retire is ticked for the account. */
  user: boolean;
  /** Retire is ticked for the contact. */
  contact: boolean;
  /** What becomes of each label, by its HID. */
  operators: Readonly<Record<string, OperatorChoice>>;
}

/** What `linked` of a retirement says. */
export type LinkedSaid = Schemas["Linked"];

/** What a retire route takes: the version, and what becomes of each linked record. */
export type RetireBody = Schemas["Retirement"];

function standing(record: { hid: string; record_status: string } | null, on: On): boolean {
  return record !== null && record.record_status !== "retired" && record.hid !== on.hid;
}

/**
 * The linked records a retirement has to say something of: those that are not retired,
 * other than the one it is asked on.
 */
export function othersOf(on: On, linked: Linked): Linked {
  return {
    user: linked.user && standing(linked.user, on) ? linked.user : null,
    contact: linked.contact && standing(linked.contact, on) ? linked.contact : null,
    operators: linked.operators.filter((operator) => standing(operator, on)),
  };
}

/** Whether nothing that is not retired is linked: the record is retired by itself, as before. */
export function nothingLinked(on: On, linked: Linked): boolean {
  const others = othersOf(on, linked);
  return others.user === null && others.contact === null && others.operators.length === 0;
}

/** Whether the contact is retired by what is asked: by its own route, or ticked. */
export function contactGoes(on: On, linked: Linked, choices: Choices): boolean {
  if (on.kind === "contact") return true;
  return othersOf(on, linked).contact !== null && choices.contact;
}

/**
 * Why the retirement cannot be asked by this person at all, or null: a contact is not
 * retired while its account stands on it, and somebody who is no Admin retires no account.
 */
export function blockedWords(on: On, linked: Linked, admin: boolean): string | null {
  const account = othersOf(on, linked).user;
  if (on.kind !== "contact" || admin || account === null) return null;
  return `An Admin retires an account, and a contact is not retired while its account stands on it. Ask an Admin to retire ${account.username} with this contact.`;
}

/**
 * The choices held to the one rule (P-291): a contact is not retired while its account
 * or a label stands on it, so with the contact going the account goes too and no label
 * is kept. Somebody who is no Admin retires no account: it is kept, and so its contact is.
 */
export function held(on: On, linked: Linked, choices: Choices, admin: boolean): Choices {
  const others = othersOf(on, linked);
  const accountStays = others.user !== null && !admin;
  const contact = others.contact !== null && choices.contact && !accountStays;
  const going = on.kind === "contact" || contact;
  const operators: Record<string, OperatorChoice> = {};
  for (const operator of others.operators) {
    const was = choices.operators[operator.hid] ?? { action: "retire", contactHid: "" };
    operators[operator.hid] = going && was.action === "keep" ? { ...was, action: "retire" } : was;
  }
  return {
    user: others.user !== null && !accountStays && (going || choices.user),
    contact,
    operators,
  };
}

/** What the confirmation opens with: Retire ticked for each linked record (P-291). */
export function startChoices(on: On, linked: Linked, admin: boolean): Choices {
  return held(on, linked, { user: true, contact: true, operators: {} }, admin);
}

/**
 * The choices after `linked` was read again, as after a refusal that names a record that
 * was not listed: what was chosen is kept, a record that is new is ticked, as at the
 * start, and one that is gone or retired since is asked nothing.
 */
export function keptChoices(
  on: On,
  was: { linked: Linked; choices: Choices },
  now: Linked,
  admin: boolean,
): Choices {
  const before = othersOf(on, was.linked);
  return held(
    on,
    now,
    {
      user: before.user === null ? true : was.choices.user,
      contact: before.contact === null ? true : was.choices.contact,
      operators: was.choices.operators,
    },
    admin,
  );
}

/** The row of the confirmation a record has: where a refusal of it is said. */
export function rowOf(kind: PersonKind, hid = ""): string {
  return kind === "operator" ? `operator ${hid}` : kind;
}

/**
 * What one Retire sends, or what is still to be chosen, by the row it is said at.
 * Every linked record that is not retired is said, a kept one too, so that nothing
 * changes and nothing is left without being said. With nothing linked, the version alone.
 */
export function retireBody(
  on: On,
  linked: Linked,
  choices: Choices,
  rowVersion: number,
  admin: boolean,
): { ok: true; body: RetireBody } | { ok: false; errors: Record<string, string> } {
  const others = othersOf(on, linked);
  const firm = held(on, linked, choices, admin);
  const errors: Record<string, string> = {};
  const said: LinkedSaid = {};
  if (others.user) said.user = firm.user ? "retire" : "keep";
  if (others.contact) said.contact = firm.contact ? "retire" : "keep";
  if (others.operators.length > 0) {
    said.operators = others.operators.map((operator) => {
      const choice = firm.operators[operator.hid] ?? { action: "retire", contactHid: "" };
      if (choice.action !== "hand_over") return { hid: operator.hid, action: choice.action };
      if (choice.contactHid === "") {
        errors[rowOf("operator", operator.hid)] =
          "Choose the person the label is handed over to, or another choice.";
      } else if (choice.contactHid === linked.contact?.hid) {
        errors[rowOf("operator", operator.hid)] =
          "This is the person behind the label now: choose another, or Keep.";
      }
      return { hid: operator.hid, action: "hand_over", contact_hid: choice.contactHid };
    });
  }
  if (Object.keys(errors).length > 0) return { ok: false, errors };
  const body: RetireBody = { row_version: rowVersion };
  if (Object.keys(said).length > 0) body.linked = said;
  return { ok: true, body };
}

/**
 * Where a refusal is said: the message of each field the server names under `linked`,
 * by the row of the confirmation it belongs to, an operator by its place in what was
 * sent; and the rest, which is said above the rows.
 */
export function refusedRows(
  fields: Readonly<Record<string, string>>,
  sent: RetireBody | BringBackBody | null,
): { rows: Record<string, string>; shown: string[] } {
  const rows: Record<string, string> = {};
  const shown: string[] = [];
  const put = (row: string, field: string, message: string) => {
    rows[row] = rows[row] === undefined ? message : `${rows[row]}; ${message}`;
    shown.push(field);
  };
  const operators = sent?.linked?.operators ?? [];
  for (const [field, message] of Object.entries(fields)) {
    const [first, second, third] = field.split(".");
    if (first !== "linked") continue;
    if (second === "user" || second === "contact") put(second, field, message);
    else if (second === "operators" && third !== undefined) {
      const operator = operators[Number(third)];
      if (operator) put(rowOf("operator", operator.hid), field, message);
    }
  }
  return { rows, shown };
}

/**
 * Whether a refusal says that something is linked which the confirmation did not list,
 * so that `linked` is read again: the server names it under `linked` and in `depends_on`.
 */
export function namesUnlisted(
  error: { status: number; dependsOn: readonly { record_type: string; hid: string }[] },
  on: On,
  linked: Linked,
): boolean {
  if (error.status !== 409) return false;
  const others = othersOf(on, linked);
  const listed = new Set([
    ...(others.user ? [others.user.hid] : []),
    ...(others.contact ? [others.contact.hid] : []),
    ...others.operators.map((operator) => operator.hid),
  ]);
  return error.dependsOn.some((record) => !listed.has(record.hid));
}

/** How much names a contact, said beside it so that the choice is an informed one. */
export function contactUses(uses: number): string {
  if (uses === 0) return "named nowhere";
  return `named by ${uses.toLocaleString("en-US")} ${uses === 1 ? "record" : "records"}`;
}

/** How much a label is given to, said beside it. */
export function operatorUses(uses: number): string {
  if (uses === 0) return "given to nothing";
  return `given to ${uses.toLocaleString("en-US")} ${uses === 1 ? "item, group or place" : "items, groups and places"}`;
}

/** The state of an account in a word: retired, disabled, or active (P-292). */
export function userState(user: { record_status?: string | null; disabled: boolean }): string {
  if (user.record_status === "retired") return "Retired";
  return user.disabled ? "Disabled" : "Active";
}

/** What the record a retirement is asked on is called: a label is released. */
export function nameOf(on: On, linked: Linked): string {
  if (on.kind === "user") return linked.user?.username ?? "the account";
  if (on.kind === "contact") return linked.contact?.name ?? "the contact";
  return linked.operators.find((operator) => operator.hid === on.hid)?.label ?? "the label";
}

function listed(parts: readonly string[]): string {
  if (parts.length <= 1) return parts.join("");
  return `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

/**
 * What a page says once a retirement is done: the record, and what became of each
 * linked record, as it was asked.
 */
export function retiredWords(
  on: On,
  linked: Linked,
  choices: Choices,
  admin: boolean,
  handedTo: Readonly<Record<string, string>> = {},
): string {
  const others = othersOf(on, linked);
  const firm = held(on, linked, choices, admin);
  const name = nameOf(on, linked);
  const first = on.kind === "operator" ? `${name} was released` : `${name} was retired`;
  const gone: string[] = [];
  const more: string[] = [];
  const kept: string[] = [];
  if (others.user) {
    (firm.user ? gone : kept).push(`the account ${others.user.username}`);
  }
  if (others.contact) {
    (firm.contact ? gone : kept).push(`the contact ${others.contact.name}`);
  }
  for (const operator of others.operators) {
    const choice = firm.operators[operator.hid];
    if (!choice || choice.action === "retire") more.push(`${operator.label} was released`);
    else if (choice.action === "open") more.push(`${operator.label} was left open`);
    else if (choice.action === "hand_over") {
      const to = handedTo[operator.hid];
      more.push(`${operator.label} was handed over${to ? ` to ${to}` : ""}`);
    } else kept.push(`the label ${operator.label}`);
  }
  // A sentence that begins with a username or a label begins as that is written.
  const sentences = [gone.length > 0 ? `${first}, with ${listed(gone)}` : first];
  if (more.length > 0) sentences.push(listed(more));
  if (kept.length > 0) {
    const stays = `${listed(kept)} ${kept.length === 1 ? "stays" : "stay"}`;
    sentences.push(`${stays.charAt(0).toUpperCase()}${stays.slice(1)}`);
  }
  return sentences.map((sentence) => `${sentence}.`).join(" ");
}

/** What Bring back of a user offers: its retired contact, and that contact's retired labels. */
export interface BringBackOffer {
  /** The contact, where it is retired: the account is brought back with it. */
  contact: LinkedContact | null;
  /** The retired labels of that contact: none need be brought back. */
  operators: readonly LinkedOperator[];
}

export function bringBackOffer(linked: Linked): BringBackOffer {
  return {
    contact: linked.contact?.record_status === "retired" ? linked.contact : null,
    operators: linked.operators.filter((operator) => operator.record_status === "retired"),
  };
}

/** What `POST /users/{hid}/bring-back` takes. */
export type BringBackBody = Schemas["BringBack"];

/**
 * What one Bring back sends: the account, with its contact where that is retired, since
 * an account does not stand on a retired contact, and the labels ticked.
 */
export function bringBackBody(
  linked: Linked,
  ticked: readonly string[],
  rowVersion: number,
): BringBackBody {
  const offer = bringBackOffer(linked);
  const said: Schemas["LinkedBack"] = {};
  if (offer.contact) said.contact = "bring_back";
  const operators = offer.operators.filter((operator) => ticked.includes(operator.hid));
  if (operators.length > 0) {
    said.operators = operators.map((operator) => ({ hid: operator.hid, action: "bring_back" }));
  }
  const body: BringBackBody = { row_version: rowVersion };
  if (Object.keys(said).length > 0) body.linked = said;
  return body;
}

/**
 * The retired account that has a username refused to another (P-296), or null: the
 * server answers a `409` on `username` that says the account is retired, and names it.
 */
export function retiredAccount(
  error: {
    status: number;
    fields: Readonly<Record<string, string>>;
    existing: { record_type: string; hid: string; label: string } | null;
  } | null,
): { hid: string; label: string } | null {
  if (error?.status !== 409 || error.existing?.record_type !== "user") return null;
  const said = error.fields.username;
  if (said === undefined || !/retired/i.test(said)) return null;
  return { hid: error.existing.hid, label: error.existing.label };
}

/** What is said before the linked records a refusal names as not said (P-297). */
export function notSaidLead(count: number): string {
  return count === 1
    ? "Linked, and not listed when this opened. It is listed now: say what becomes of it."
    : `${count.toLocaleString("en-US")} are linked, and were not listed when this opened. They are listed now: say what becomes of each.`;
}
