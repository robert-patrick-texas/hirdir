// 0.9.13: who is a user, a contact and an operator, and a new person in one step
// (P-280 to P-284). A new user is made with its contact, its operator, its role and its
// groups by one Create; a user's groups are ticked on its page; and an operator is made
// of a person in one press. This holds what the forms work out from what is typed.

import type { Schemas } from "../api/client";
import { type Mark, safeColour } from "./operators";
import { NEW_PERSON_FIELDS, newPersonErrors, type PersonChoice, readPerson } from "./people";
import { roleLabel } from "./roles";

/**
 * What a group grants, said beside its box: "grants Inventory", or that it grants nothing.
 * It names the box in the New user form, beside the field Role: it does not say "role".
 */
export function groupGrants(roles: readonly string[]): string {
  if (roles.length === 0) return "grants nothing";
  return `grants ${roles.map((role) => roleLabel(role)).join(", ")}`;
}

/**
 * The label of a new operator, and what the form last filled it with. The label follows
 * the username as it is typed while it is blank or still what the form filled in, and
 * keeps what was typed over it (P-283), as the New operator form does with the username
 * of the person chosen (P-284).
 */
export interface FollowedLabel {
  label: string;
  filled: string;
}

export function followedLabel(username: string): FollowedLabel {
  return { label: username, filled: username };
}

/** The username was typed: the label follows it, unless another label was typed over it. */
export function followUsername(was: FollowedLabel, username: string): FollowedLabel {
  return was.label === "" || was.label === was.filled ? followedLabel(username) : was;
}

/** The label was typed: it is the person's from now on, until it is blank again. */
export function typeLabel(was: FollowedLabel, label: string): FollowedLabel {
  return { label, filled: was.filled };
}

/**
 * The label Make an operator gives the operator of a person (P-284): the username where
 * the person is a user, else the contact's name.
 */
export function operatorLabelOf(person: {
  name: string;
  user?: { username: string } | null;
}): string {
  return person.user ? person.user.username : person.name;
}

/**
 * Whether a refusal of a new operator is of its label or its colour, which the form of
 * Make an operator then opens with, rather than a refusal of the whole.
 */
export function refusedField(fields: Readonly<Record<string, string>>): boolean {
  return Object.keys(fields).some((field) => /(^|\.)(label|colour)$/.test(field));
}

/** What the New user form holds (P-282, P-283). */
export interface NewUserForm {
  username: string;
  service: boolean;
  /** Also a contact: the person, a new contact or one there is. */
  alsoContact: boolean;
  person: PersonChoice;
  /** Also an operator: made with the user, of its contact. */
  alsoOperator: boolean;
  label: string;
  /**
   * The colour as chosen, or null where none was: then the server gives the next that no
   * operator has. Chosen blank, the operator has no colour.
   */
  colour: string | null;
  role: string;
  groupHids: readonly string[];
  notes: string;
  accessCode: string;
}

/** What `POST /users` takes since 0.9.13 ("### People" of docs/interfaces.md). */
export type NewUserBody = Schemas["UserCreate"];

/**
 * What one Create sends: the user, with its contact and its operator where their boxes
 * are ticked, its role, its groups and its notes. A service account is no person and has
 * neither box, nor an access code. What is missing is said of its field before anything
 * is sent. A label left blank is the username, which the server gives; a colour not
 * chosen is the next that no operator has, which it gives too.
 */
export function newUserBody(
  form: NewUserForm,
): { ok: true; body: NewUserBody } | { ok: false; field: string; error: string } {
  const body: NewUserBody = { username: form.username.trim(), is_service_account: form.service };
  if (!form.service && form.alsoContact) {
    const read = readPerson(form.person);
    if (!read.ok) return { ok: false, field: read.field, error: read.error };
    if (read.contactHid !== null) body.contact_hid = read.contactHid;
    if (read.person !== null) body.contact = read.person;
    if (form.alsoOperator) {
      const operator: Schemas["NewOperator"] = {};
      if (form.label.trim() !== "") operator.label = form.label.trim();
      if (form.colour !== null) operator.colour = form.colour.trim() || null;
      body.operator = operator;
    }
  }
  if (form.role !== "") body.role = form.role;
  if (form.groupHids.length > 0) body.group_hids = [...form.groupHids];
  if (form.notes.trim() !== "") body.notes = form.notes.trim();
  if (!form.service && form.accessCode !== "") body.access_code = form.accessCode;
  return { ok: true, body };
}

/**
 * The mark of an operator a user or a contact names (P-280): its label in its colour, a
 * link to its page, and released where it is retired. Who is behind it is the person
 * whose page or row it is on, and is not said again.
 */
