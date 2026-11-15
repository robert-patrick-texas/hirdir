// The contacts of an agreement and of a contract: the account managers and the support
// contacts, each a contact record named in a role with a priority (D-170, D-183). For
// each role by itself, a contract that names nobody of its own has those its agreement
// names, with that source; one that names anybody has its own, all of them, in place of
// the agreement's. The server resolves that when the record is read: nothing is copied,
// and a change of a contact record shows wherever it is named or had from there. The
// free text of the account manager and the support contact stays beside these.

import { type FormEvent, useState } from "react";
import { Link } from "react-router";
import { api, type Schemas } from "../api";
import { agreementPath } from "../lib/contracts";
import { useAction } from "../lib/hooks";
import { optionLabel, RECORD_STATUSES } from "../lib/options";
import { fieldErrors } from "../lib/problems";
import { useSorting } from "../lib/useSorting";
import { ConfirmButton } from "./ConfirmButton";
import { ContactField } from "./ContactField";
import { Dash } from "./ContractParts";
import { SelectField, TextField } from "./Field";
import { Problem } from "./Problem";
import { SortTh } from "./SortTh";

type Naming = Schemas["ContractContactOut"];
type InForce = Schemas["EffectiveContacts"];
type Role = Naming["role"];

/** The two roles, in the order they are shown. */
export const CONTACT_ROLES: ReadonlyArray<{ value: Role; label: string; one: string }> = [
  { value: "account_manager", label: "Account managers", one: "account manager" },
  { value: "support_contact", label: "Support contacts", one: "support contact" },
];

function roleOne(role: Role): string {
  return CONTACT_ROLES.find((one) => one.value === role)?.one ?? role;
}

interface ContractContactsProps {
  of: "agreement" | "contract";
  record: {
    hid: string;
    record_status: string;
    effective: { account_managers: InForce; support_contacts: InForce };
  };
  /** What the record is called: the name of an agreement, the number of a contract. */
  name: string;
  /** For a contract: the agreement it is in, which it has the contacts of a role from. */
  agreement?: { hid: string; name: string } | null;
  mayEdit: boolean;
  onChanged: (text: string) => void;
}

/** One contact in force, with its role and where it came from. */
interface Row {
  role: Role;
  naming: Naming;
  source: InForce["source"];
}

