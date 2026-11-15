// What the pages of agreements and of contracts share: their second row of navigation,
// the fields of their forms, and how a value that a contract has from its agreement is
// shown. What is inherited is lighter and marked "Inherited", with the agreement it came
// from; what is the contract's own where the agreement has one too is marked "Overrides",
// with what it overrides.

import type { ReactNode } from "react";
import { Link, NavLink } from "react-router";
import {
  type Agreement,
  agreementHint,
  agreementPath,
  CONTRACT_STATUSES,
  type Contract,
  type InForce,
  LAPSED_NOTE,
  nextTermText,
  RENEWAL_PENDING,
  RENEWAL_PENDING_NOTE,
} from "../lib/contracts";
import { optionLabel, RECORD_STATUSES, SETTABLE_STATUSES } from "../lib/options";
import type { FieldSpec, Option } from "../lib/patch";

/** The second row of navigation on the pages of contracts and of agreements. */
export function ContractsNav() {
  return (
    <nav className="sub" aria-label="Contracts">
      <ul>
        <li>
          <NavLink to="/contracts" end>
            Contracts
          </NavLink>
        </li>
        <li>
          <NavLink to="/agreements">Support agreements</NavLink>
        </li>
        <li>
          <NavLink to="/contracts/renewals">Renewals</NavLink>
        </li>
        <li>
          <NavLink to="/reports/coverage">Gaps and expiries: the coverage report</NavLink>
        </li>
      </ul>
    </nav>
  );
}

export function Dash() {
  return <span className="muted">—</span>;
}

interface StatusMarksProps {
  record: Pick<Contract, "status" | "lapsed" | "next_term" | "record_status"> &
    Partial<Pick<Contract, "ends_with_term">>;
  /** Say the status also where it is Active: beside the name of a page. */
  always?: boolean;
}

/**
 * How a contract or an agreement stands, as marks beside its name: its status where
 * that is not Active, that it has lapsed, that its renewal is pending, that a term is
 * still to begin, and its record status where that is not active.
 */
export function StatusMarks({ record, always = false }: StatusMarksProps) {
  const pending = record.status === RENEWAL_PENDING;
  // A contract that has ended by choice says so in its own mark, in place of Expired.
  const byChoice = record.ends_with_term === true && record.status === "expired";
  return (
    <>
      {!pending && !byChoice && (always || record.status !== "active") && (
        <span className="badge badge-plain" data-mark="status">
          {optionLabel(CONTRACT_STATUSES, record.status)}
        </span>
      )}
      {record.ends_with_term === true && <EndsWithTermMark contract={record} />}
      {pending && (
        <span className="badge" data-mark="renewal-pending" title={RENEWAL_PENDING_NOTE}>
          Renewal pending
        </span>
      )}
      {record.lapsed && (
        <span className="badge" data-mark="lapsed" title={LAPSED_NOTE}>
          Lapsed
        </span>
      )}
      {record.next_term && (
        <span
          className="badge badge-plain"
          data-mark="next-term"
          title={nextTermText(record.next_term)}
        >
          Renewed from {record.next_term.starts_on}
        </span>
      )}
      {record.record_status !== "active" && (
        <span className="badge" data-mark="record-status">
          {optionLabel(RECORD_STATUSES, record.record_status)}
        </span>
      )}
    </>
  );
}

/** What is said of a contract that is not to be renewed, while its term runs. */
export const ENDS_WITH_TERM_NOTE =
  "Not to be renewed: it ends with this term. It covers to the end of its present term, is not lapsed after it, and is expired from the next day. A renewal takes the mark off.";

/** What is said of a contract that was not to be renewed, once its term has ended. */
export const ENDED_BY_CHOICE_NOTE =
  "Expired by choice: it was marked to end with its term, and that term has ended. It covers nothing now, and is retired by hand once nobody needs to see it.";

/**
 * The mark of a contract that is not to be renewed: ending with its term while that
 * runs, and expired by choice once it has ended (P-129). Nothing for any other.
 */
export function EndsWithTermMark({
  contract,
}: {
  contract: Pick<Contract, "status"> & Partial<Pick<Contract, "ends_with_term">>;
}) {
  if (contract.ends_with_term !== true) return null;
  if (contract.status === "expired") {
    return (
      <span className="badge" data-mark="ended-by-choice" title={ENDED_BY_CHOICE_NOTE}>
        Expired by choice
      </span>
    );
  }
  return (
    <span className="badge badge-plain" data-mark="ends-with-term" title={ENDS_WITH_TERM_NOTE}>
      Ends with this term
    </span>
  );
}

