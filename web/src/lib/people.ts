// People (P-172): every person is a contact, once, with what is true of them whatever
// part they play, and a user and an operator are each a part that a contact plays. The
// name, the email and the two numbers that a user or an operator shows are its contact's,
// read when it is read and changed on the contact, so that a new number entered once
// shows wherever that person is named.
//
// A form gives the person behind a part in one of a few ways: a contact that is a user, a
// contact that is not, a new person whose name, email and numbers make a new contact, or
// nobody. This says what each way sends, and what is wrong with it before it is sent.

import type { Schemas } from "../api/client";
import { all, type FilterNode } from "./filter";
import { contactSearch } from "./operators";
import type { Option } from "./patch";

/** An operator is internal where its contact is a user's, external where it is not. */
export const SCOPES: readonly Option[] = [
  { value: "internal", label: "Internal" },
  { value: "external", label: "External" },
];

/** Internal or External, or blank where nobody is behind the label. */
export function scopeLabel(scope: string | null | undefined): string {
  return SCOPES.find((option) => option.value === scope)?.label ?? "";
}

/** What a scope means, said beside it. */
export function scopeHint(scope: string | null | undefined): string {
  if (scope === "internal") return "the person behind it is a user of hirdir";
  if (scope === "external") return "the person behind it is not a user of hirdir";
  return "";
}

/**
 * The ways a form gives the person behind a part: a contact that is a user, another
 * contact, a new person, or nobody.
 */
export type PersonWay = "user" | "contact" | "new" | "none";

/** What is typed for a new person. */
export interface NewPersonValues {
  name: string;
  email: string;
  organization: string;
  phone: string;
  phone2: string;
}

export const NO_NEW_PERSON: NewPersonValues = {
  name: "",
  email: "",
  organization: "",
  phone: "",
  phone2: "",
};

/** What a form holds of the person: the way, the contact chosen and what was typed. */
export interface PersonChoice {
  way: PersonWay;
  /** The HID of the contact chosen, for the ways that choose one. */
  contactHid: string;
  person: NewPersonValues;
}

export function personChoice(way: PersonWay, contactHid = ""): PersonChoice {
  return { way, contactHid, person: NO_NEW_PERSON };
}

/** A new person as the server takes one: what is blank is left out. */
export type NewPerson = Schemas["NewPerson"];

/**
 * What a choice of the person sends: the contact chosen, or a new person, or neither.
 * What is missing is said of the field it is missing from, before anything is sent.
 */
export type PersonRead =
  | { ok: true; contactHid: string | null; person: NewPerson | null }
  | { ok: false; field: "contact_hid" | "name"; error: string };

export function readPerson(choice: PersonChoice): PersonRead {
  switch (choice.way) {
    case "none":
      return { ok: true, contactHid: null, person: null };
    case "user":
    case "contact":
      return choice.contactHid === ""
        ? {
            ok: false,
            field: "contact_hid",
            error: choice.way === "user" ? "Choose a user." : "Choose a contact.",
          }
        : { ok: true, contactHid: choice.contactHid, person: null };
    case "new": {
      const name = choice.person.name.trim();
      if (name === "") return { ok: false, field: "name", error: "A new person needs a name." };
      const person: NewPerson = { name };
      for (const field of ["email", "organization", "phone", "phone2"] as const) {
        const value = choice.person[field].trim();
        if (value !== "") person[field] = value;
      }
      return { ok: true, contactHid: null, person };
    }
  }
}

/** The fields of a new person, as a form names them. */
export const NEW_PERSON_FIELDS = ["name", "email", "organization", "phone", "phone2"] as const;

/**
 * What the server refused of a new person, by the field of the form it belongs beside.
 * `POST /users` names the fields of the contact it makes `contact.name`, `contact.email`
 * and so on; `POST /contacts` names them plainly. Either is said beside the same input.
 */
export function newPersonErrors(
  fields: Readonly<Record<string, string | undefined>>,
): Record<string, string> {
  const found: Record<string, string> = {};
  for (const field of NEW_PERSON_FIELDS) {
    const message = fields[`contact.${field}`] ?? fields[field];
    if (message) found[field] = message;
  }
  return found;
}

/**
 * The filter of the contacts a search offers: those whose name or email has every word
 * typed, and that are users, or that are not, or either. Blank text is no search.
 */
export function contactFinder(typed: string, users?: boolean): FilterNode | null {
  const search = contactSearch(typed);
  if (search === null) return null;
  return users === undefined ? search : all(search, { field: "is_user", op: "eq", value: users });
}

/**
 * A contact as a search offers it: its name and email address, and the user it is, by
 * its username, or only that it is one where the username is not given.
 */
export function personLabel(contact: {
  name: string;
  email?: string | null;
  is_user?: boolean;
  user?: { username: string } | null;
}): string {
  const named = contact.email ? `${contact.name} (${contact.email})` : contact.name;
  if (contact.user) return `${named}, user ${contact.user.username}`;
  return contact.is_user ? `${named}, a user` : named;
}

/**
 * 0.9.17: a person's account as a picker of people offers it, named as a contact that is
 * a user is offered, `Sam Roe (sroe@example.net), user sroe`, so that a person is named
 * one way in every picker (review 12); an account with no contact by its username.
 */
export function userOptionLabel(user: {
  display_name: string;
  email: string;
  username: string;
}): string {
  if (!user.display_name) return user.username;
  return personLabel({ name: user.display_name, email: user.email, user });
}

/** The two numbers of a person, as one line: the first, then the second. */
export function numbersText(phone: string | null | undefined, phone2: string | null | undefined) {
  return [phone, phone2].filter((one): one is string => Boolean(one)).join(" · ");
}
