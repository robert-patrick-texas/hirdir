// The contacts of a circuit and of a carrier (P-149). A vendor names its account team
// and its support desk once. A circuit has those of its primary carrier, for each role
// by itself, unless it names its own of that role, which then stand in place of the
// carrier's, all of them. The site contacts of a side are those of its location, each
// role resolved for the location as the contacts of a place resolve, with the level each
// came from, unless the circuit names its own for that side and role. The server works
// that out when the circuit is read: nothing is copied, and a change of a contact record
// shows wherever it is named or had from there.

import { type FormEvent, useState } from "react";
import { Link } from "react-router";
import { api, type Schemas } from "../api";
import {
  CARRIER_CONTACT_ROLES,
  type CarrierContacts,
  type CarrierRole,
  type Circuit,
  CONTACT_ROLE_LIST,
  carrierRoleOne,
  carrierSourceText,
  contactSourcePath,
  type NamedContact,
  SIDES,
  type Side,
  type SiteRoleContacts,
  sideLabel,
  sideOf,
  siteSourceText,
  vendorPath,
} from "../lib/circuits";
import { useAction } from "../lib/hooks";
import { choiceLabel, choiceOptions, optionLabel, RECORD_STATUSES } from "../lib/options";
import { fieldErrors } from "../lib/problems";
import { useSorting } from "../lib/useSorting";
import { Dash } from "./CircuitParts";
import { ConfirmButton } from "./ConfirmButton";
import { ContactField } from "./ContactField";
import { SelectField, TextField } from "./Field";
import { Problem } from "./Problem";
import { SortTh } from "./SortTh";

type Choice = Schemas["ChoiceOut"];
type Naming = Schemas["CircuitContactOut"];
type VendorNaming = Schemas["VendorContactOut"];

/** One contact as a table shows it: the contact record as it is now, and its naming. */
function ContactCells({
  contact,
  inherited,
}: {
  contact: Schemas["ContactRef"];
  inherited: boolean;
}) {
  return (
    <>
      <th scope="row">
        <Link
          to={`/contacts/${encodeURIComponent(contact.hid)}`}
          {...(inherited ? { className: "link-inherited" } : {})}
        >
          {contact.name}
        </Link>
        {contact.record_status !== "active" && (
          <span className="badge" data-mark="contact-status">
            {optionLabel(RECORD_STATUSES, contact.record_status)}
          </span>
        )}
      </th>
      <td>{contact.organization || <Dash />}</td>
      <td data-testid="contact-email">
        {contact.email ? <a href={`mailto:${contact.email}`}>{contact.email}</a> : <Dash />}
      </td>
      <td data-testid="contact-phone">{contact.phone || <Dash />}</td>
    </>
  );
}

/** Whole numbers only, for a priority: null for none, or for what is no number. */
function priorityOf(typed: string): number | null {
  const text = typed.trim();
  return /^\d{1,4}$/.test(text) ? Number.parseInt(text, 10) : null;
}

interface CircuitContactsProps {
  circuit: Circuit;
  choices: readonly Choice[] | undefined;
  mayEdit: boolean;
  onChanged: (text: string) => void;
}

/**
 * The contacts of a circuit: the carrier's account team and support desk in force, each
 * with where it came from; the site contacts of each side by role, each with the level it
 * came from; and the contacts it names of its own, to name and to remove.
 */
export function CircuitContacts({ circuit, choices, mayEdit, onChanged }: CircuitContactsProps) {
  return (
    <section aria-labelledby="circuit-contacts" data-testid="circuit-contacts">
      <h2 id="circuit-contacts">Contacts</h2>
      <CarrierInForce circuit={circuit} />
      {SIDES.map(({ value }) => (
        <SiteContacts key={value} circuit={circuit} side={value} choices={choices} />
      ))}
      <OwnNamings circuit={circuit} choices={choices} mayEdit={mayEdit} onChanged={onChanged} />
    </section>
  );
}

interface CarrierRow {
  role: CarrierRole;
  naming: NamedContact;
  source: CarrierContacts["source"];
}