/** Free text of several lines, such as whom to call for support, with its lines kept. */
export function Lines({ text }: { text: string | null | undefined }) {
  return text ? <span className="lines">{text}</span> : <Dash />;
}

/**
 * Where support is reached online, as a link when it is an address of the web: it opens
 * in a tab of its own, and tells the other site nothing of this one.
 */
export function SupportLink({ url }: { url: string | null | undefined }) {
  if (!url) return <Dash />;
  if (!/^https?:\/\//i.test(url)) return <>{url}</>;
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" data-testid="support-url">
      {url}
    </a>
  );
}

interface InForceValueProps {
  value: InForce;
  /** The agreement the contract is in: where an inherited value came from. */
  agreement: { hid: string; name: string } | null;
  /** The value as the page shows it, when it is more than its text: a link, several lines. */
  children?: ReactNode;
}

/**
 * One value of a contract as it is in force, with how it stands: its own, inherited from
 * its agreement, or its own in place of what the agreement has.
 */
export function InForceValue({ value, agreement, children }: InForceValueProps) {
  const shown = children ?? value.text;
  if (value.standing === "none") {
    return (
      <span className="muted" data-standing="none">
        —
      </span>
    );
  }
  if (value.standing === "inherited") {
    return (
      <span className="inherited" data-standing="inherited">
        {shown} · <span className="badge badge-plain mark">Inherited</span> from{" "}
        {agreement ? <Link to={agreementPath(agreement.hid)}>{agreement.name}</Link> : "above"}
      </span>
    );
  }
  if (value.standing === "override") {
    return (
      <span data-standing="override" data-same={value.same ? "true" : "false"}>
        {shown}
        <span className="muted"> · Set here </span>
        <span className="badge mark">Overrides</span>{" "}
        <span className="inherited">{value.overridden}</span>
        {agreement && (
          <span className="muted">
            {" "}
            of <Link to={agreementPath(agreement.hid)}>{agreement.name}</Link>
          </span>
        )}
        {value.same && (
          <span className="muted" data-testid="override-same">
            , which is the same: set here, it stays as it is when the agreement&apos;s changes
          </span>
        )}
      </span>
    );
  }
  return (
    <span data-standing="own">
      {shown}
      {agreement && <span className="muted"> · Set here</span>}
    </span>
  );
}

/** What the forms of an agreement and of a contract choose from. */
export interface ContractLists {
  vendors: readonly Option[];
  tags: readonly string[];
}

function shared(lists: ContractLists, tags: readonly string[]): FieldSpec[] {
  return [
    {
      name: "tags",
      label: "Tags",
      kind: "set",
      options: [...new Set([...lists.tags, ...tags])].map((label) => ({
        value: label,
        label,
      })),
    },
  ];
}

/** The fields of an agreement that a form sets. */
export function agreementSpecs(
  lists: ContractLists,
  current: Agreement | null = null,
): FieldSpec[] {
  return [
    {
      name: "name",
      label: "Name",
      kind: "text",
      required: true,
      maxLength: 200,
      hint: "What the agreement is called, as in Cisco Enterprise Agreement.",
    },
    {
      name: "number",
      label: "Number",
      kind: "text",
      maxLength: 200,
      hint: "The agreement's own number, where it has one.",
    },
    {
      name: "vendor_hid",
      label: "Vendor",
      kind: "choice",
      required: true,
      options: lists.vendors,
      ...(current ? {} : { blank: "Choose a vendor" }),
      hint: "The vendor the agreement is with. Its contracts are with the same vendor.",
    },
    {
      name: "status",
      label: "Status",
      kind: "choice",
      options: CONTRACT_STATUSES,
      hint: "What you say of it. It gates nothing: a contract covers by its own status.",
    },
    {
      name: "reseller_hid",
      label: "Reseller",
      kind: "choice",
      options: lists.vendors,
      blank: "None",
      heading: "What its contracts have from it, where they say nothing of their own",
      hint: "The vendor it was bought through.",
    },
    { name: "starts_on", label: "Starts on", kind: "date" },
    {
      name: "ends_on",
      label: "Ends on",
      kind: "date",
      hint: "A contract with no dates of its own ends when the agreement does.",
    },
    { name: "support_level", label: "Support level", kind: "text", maxLength: 200 },
    {
      name: "account_manager",
      label: "Account manager",
      kind: "longtext",
      maxLength: 10000,
      hint: "Whom to ask about it: a name with a telephone number or an address.",
    },
    {
      name: "support_contact",
      label: "Support contact",
      kind: "longtext",
      maxLength: 10000,
      hint: "Whom to call for support.",
    },
    {
      name: "support_url",
      label: "Support URL",
      kind: "text",
      maxLength: 2000,
      hint: "Where support is reached online: begins with https:// or http://",
    },
    {
      name: "purchase_reference",
      label: "Purchase reference",
      kind: "text",
      maxLength: 200,
      heading: "Its own",
    },
    {
      name: "annual_cost",
      label: "Annual cost",
      kind: "decimal",
      places: 2,
      hint: "The agreement's own total. It is added to nothing.",
    },
    { name: "notes", label: "Notes", kind: "longtext", maxLength: 10000 },
    { name: "record_status", label: "Record status", kind: "choice", options: SETTABLE_STATUSES },
    ...shared(lists, current?.tags ?? []),
  ];
}