/** The account managers and support contacts in force, own or from the agreement. */
export function ContractContacts(props: ContractContactsProps) {
  const { of, record, name, agreement = null, mayEdit, onChanged } = props;
  const removing = useAction();
  const lists: Record<Role, InForce> = {
    account_manager: record.effective.account_managers,
    support_contact: record.effective.support_contacts,
  };
  const rows: Row[] = CONTACT_ROLES.flatMap(({ value }) =>
    lists[value].value.map((naming) => ({ role: value, naming, source: lists[value].source })),
  );
  // By role and priority at first, as the server lists them, until a header is pressed.
  const sorting = useSorting(rows, {
    role: (row) => roleOne(row.role),
    contact: (row) => row.naming.contact.name,
    organization: (row) => row.naming.contact.organization,
    email: (row) => row.naming.contact.email,
    phone: (row) => row.naming.contact.phone,
    priority: (row) => row.naming.priority,
    source: (row) => row.source,
  });
  const open = mayEdit && record.record_status !== "retired";

  async function remove(naming: Naming) {
    const who = naming.contact.name;
    const result = await removing.run(() =>
      of === "agreement"
        ? api.request("delete", "/api/v1/agreements/{hid}/contacts/{link_hid}", {
            path: { hid: record.hid, link_hid: naming.hid },
          })
        : api.request("delete", "/api/v1/contracts/{hid}/contacts/{link_hid}", {
            path: { hid: record.hid, link_hid: naming.hid },
          }),
    );
    if (result.ok) onChanged(`${who} is no longer named as ${roleOne(naming.role)} of ${name}.`);
  }

  return (
    <section aria-labelledby="contract-contacts" data-testid="contract-contacts">
      <h2 id="contract-contacts">Account managers and support contacts</h2>
      <p className="hint">
        {of === "contract"
          ? agreement
            ? `For each role by itself: where ${name} names nobody of its own, it has those ${agreement.name} names, shown lighter; where it names anybody, it has its own, all of them, in place of the agreement's. Each is a contact record as it is now. The free text of the account manager and the support contact above stays beside these.`
            : `The contact records ${name} names in each role, as they are now. Put into an agreement, it has the agreement's in a role where it names nobody of its own. The free text above stays beside these.`
          : `The contact records ${name} names in each role, as they are now. A contract in it that names nobody of its own in a role has these. The free text above stays beside these.`}
      </p>
      <ul className="plain-list" data-testid="contact-sources">
        {CONTACT_ROLES.map(({ value, label }) => (
          <li key={value} data-role={value} data-source={lists[value].source}>
            <strong>{label}:</strong> <SourceText list={lists[value]} agreement={agreement} />
          </li>
        ))}
      </ul>
      <Problem error={removing.error} />
      {rows.length > 0 && (
        <div className="scroll">
          <table data-testid="contacts-in-force">
            <caption className="visually-hidden">
              The account managers and support contacts in force for {name}, each with where it came
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
                {open && <th scope="col">Change</th>}
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map(({ role, naming, source }) => {
                const inherited = source === "agreement";
                const contact = naming.contact;
                return (
                  <tr
                    key={naming.hid}
                    data-role={role}
                    data-contact={contact.name}
                    data-source={source}
                    className={inherited ? "inherited" : undefined}
                  >
                    <td>{roleOne(role)}</td>
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
                      {contact.email ? (
                        <a href={`mailto:${contact.email}`}>{contact.email}</a>
                      ) : (
                        <Dash />
                      )}
                    </td>
                    <td data-testid="contact-phone">{contact.phone || <Dash />}</td>
                    <td className="number" data-testid="priority">
                      {naming.priority}
                    </td>
                    <td data-testid="contact-source">
                      {inherited ? (
                        <>
                          Inherited from{" "}
                          {agreement ? (
                            <Link to={agreementPath(agreement.hid)}>{agreement.name}</Link>
                          ) : (
                            "its agreement"
                          )}
                        </>
                      ) : (
                        "Named here"
                      )}
                    </td>
                    {open && (
                      <td className="row-actions">
                        {inherited ? (
                          <span className="muted">Changed on the agreement</span>
                        ) : (
                          <>
                            <Priority
                              key={`${naming.hid} ${naming.row_version}`}
                              of={of}
                              recordHid={record.hid}
                              naming={naming}
                              what={`${contact.name} as ${roleOne(role)}`}
                              onChanged={onChanged}
                            />
                            <ConfirmButton
                              label="Remove"
                              title={`Remove ${contact.name} as ${roleOne(role)} of ${name}?`}
                              confirmLabel="Remove the naming"
                              onConfirm={() => remove(naming)}
                              disabled={removing.busy}
                            >
                              <p>
                                The contact record itself stays.
                                {of === "contract" && agreement
                                  ? ` Should ${name} name nobody left in this role, it has those of ${agreement.name} again.`
                                  : ""}
                              </p>
                            </ConfirmButton>
                          </>
                        )}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {open && <NameContact of={of} recordHid={record.hid} name={name} onChanged={onChanged} />}
    </section>
  );
}

/** Where the contacts of a role came from, as a few words. */
function SourceText({
  list,
  agreement,
}: {
  list: InForce;
  agreement: { hid: string; name: string } | null;
}) {
  const count = list.value.length;
  if (list.source === "none" || count === 0) return <span className="muted">nobody is named</span>;
  if (list.source === "agreement") {
    return (
      <span className="inherited">
        {count} from{" "}
        {agreement ? (
          <Link to={agreementPath(agreement.hid)}>{agreement.name}</Link>
        ) : (
          "its agreement"
        )}
        , which it names nobody in place of
      </span>
    );
  }
  return <span>{count} named here</span>;
}

/** Change the priority of one naming: 1 is listed, and asked, first. */
function Priority(props: {
  of: "agreement" | "contract";
  recordHid: string;
  naming: Naming;
  what: string;
  onChanged: (text: string) => void;
}) {
  const { of, recordHid, naming, what, onChanged } = props;
  const [typed, setTyped] = useState(String(naming.priority));
  const action = useAction();
  const wanted = /^\d{1,4}$/.test(typed.trim()) ? Number.parseInt(typed.trim(), 10) : null;
  const refused = fieldErrors(action.error, ["priority"]).shown;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (wanted === null) return;
    const body = { row_version: naming.row_version, priority: wanted };
    const path = { hid: recordHid, link_hid: naming.hid };
    const result = await action.run(() =>
      of === "agreement"
        ? api.request("patch", "/api/v1/agreements/{hid}/contacts/{link_hid}", { path, body })
        : api.request("patch", "/api/v1/contracts/{hid}/contacts/{link_hid}", { path, body }),
    );
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
      <button type="submit" disabled={action.busy || wanted === null || wanted === naming.priority}>
        Set priority
      </button>
    </form>
  );
}

/** Name a contact record for the agreement or the contract, in a role, with a priority. */
function NameContact(props: {
  of: "agreement" | "contract";
  recordHid: string;
  name: string;
  onChanged: (text: string) => void;
}) {
  const { of, recordHid, name, onChanged } = props;
  const [contact, setContact] = useState("");
  const [role, setRole] = useState<Role | "">("");
  const [priority, setPriority] = useState("");
  const action = useAction();
  const known = ["contact_hid", "role", "priority"];
  const refused = fieldErrors(action.error, known).shown;
  const typed = priority.trim();
  const order = /^\d{1,4}$/.test(typed) ? Number.parseInt(typed, 10) : null;
  const ready = contact !== "" && role !== "" && (typed === "" || order !== null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready) return;
    const body: Schemas["ContractContactAdd"] = {
      contact_hid: contact,
      role,
      ...(order === null ? {} : { priority: order }),
    };
    const path = { hid: recordHid };
    const result = await action.run(() =>
      of === "agreement"
        ? api.request("post", "/api/v1/agreements/{hid}/contacts", { path, body })
        : api.request("post", "/api/v1/contracts/{hid}/contacts", { path, body }),
    );
    if (!result.ok) return;
    onChanged(`${result.value.contact.name} is now named as ${roleOne(role)} of ${name}.`);
    setContact("");
    setPriority("");
  }

  return (
    <section aria-labelledby="name-contact" className="panel">
      <h3 id="name-contact">Name a contact</h3>
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
              setRole(CONTACT_ROLES.find((one) => one.value === next)?.value ?? "")
            }
            required
            disabled={action.busy}
            error={refused.role}
          >
            <option value="">Choose a role</option>
            {CONTACT_ROLES.map((one) => (
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
            error={
              refused.priority ?? (typed !== "" && order === null ? "A whole number." : undefined)
            }
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