/** The carrier's account team and support desk in force: its own, or its primary carrier's. */
function CarrierInForce({ circuit }: { circuit: Circuit }) {
  const lists: Record<CarrierRole, CarrierContacts> = {
    account_manager: circuit.effective.account_managers ?? {
      value: [],
      source: "none",
      source_hid: null,
    },
    support_contact: circuit.effective.support_contacts ?? {
      value: [],
      source: "none",
      source_hid: null,
    },
  };
  const rows: CarrierRow[] = CARRIER_CONTACT_ROLES.flatMap(({ value }) =>
    lists[value].value.map((naming) => ({ role: value, naming, source: lists[value].source })),
  );
  const sorting = useSorting(rows, {
    role: (row) => carrierRoleOne(row.role),
    contact: (row) => row.naming.contact.name,
    organization: (row) => row.naming.contact.organization,
    email: (row) => row.naming.contact.email,
    phone: (row) => row.naming.contact.phone,
    priority: (row) => row.naming.priority,
    source: (row) => row.source,
  });
  const carrier = circuit.carrier;
  return (
    <section aria-labelledby="carrier-contacts">
      <h3 id="carrier-contacts">The carrier&apos;s account team and support desk</h3>
      <p className="hint">
        For each role by itself: where the circuit names nobody of its own, it has those its primary
        carrier names, shown lighter; where it names anybody, it has its own, all of them, in place
        of the carrier&apos;s. A support desk&apos;s number and address are the telephone and the
        email of its contact record.
      </p>
      <ul className="plain-list" data-testid="carrier-contact-sources">
        {CARRIER_CONTACT_ROLES.map(({ value, label }) => (
          <li key={value} data-role={value} data-source={lists[value].source}>
            <strong>{label}:</strong> {carrierSourceText(lists[value], carrier?.name ?? null)}
          </li>
        ))}
      </ul>
      {rows.length > 0 && (
        <div className="scroll">
          <table data-testid="carrier-contacts-in-force">
            <caption className="visually-hidden">
              The account team and support desk in force for {circuit.name}, each with where it came
              from
            </caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="role">
                  Role
                </SortTh>
                <SortTh sort={sorting} column="contact">
                  Contact
                </SortTh>
                <SortTh sort={sorting} column="organization">
                  Organization
                </SortTh>
                <SortTh sort={sorting} column="email">
                  Email
                </SortTh>
                <SortTh sort={sorting} column="phone">
                  Telephone
                </SortTh>
                <SortTh sort={sorting} column="priority" className="number">
                  Priority
                </SortTh>
                <SortTh sort={sorting} column="source">
                  Source
                </SortTh>
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map(({ role, naming, source }) => {
                const inherited = source === "vendor";
                return (
                  <tr
                    key={`${role} ${naming.hid}`}
                    data-role={role}
                    data-contact={naming.contact.name}
                    data-source={source}
                    className={inherited ? "inherited" : undefined}
                  >
                    <td>{carrierRoleOne(role)}</td>
                    <ContactCells contact={naming.contact} inherited={inherited} />
                    <td className="number">{naming.priority}</td>
                    <td data-testid="contact-source">
                      {inherited ? (
                        <>
                          From the carrier{" "}
                          {carrier ? (
                            <Link className="value-link" to={vendorPath(carrier.hid)}>
                              {carrier.name}
                            </Link>
                          ) : null}
                        </>
                      ) : (
                        "Named here"
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

interface SiteRow {
  entry: SiteRoleContacts;
  naming: NamedContact;
}

/** The site contacts of one side, by role, each with the level it came from. */
function SiteContacts(props: {
  circuit: Circuit;
  side: Side;
  choices: readonly Choice[] | undefined;
}) {
  const { circuit, side, choices } = props;
  const { at } = sideOf(circuit, side);
  const entries = circuit.effective.site_contacts?.[side] ?? [];
  const rows: SiteRow[] = entries.flatMap((entry) =>
    entry.value.map((naming) => ({ entry, naming })),
  );
  const sorting = useSorting(rows, {
    role: (row) => choiceLabel(choices, CONTACT_ROLE_LIST, row.entry.role),
    contact: (row) => row.naming.contact.name,
    organization: (row) => row.naming.contact.organization,
    email: (row) => row.naming.contact.email,
    phone: (row) => row.naming.contact.phone,
    priority: (row) => row.naming.priority,
    source: (row) => siteSourceText(row.entry, at),
  });
  const id = `site-contacts-${side}`;
  return (
    <section aria-labelledby={id} data-testid={id}>
      <h3 id={id}>Site contacts of the {sideLabel(side)}</h3>
      {at ? (
        <p className="hint">
          Those of its location, {at.path}, for each role as the location has them, with the level
          they came from; or, for a role, those the circuit names of its own for this side.
        </p>
      ) : (
        <p className="hint">
          This side has no location: it has only the contacts the circuit names for it.
        </p>
      )}
      {rows.length === 0 ? (
        <p className="muted">No site contact.</p>
      ) : (
        <div className="scroll">
          <table>
            <caption className="visually-hidden">
              The site contacts of the {sideLabel(side)} of {circuit.name}
            </caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="role">
                  Role
                </SortTh>
                <SortTh sort={sorting} column="contact">
                  Contact
                </SortTh>
                <SortTh sort={sorting} column="organization">
                  Organization
                </SortTh>
                <SortTh sort={sorting} column="email">
                  Email
                </SortTh>
                <SortTh sort={sorting} column="phone">
                  Telephone
                </SortTh>
                <SortTh sort={sorting} column="priority" className="number">
                  Priority
                </SortTh>
                <SortTh sort={sorting} column="source">
                  Source
                </SortTh>
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map(({ entry, naming }) => {
                const inherited = entry.source !== "own";
                return (
                  <tr
                    key={`${entry.role} ${naming.hid}`}
                    data-role={entry.role}
                    data-contact={naming.contact.name}
                    data-source={entry.source}
                    className={inherited ? "inherited" : undefined}
                  >
                    <td>{choiceLabel(choices, CONTACT_ROLE_LIST, entry.role)}</td>
                    <ContactCells contact={naming.contact} inherited={inherited} />
                    <td className="number">{naming.priority}</td>
                    <td data-testid="contact-source">
                      {inherited ? (
                        <Link className="value-link" to={contactSourcePath(entry)}>
                          {siteSourceText(entry, at)}
                        </Link>
                      ) : (
                        "Named here"
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** The role of a naming in words: one of the carrier's two, or one of the contact_role list. */
function namingRole(
  naming: Pick<Naming, "side" | "role">,
  choices: readonly Choice[] | undefined,
): string {
  return naming.side === null
    ? carrierRoleOne(naming.role)
    : choiceLabel(choices, CONTACT_ROLE_LIST, naming.role);
}

/** Where a naming stands: with the carrier's, or among the site contacts of a side. */
function namingWhere(side: Side | null): string {
  return side === null ? "The carrier's" : `Site, ${sideLabel(side)}`;
}

/** The contacts the circuit names of its own: those of the carrier's, and of each side. */
function OwnNamings(props: CircuitContactsProps) {
  const { circuit, choices, mayEdit, onChanged } = props;
  const removing = useAction();
  const namings = circuit.contacts ?? [];
  const sorting = useSorting(namings, {
    where: (naming) => namingWhere(naming.side),
    role: (naming) => namingRole(naming, choices),
    contact: (naming) => naming.contact.name,
    priority: (naming) => naming.priority,
  });

  async function remove(naming: Naming) {
    const result = await removing.run(() =>
      api.request("delete", "/api/v1/circuits/{hid}/contacts/{link_hid}", {
        path: { hid: circuit.hid, link_hid: naming.hid },
      }),
    );
    if (result.ok) {
      onChanged(
        `${naming.contact.name} is no longer named as ${namingRole(naming, choices).toLowerCase()} of ${circuit.name}.`,
      );
    }
  }

  return (
    <section aria-labelledby="own-contacts" data-testid="own-contacts">
      <h3 id="own-contacts">Named of its own</h3>
      <p className="hint">
        A contact named here for the carrier&apos;s role stands in place of the carrier&apos;s in
        that role; one named for a side and a role stands in place of what the location gives that
        side in that role.
      </p>
      <Problem error={removing.error} />
      {namings.length === 0 ? (
        <p className="muted">It names nobody of its own.</p>
      ) : (
        <div className="scroll">
          <table>
            <caption className="visually-hidden">
              The contacts {circuit.name} names of its own
            </caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="where">
                  For
                </SortTh>
                <SortTh sort={sorting} column="role">
                  Role
                </SortTh>
                <SortTh sort={sorting} column="contact">
                  Contact
                </SortTh>
                <SortTh sort={sorting} column="priority" className="number">
                  Priority
                </SortTh>
                {mayEdit && <th scope="col">Change</th>}
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((naming) => (
                <tr
                  key={naming.hid}
                  data-contact={naming.contact.name}
                  data-side={naming.side ?? ""}
                  data-role={naming.role}
                >
                  <td>{namingWhere(naming.side)}</td>
                  <td>{namingRole(naming, choices)}</td>
                  <th scope="row">
                    <Link to={`/contacts/${encodeURIComponent(naming.contact.hid)}`}>
                      {naming.contact.name}
                    </Link>
                    {naming.contact.record_status !== "active" && (
                      <span className="badge" data-mark="contact-status">
                        {optionLabel(RECORD_STATUSES, naming.contact.record_status)}
                      </span>
                    )}
                  </th>
                  <td className="number">{naming.priority}</td>
                  {mayEdit && (
                    <td className="row-actions">
                      <Priority
                        key={`${naming.hid} ${naming.row_version}`}
                        what={`${naming.contact.name} as ${namingRole(naming, choices).toLowerCase()}`}
                        priority={naming.priority}
                        save={(priority) =>
                          api.request("patch", "/api/v1/circuits/{hid}/contacts/{link_hid}", {
                            path: { hid: circuit.hid, link_hid: naming.hid },
                            body: { row_version: naming.row_version, priority },
                          })
                        }
                        onChanged={onChanged}
                      />
                      <ConfirmButton
                        label="Remove"
                        title={`Remove ${naming.contact.name} from ${circuit.name}?`}
                        confirmLabel="Remove the naming"
                        onConfirm={() => remove(naming)}
                        disabled={removing.busy}
                      >
                        <p>
                          The contact record itself stays. Should the circuit name nobody left in
                          this role, it has the carrier&apos;s, or the location&apos;s, again.
                        </p>
                      </ConfirmButton>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {mayEdit && <NameCircuitContact circuit={circuit} choices={choices} onChanged={onChanged} />}
    </section>
  );
}

/** Change the priority of one naming: 1 is listed, and asked, first. */
function Priority(props: {
  what: string;
  priority: number;
  save: (priority: number) => Promise<unknown>;
  onChanged: (text: string) => void;
}) {
  const { what, priority, save, onChanged } = props;
  const [typed, setTyped] = useState(String(priority));
  const action = useAction();
  const wanted = priorityOf(typed);
  const refused = fieldErrors(action.error, ["priority"]).shown;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (wanted === null) return;
    const result = await action.run(() => save(wanted));
    if (result.ok) onChanged(`The priority of ${what} is now ${wanted}.`);
  }

  return (
    <form onSubmit={submit} className="cell-form" noValidate>
      <TextField
        label={`Priority of ${what}`}
        name="priority"
        value={typed}
        onChange={setTyped}
        inputMode="numeric"
        maxLength={4}
        autoComplete="off"
        disabled={action.busy}
        error={refused.priority ?? action.error?.message}
      />
      <button type="submit" disabled={action.busy || wanted === null || wanted === priority}>
        Set priority
      </button>
    </form>
  );
}

/**
 * Name a contact for the circuit: with no side, one of the carrier's two roles, in place
 * of the carrier's; with a side, a role of the contact_role list, in place of what the
 * location gives that side.
 */
function NameCircuitContact(props: {
  circuit: Circuit;
  choices: readonly Choice[] | undefined;
  onChanged: (text: string) => void;
}) {
  const { circuit, choices, onChanged } = props;
  const [contact, setContact] = useState("");
  const [side, setSide] = useState<"" | Side>("");
  const [role, setRole] = useState("");
  const [priority, setPriority] = useState("");
  const action = useAction();
  const known = ["contact_hid", "side", "role", "priority"];
  const refused = fieldErrors(action.error, known).shown;
  const order = priorityOf(priority);
  const badPriority = priority.trim() !== "" && order === null;
  const ready = contact !== "" && role !== "" && !badPriority;
  const roles =
    side === ""
      ? CARRIER_CONTACT_ROLES.map((one) => ({
          value: one.value,
          label: one.one.charAt(0).toUpperCase() + one.one.slice(1),
        }))
      : choiceOptions(choices, CONTACT_ROLE_LIST);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready) return;
    const body: Schemas["CircuitContactAdd"] = {
      contact_hid: contact,
      role,
      side: side === "" ? null : side,
      ...(order === null ? {} : { priority: order }),
    };
    const result = await action.run(() =>
      api.request("post", "/api/v1/circuits/{hid}/contacts", { path: { hid: circuit.hid }, body }),
    );
    if (!result.ok) return;
    onChanged(
      `${result.value.contact.name} is now named as ${namingRole(result.value, choices).toLowerCase()} of ${circuit.name}.`,
    );
    setContact("");
    setPriority("");
  }

  return (
    <section aria-labelledby="name-circuit-contact" className="panel">
      <h3 id="name-circuit-contact">Name a contact</h3>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={known} />
        <div className="fields">
          <ContactField
            label="Contact"
            name="contact_hid"
            value={contact}
            onChange={setContact}
            blank="No contact chosen"
            disabled={action.busy}
            error={refused.contact_hid}
            hint="A contact record, made under Contacts. A retired one is not offered."
          />
          <SelectField
            label="For"
            name="side"
            value={side}
            onChange={(next) => {
              setSide(next === "a" || next === "z" ? next : "");
              setRole("");
            }}
            disabled={action.busy}
            error={refused.side}
          >
            <option value="">The carrier: its account team or support desk</option>
            {SIDES.map((one) => (
              <option key={one.value} value={one.value}>
                A site contact of the {one.label}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="Role"
            name="role"
            value={role}
            onChange={setRole}
            required
            disabled={action.busy}
            error={refused.role}
          >
            <option value="">Choose a role</option>
            {roles.map((one) => (
              <option key={one.value} value={one.value}>
                {one.label}
              </option>
            ))}
          </SelectField>
          <TextField
            label="Priority"
            name="priority"
            value={priority}
            onChange={setPriority}
            inputMode="numeric"
            maxLength={4}
            autoComplete="off"
            disabled={action.busy}
            error={refused.priority ?? (badPriority ? "A whole number." : undefined)}
            hint="1 is listed first. Left blank, after the last one of the side and role."
          />
        </div>
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || !ready}>
            Name the contact
          </button>
        </p>
      </form>
    </section>
  );
}

// --- the contacts of a vendor ----------------------------------------------------------

interface VendorContactsProps {
  vendor: { hid: string; name: string; contacts: readonly VendorNaming[] };
  mayEdit: boolean;
  onChanged: (text: string) => void;
}

/**
 * The account team and the support desk of a vendor, named once, on the vendor: each
 * circuit of the carrier that names nobody of its own in a role has these (P-149).
 */
export function VendorContacts({ vendor, mayEdit, onChanged }: VendorContactsProps) {
  const removing = useAction();
  const sorting = useSorting(vendor.contacts, {
    role: (naming) => carrierRoleOne(naming.role),
    contact: (naming) => naming.contact.name,
    organization: (naming) => naming.contact.organization,
    email: (naming) => naming.contact.email,
    phone: (naming) => naming.contact.phone,
    priority: (naming) => naming.priority,
  });

  async function remove(naming: VendorNaming) {
    const result = await removing.run(() =>
      api.request("delete", "/api/v1/vendors/{hid}/contacts/{link_hid}", {
        path: { hid: vendor.hid, link_hid: naming.hid },
      }),
    );
    if (result.ok) {
      onChanged(
        `${naming.contact.name} is no longer named as ${carrierRoleOne(naming.role)} of ${vendor.name}.`,
      );
    }
  }

  return (
    <section aria-labelledby="vendor-contacts" data-testid="vendor-contacts">
      <h2 id="vendor-contacts">Account team and support desk</h2>
      <p className="hint">
        Named once, here: each circuit of this carrier has them, for each role by itself, unless it
        names its own. Nothing is copied, so a new telephone number of a contact shows on every
        circuit at once.
      </p>
      <Problem error={removing.error} />
      {vendor.contacts.length === 0 ? (
        <p className="muted">Nobody is named.</p>
      ) : (
        <div className="scroll">
          <table>
            <caption className="visually-hidden">The contacts {vendor.name} names</caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="role">
                  Role
                </SortTh>
                <SortTh sort={sorting} column="contact">
                  Contact
                </SortTh>
                <SortTh sort={sorting} column="organization">
                  Organization
                </SortTh>
                <SortTh sort={sorting} column="email">
                  Email
                </SortTh>
                <SortTh sort={sorting} column="phone">
                  Telephone
                </SortTh>
                <SortTh sort={sorting} column="priority" className="number">
                  Priority
                </SortTh>
                {mayEdit && <th scope="col">Change</th>}
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((naming) => (
                <tr key={naming.hid} data-role={naming.role} data-contact={naming.contact.name}>
                  <td>{carrierRoleOne(naming.role)}</td>
                  <ContactCells contact={naming.contact} inherited={false} />
                  <td className="number">{naming.priority}</td>
                  {mayEdit && (
                    <td className="row-actions">
                      <Priority
                        key={`${naming.hid} ${naming.row_version}`}
                        what={`${naming.contact.name} as ${carrierRoleOne(naming.role)}`}
                        priority={naming.priority}
                        save={(priority) =>
                          api.request("patch", "/api/v1/vendors/{hid}/contacts/{link_hid}", {
                            path: { hid: vendor.hid, link_hid: naming.hid },
                            body: { row_version: naming.row_version, priority },
                          })
                        }
                        onChanged={onChanged}
                      />
                      <ConfirmButton
                        label="Remove"
                        title={`Remove ${naming.contact.name} as ${carrierRoleOne(naming.role)} of ${vendor.name}?`}
                        confirmLabel="Remove the naming"
                        onConfirm={() => remove(naming)}
                        disabled={removing.busy}
                      >
                        <p>
                          The contact record itself stays. A circuit of this carrier that names
                          nobody of its own in this role no longer has this contact.
                        </p>
                      </ConfirmButton>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {mayEdit && <NameVendorContact vendor={vendor} onChanged={onChanged} />}
    </section>
  );
}

/** Name a contact record for a vendor: its account team or its support desk. */
function NameVendorContact(props: {
  vendor: { hid: string; name: string };
  onChanged: (text: string) => void;
}) {
  const { vendor, onChanged } = props;
  const [contact, setContact] = useState("");
  const [role, setRole] = useState<CarrierRole | "">("");
  const [priority, setPriority] = useState("");
  const action = useAction();
  const known = ["contact_hid", "role", "priority"];
  const refused = fieldErrors(action.error, known).shown;
  const order = priorityOf(priority);
  const badPriority = priority.trim() !== "" && order === null;
  const ready = contact !== "" && role !== "" && !badPriority;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready) return;
    const body: Schemas["VendorContactAdd"] = {
      contact_hid: contact,
      role,
      ...(order === null ? {} : { priority: order }),
    };
    const result = await action.run(() =>
      api.request("post", "/api/v1/vendors/{hid}/contacts", { path: { hid: vendor.hid }, body }),
    );
    if (!result.ok) return;
    onChanged(
      `${result.value.contact.name} is now named as ${carrierRoleOne(role)} of ${vendor.name}.`,
    );
    setContact("");
    setPriority("");
  }

  return (
    <section aria-labelledby="name-vendor-contact" className="panel">
      <h3 id="name-vendor-contact">Name a contact</h3>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={known} />
        <div className="fields">
          <ContactField
            label="Contact"
            name="contact_hid"
            value={contact}
            onChange={setContact}
            blank="No contact chosen"
            disabled={action.busy}
            error={refused.contact_hid}
            hint="A contact record, made under Contacts. A retired one is not offered."
          />
          <SelectField
            label="Role"
            name="role"
            value={role}
            onChange={(next) =>
              setRole(CARRIER_CONTACT_ROLES.find((one) => one.value === next)?.value ?? "")
            }
            required
            disabled={action.busy}
            error={refused.role}
          >
            <option value="">Choose a role</option>
            {CARRIER_CONTACT_ROLES.map((one) => (
              <option key={one.value} value={one.value}>
                {one.one.charAt(0).toUpperCase() + one.one.slice(1)}
              </option>
            ))}
          </SelectField>
          <TextField
            label="Priority"
            name="priority"
            value={priority}
            onChange={setPriority}
            inputMode="numeric"
            maxLength={4}
            autoComplete="off"
            disabled={action.busy}
            error={refused.priority ?? (badPriority ? "A whole number." : undefined)}
            hint="1 is listed first. Left blank, after the last one of the role."
          />
        </div>
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || !ready}>
            Name the contact
          </button>
        </p>
      </form>
    </section>
  );
}
