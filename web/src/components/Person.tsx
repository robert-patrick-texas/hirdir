// 0.9.3: the person behind a user or an operator, who is a contact (P-172). One form
// part chooses that person, a contact that is a user, another contact, a new person or
// nobody; another changes the contact's email and numbers where the user or the
// operator is shown, which changes them wherever that person is named.

import { useState } from "react";
import { api, type Schemas } from "../api";
import { useLoad } from "../lib/hooks";
import type { FieldSpec, Option } from "../lib/patch";
import { NO_NEW_PERSON, type PersonChoice, type PersonWay } from "../lib/people";
import { ContactField } from "./ContactField";
import { RadioGroupField, TextField } from "./Field";
import { Problem } from "./Problem";
import { EditForm } from "./RecordForm";

type Contact = Schemas["ContactOut"];

/** What each way is called, where a form does not call it otherwise. */
const WAY_LABELS: Readonly<Record<PersonWay, string>> = {
  user: "A user",
  contact: "Another contact",
  new: "A new person",
  none: "Nobody",
};

interface PersonChooserProps {
  /** The name of the group of choices, as the form calls the person. */
  legend: string;
  /** A name for the inputs, unique on the page. */
  name: string;
  /** The ways offered, in order. */
  ways: readonly PersonWay[];
  /** What a way is called here, where not as WAY_LABELS says. */
  wayLabels?: Partial<Record<PersonWay, string>>;
  choice: PersonChoice;
  onChange: (choice: PersonChoice) => void;
  /**
   * What is wrong, by field: `contact_hid` for the contact chosen, and `name`, `email`,
   * `organization`, `phone` and `phone2` for a new person, as the server names them.
   */
  errors?: Readonly<Record<string, string | undefined>>;
  /** Ask a new person's organization too. */
  organization?: boolean;
  hint?: string;
  /** Contacts the form already knows what to call, such as one it has just made. */
  known?: readonly Option[];
  disabled?: boolean;
}

/**
 * The person behind a part: chosen from the contacts that are users, from the others,
 * or typed as a new person whose name, email and numbers make a new contact, or nobody.
 * The way is chosen first, and only its fields are shown.
 */
export function PersonChooser(props: PersonChooserProps) {
  const { legend, name, ways, wayLabels = {}, choice, onChange, errors = {} } = props;
  const { organization = false, hint, known = [], disabled } = props;
  const label = (way: PersonWay) => wayLabels[way] ?? WAY_LABELS[way];
  const typed = (field: keyof PersonChoice["person"]) => (value: string) =>
    onChange({ ...choice, person: { ...choice.person, [field]: value } });

  return (
    <div className="person-chooser" data-testid={`person-${name}`}>
      <RadioGroupField
        label={legend}
        name={`${name}-way`}
        options={ways.map((way) => ({ value: way, label: label(way) }))}
        value={choice.way}
        // Another way lets go of what was chosen or typed for the one before.
        onChange={(way) =>
          onChange({ way: way as PersonWay, contactHid: "", person: NO_NEW_PERSON })
        }
        disabled={disabled}
        {...(hint ? { hint } : {})}
      />
      {(choice.way === "user" || choice.way === "contact") && (
        <div className="fields">
          <ContactField
            key={choice.way}
            label={choice.way === "user" ? "User" : "Contact"}
            name={`${name}-${choice.way}`}
            users={choice.way === "user"}
            value={choice.contactHid}
            onChange={(hid) => onChange({ ...choice, contactHid: hid })}
            blank={choice.way === "user" ? "No user chosen" : "No contact chosen"}
            hint={
              choice.way === "user"
                ? "A contact that is a user, who signs in to hirdir."
                : "A contact that is no user of hirdir."
            }
            known={known}
            error={errors.contact_hid}
            disabled={disabled}
          />
        </div>
      )}
      {choice.way === "new" && (
        <div className="fields" data-testid={`new-person-${name}`}>
          <TextField
            label="Name"
            name={`${name}-name`}
            value={choice.person.name}
            onChange={typed("name")}
            required
            maxLength={200}
            autoComplete="off"
            hint="A new contact is made with it."
            error={errors.name}
            disabled={disabled}
          />
          <TextField
            label="Email"
            name={`${name}-email`}
            value={choice.person.email}
            onChange={typed("email")}
            maxLength={254}
            autoComplete="off"
            hint="Belongs to one contact only."
            error={errors.email}
            disabled={disabled}
          />
          {organization && (
            <TextField
              label="Organization"
              name={`${name}-organization`}
              value={choice.person.organization}
              onChange={typed("organization")}
              maxLength={200}
              autoComplete="off"
              error={errors.organization}
              disabled={disabled}
            />
          )}
          <TextField
            label="Phone"
            name={`${name}-phone`}
            value={choice.person.phone}
            onChange={typed("phone")}
            maxLength={50}
            autoComplete="off"
            error={errors.phone}
            disabled={disabled}
          />
          <TextField
            label="Second phone"
            name={`${name}-phone2`}
            value={choice.person.phone2}
            onChange={typed("phone2")}
            maxLength={50}
            autoComplete="off"
            error={errors.phone2}
            disabled={disabled}
          />
        </div>
      )}
    </div>
  );
}