export function briefMark(operator: Schemas["OperatorBrief"]): Mark {
  return {
    hid: operator.hid,
    label: operator.label,
    colour: safeColour(operator.colour),
    person: "",
    open: false,
    released: operator.record_status === "retired",
  };
}

/**
 * Whether a person stands behind an operator that is not retired: where not, the page
 * offers Make an operator (P-284), and the lists count them among those behind none.
 */
export function behindOperator(operators: readonly Schemas["OperatorBrief"][]): boolean {
  return operators.some((operator) => operator.record_status !== "retired");
}

/** The gaps a list of users is narrowed to (P-280): no contact, or no operator. */
export type UsersGap = "" | "no-contact" | "no-operator";

/** What a gap asks `GET /users` for, and what the address of the page holds of it. */
export const USERS_GAPS: readonly {
  value: UsersGap;
  label: string;
  param: "contact" | "operator" | null;
}[] = [
  { value: "", label: "Every user", param: null },
  { value: "no-contact", label: "Users with no contact", param: "contact" },
  { value: "no-operator", label: "Users with no operator", param: "operator" },
];

/** The gap a list of users is narrowed to, as the address of the page says it. */
export function usersGapOf(params: URLSearchParams): UsersGap {
  if (params.get("contact") === "none") return "no-contact";
  if (params.get("operator") === "none") return "no-operator";
  return "";
}

/** What `GET /users` is asked, for a gap. */
export function usersGapQuery(gap: UsersGap): { contact?: "none"; operator?: "none" } {
  if (gap === "no-contact") return { contact: "none" };
  if (gap === "no-operator") return { operator: "none" };
  return {};
}

/** The address of the list of users: what is searched for, the gap, and the page. */
export function usersAddress(q: string, gap: UsersGap, offset: number): URLSearchParams {
  const wanted = new URLSearchParams();
  if (q) wanted.set("q", q);
  for (const [name, value] of Object.entries(usersGapQuery(gap))) wanted.set(name, value);
  if (offset > 0) wanted.set("offset", String(offset));
  return wanted;
}

/** The query of an address as it is written after the path: blank where it has none. */
export function queryOf(params: URLSearchParams): string {
  const text = params.toString();
  return text ? `?${text}` : "";
}

/**
 * The gaps of the list of contacts (P-280), each as the filter of the grid that a link
 * starts it with: every contact, those that are no user, those behind no operator. The
 * filter is always given, blank for the whole, so that the grid does not take up the
 * one it last had.
 */
export const CONTACTS_GAPS: readonly { label: string; filter: string }[] = [
  { label: "Every contact", filter: "" },
  { label: "Contacts that are no user", filter: "is_user:eq:false" },
  { label: "Contacts behind no operator", filter: "is_operator:eq:false" },
];

/** The address of the list of contacts started with a filter. */
export function contactsAddress(filter: string): string {
  return `/contacts?${new URLSearchParams({ filter }).toString()}`;
}

/** The fields of the user itself that a refusal names, each said beside its input. */
const USER_FIELDS = [
  "username",
  "is_service_account",
  "contact_hid",
  "role",
  "notes",
  "access_code",
] as const;

/**
 * The fields of `POST /users` that the New user form shows a refusal beside, as the
 * server names them: those of the contact under `contact.`, of the operator under
 * `operator.`, and the groups.
 */
export const NEW_USER_FIELDS: readonly string[] = [
  ...USER_FIELDS,
  ...NEW_PERSON_FIELDS,
  ...NEW_PERSON_FIELDS.map((field) => `contact.${field}`),
  "operator",
  "operator.label",
  "operator.colour",
  "operator.description",
  "group_hids",
];

/**
 * What the server refused of a new user, by the input of the form it is said beside:
 * the person's fields by their own names, the operator's `label` and `colour`, the rest
 * of the operator at its box, and `group_hids`, or one of them, at the groups.
 */
export function newUserErrors(fields: Readonly<Record<string, string>>): Record<string, string> {
  const found: Record<string, string> = { ...newPersonErrors(fields) };
  const put = (field: string, message: string) => {
    found[field] = found[field] === undefined ? message : `${found[field]}; ${message}`;
  };
  for (const [field, message] of Object.entries(fields)) {
    if (field === "operator.label") put("label", message);
    else if (field === "operator.colour") put("colour", message);
    else if (field === "operator" || field.startsWith("operator.")) put("operator", message);
    else if (field === "group_hids" || field.startsWith("group_hids.")) put("group_hids", message);
    else if ((USER_FIELDS as readonly string[]).includes(field)) put(field, message);
  }
  return found;
}