/**
 * The fields of a contract that a form sets. The agreement it is in is not among them:
 * a contract is put into one, and taken out, by an action of its own. For a contract in
 * an agreement, each field it may have from the agreement says what a blank brings.
 */
export function contractSpecs(lists: ContractLists, current: Contract | null = null): FieldSpec[] {
  const from = (field: Parameters<typeof agreementHint>[1], otherwise?: string) => {
    const hint = agreementHint(current, field) ?? otherwise;
    return hint === undefined ? {} : { hint };
  };
  return [
    {
      name: "number",
      label: "Number",
      kind: "text",
      required: true,
      maxLength: 200,
      hint: "Unique with its vendor. A renewal gives it its new number: see Renew.",
    },
    {
      name: "vendor_hid",
      label: "Vendor",
      kind: "choice",
      options: lists.vendors,
      ...(current ? {} : { blank: "The vendor of the agreement it is put into" }),
      hint: "The manufacturer or the provider.",
    },
    {
      name: "status",
      label: "Status",
      kind: "choice",
      options: CONTRACT_STATUSES,
      hint: "What you say of it: the clock never changes it. An active contract covers within its period. Renewal pending is for a term that has ended while the renewal is in procurement: the contract covers on, and support goes through the account manager.",
    },
    {
      name: "reseller_hid",
      label: "Reseller",
      kind: "choice",
      options: lists.vendors,
      blank: current?.agreement ? "None of its own" : "None",
      heading: current?.agreement
        ? `What it may have from ${current.agreement.name}`
        : "Period, and whom to ask",
      ...from("reseller_hid", "The vendor it was bought through."),
    },
    { name: "starts_on", label: "Starts on", kind: "date", ...from("starts_on") },
    {
      name: "ends_on",
      label: "Ends on",
      kind: "date",
      ...from("ends_on", "Blank is until further notice."),
    },
    {
      name: "support_level",
      label: "Support level",
      kind: "text",
      maxLength: 200,
      ...from("support_level"),
    },
    {
      name: "account_manager",
      label: "Account manager",
      kind: "longtext",
      maxLength: 10000,
      ...from("account_manager", "Whom to ask about the contract."),
    },
    {
      name: "support_contact",
      label: "Support contact",
      kind: "longtext",
      maxLength: 10000,
      ...from("support_contact", "Whom to call for support."),
    },
    {
      name: "support_url",
      label: "Support URL",
      kind: "text",
      maxLength: 2000,
      ...from("support_url", "Where support is reached online: begins with https:// or http://"),
    },
    {
      name: "ends_with_term",
      label: "Not to be renewed: ends with this term",
      kind: "boolean",
      hint: current?.agreement
        ? `It covers to the end of its present term, is not lapsed after it, and is expired from the next day. A renewal takes the mark off. A contract that shares the period of ${current.agreement.name} is let go when the agreement is renewed, by choosing End with this term for it there.`
        : "It covers to the end of its present term, is not lapsed after it, and is expired from the next day, as when a site closes. A renewal takes the mark off.",
    },
    {
      name: "purchase_reference",
      label: "Purchase reference",
      kind: "text",
      maxLength: 200,
      heading: "Its own",
      hint: "The request or the tracking number the present term was bought under.",
    },
    {
      name: "annual_cost",
      label: "Annual cost",
      kind: "decimal",
      places: 2,
      hint: "The contract's own total. It is added to nothing.",
    },
    { name: "notes", label: "Notes", kind: "longtext", maxLength: 10000 },
    { name: "record_status", label: "Record status", kind: "choice", options: SETTABLE_STATUSES },
    ...shared(lists, current?.tags ?? []),
  ];
}