/** The fields of a contact that the page of a user or an operator changes on it. */
export type PersonField = "name" | "email" | "phone" | "phone2";

const PERSON_SPECS: Readonly<Record<PersonField, FieldSpec>> = {
  name: {
    name: "name",
    label: "Name",
    kind: "text",
    required: true,
    maxLength: 200,
    hint: "A person, or a shared mailbox",
  },
  email: {
    name: "email",
    label: "Email",
    kind: "text",
    maxLength: 254,
    hint: "Belongs to one contact only. A file finds a contact by it.",
  },
  phone: { name: "phone", label: "Phone", kind: "text", maxLength: 50 },
  phone2: { name: "phone2", label: "Second phone", kind: "text", maxLength: 50 },
};

interface ContactChangesProps {
  /** The contact to change. */
  hid: string;
  /** The fields asked for, in order. */
  fields: readonly PersonField[];
  /** What the change is called, as the button says it. */
  submitLabel: string;
  /** The contact was changed: the page reads what shows it again. */
  onSaved: () => void;
}

/**
 * Change the name, email or numbers of a contact from the page of a part it plays, a
 * user or an operator. It is a change of the contact, by `PATCH /contacts/{hid}`, with
 * the version the contact is read at here: the contact is read first.
 */
export function ContactChanges({ hid, fields, submitLabel, onSaved }: ContactChangesProps) {
  const [turn, setTurn] = useState(0);
  const contact = useLoad(`person ${hid} ${turn}`, (signal) =>
    api.request("get", "/api/v1/contacts/{hid}", { path: { hid }, signal }),
  );
  const record = contact.data;
  if (contact.error) return <Problem error={contact.error} />;
  if (!record) {
    return (
      <p role="status" className="muted loading-late">
        Loading…
      </p>
    );
  }
  if (record.record_status === "retired") {
    return (
      <p className="hint" data-testid="person-retired">
        The contact is retired. It is brought back on its own page, and then changed here.
      </p>
    );
  }
  return (
    <EditForm<Contact, Schemas["ContactPatch"]>
      key={`${record.hid} ${record.row_version}`}
      specs={fields.map((field) => PERSON_SPECS[field])}
      record={record}
      save={(body) =>
        api.request("patch", "/api/v1/contacts/{hid}", { path: { hid: record.hid }, body })
      }
      onSaved={() => {
        setTurn((count) => count + 1);
        onSaved();
      }}
      onReload={() => setTurn((count) => count + 1)}
      submitLabel={submitLabel}
    />
  );
}
