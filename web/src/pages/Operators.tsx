import { type FormEvent, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { BoxTree } from "../components/BoxTree";
import { ColourShown, useNextColour } from "../components/ColourPicker";
import { ConfirmButton } from "../components/ConfirmButton";
import { FormFields } from "../components/FormFields";
import { GapLinks } from "../components/GapLinks";
import type { GridColumn } from "../components/grid/columns";
import { DataGrid } from "../components/grid/DataGrid";
import { OperatorMark } from "../components/Operator";
import { ContactChanges, PersonChooser } from "../components/Person";
import { Notice, Problem } from "../components/Problem";
import { EditForm } from "../components/RecordForm";
import { Time } from "../components/Time";
import { assignmentColumns, totalCount } from "../lib/assignments";
import { formatTime, plural } from "../lib/format";
import { queryBody, queryParams } from "../lib/gridQuery";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { EVERY } from "../lib/lists";
import { isGapShown, labelFor, OPERATOR_GAPS, operatorsAddress } from "../lib/operatorPage";
import {
  markOf,
  type Operator,
  operatedGroupsPath,
  operatedItemsPath,
  operatorPath,
  safeColour,
} from "../lib/operators";
import { optionLabel, RECORD_STATUSES, SETTABLE_STATUSES } from "../lib/options";
import {
  buildCreate,
  type FieldSpec,
  type FormValue,
  type FormValues,
  formOf,
  type Option,
} from "../lib/patch";
import {
  numbersText,
  type PersonChoice,
  personChoice,
  personLabel,
  readPerson,
  SCOPES,
  scopeHint,
  scopeLabel,
} from "../lib/people";
import { kindPath } from "../lib/preview";
import { allows } from "../lib/roles";
import { oneLink, page } from "../lib/valueLinks";

/**
 * The columns of the list. 0.9.13: the user behind each operator, by its username, a link
 * to the user's page for an Admin, whose page it is, and plain words for others (P-280).
 */
function operatorColumns(admin: boolean): GridColumn<Operator>[] {
  return [
    {
      id: "label",
      header: "Label",
      kind: "text",
      value: (operator) => operator.label,
      chip: (operator) => ({
        colour: safeColour(operator.colour),
        path: operatorPath(operator.hid),
      }),
      width: 180,
    },
    {
      // The person behind the label: the list is filtered and sorted by that name.
      id: "contact.name",
      header: "Person behind it",
      kind: "text",
      column: "contact",
      value: (operator) => operator.contact?.name,
      links: (operator) => oneLink(operator.contact?.name, page("contact", operator.contact?.hid)),
      width: 240,
    },
    {
      // The server neither filters nor sorts by it: Show narrows the list to the gaps.
      id: "user",
      header: "User",
      kind: "text",
      field: null,
      sortField: null,
      column: null,
      value: (operator) => operator.user?.username ?? "no user",
      links: (operator) =>
        oneLink(operator.user?.username, kindPath("user", operator.user?.hid, admin)),
      width: 150,
    },
    ...COLUMNS,
  ];
}

const COLUMNS: GridColumn<Operator>[] = [
  // 0.9.3: internal where the person behind it is a user, external where not, and the
  // person's email and numbers, which are the contact's (P-172).
  {
    id: "scope",
    header: "Internal or external",
    kind: "choice",
    value: (operator) => scopeLabel(operator.scope),
    choices: SCOPES,
    width: 170,
  },
  {
    id: "contact.email",
    header: "Email",
    kind: "text",
    column: "contact_email",
    value: (operator) => operator.contact?.email,
    width: 240,
  },
  {
    id: "contact.phone",
    header: "Phone",
    kind: "text",
    column: "contact_phone",
    value: (operator) => operator.contact?.phone,
    width: 150,
  },
  {
    id: "contact.phone2",
    header: "Second phone",
    kind: "text",
    column: "contact_phone2",
    value: (operator) => operator.contact?.phone2,
    width: 150,
  },
  {
    id: "is_open",
    header: "Open",
    kind: "boolean",
    column: null,
    value: (operator) => (operator.is_open ? "Open" : ""),
    choices: [
      { value: "true", label: "Open: nobody is behind it" },
      { value: "false", label: "Somebody is behind it" },
    ],
    width: 110,
  },
  {
    id: "description",
    header: "Description",
    kind: "text",
    value: (operator) => operator.description,
    width: 300,
  },
  {
    // How many items, groups and places are given it as their own: counted by the server.
    id: "uses",
    header: "Given to",
    kind: "integer",
    field: null,
    sortField: "uses",
    column: null,
    value: (operator) => String(operator.uses),
    numeric: true,
    width: 110,
  },
  {
    id: "colour",
    header: "Colour",
    kind: "text",
    value: (operator) => operator.colour,
    mono: true,
    hide: true,
  },
  {
    id: "record_status",
    header: "Record status",
    kind: "choice",
    value: (operator) =>
      operator.record_status === "retired"
        ? "Released"
        : optionLabel(RECORD_STATUSES, operator.record_status),
    choices: RECORD_STATUSES,
    width: 140,
  },
  {
    id: "updated_at",
    header: "Changed",
    kind: "timestamp",
    value: (operator) => formatTime(operator.updated_at),
    hide: true,
  },
  {
    id: "hid",
    header: "HID",
    kind: "reference",
    value: (operator) => operator.hid,
    mono: true,
    hide: true,
  },
];

/**
 * The fields of an operator that a form sets. 0.9.3: the person behind it is chosen
 * beside them, a user, another contact or a new person (P-172).
 */
function operatorSpecs(): FieldSpec[] {
  return [
    {
      name: "label",
      label: "Label",
      kind: "text",
      required: true,
      maxLength: 40,
      hint: "Short, and of your choosing: initials, a surname, a code such as Op2. It is what lists and reports show.",
    },
    // 0.9.13: chosen from the grid, by the slider or typed, beside the label as it will
    // show (P-285).
    {
      name: "colour",
      label: "Colour",
      kind: "colour",
      hint: "Press a colour, move the slider, or type one in the form #1f6feb. A dot in this colour stands beside the label. Blank is no colour.",
      sample: (values) => (typeof values.label === "string" ? values.label : ""),
      sampleAs: "operator",
    },
    { name: "record_status", label: "Record status", kind: "choice", options: SETTABLE_STATUSES },
    { name: "description", label: "Description", kind: "longtext", maxLength: 10000 },
  ];
}

/**
 * Operators: the labels that stand for the members of the team who look after things.
 * Items, groups and places are given a label, never a person, so that the person behind
 * a label is changed here, once.
 */
export function Operators() {
  useTitle("Operators");
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const startFilter = params.get("filter");
  const [adding, setAdding] = useState(false);
  const admin = allows(user.role, "admin");
  const columns = useMemo(() => operatorColumns(admin), [admin]);

  return (
    <>
      <h1>Operators</h1>
      <p>
        An operator is a short label that stands for the member of the team who looks after what it
        is on. Lists and reports show the label, in its colour; the person behind it is named here.
        A label with nobody behind it is an open assignment. A label that is released stands for
        nothing: it is shown here when Include archived is on.
      </p>
      {adding && (
        <NewOperator
          onCreated={(operator) => navigate(operatorPath(operator.hid))}
          onCancel={() => setAdding(false)}
        />
      )}
      {/* 0.9.13: the gaps, each one press away and an address of its own, as on the lists
          of users and of contacts (P-280). */}
      <GapLinks
        label="Show operators"
        links={OPERATOR_GAPS.map((gap) => ({
          text: gap.label,
          to: operatorsAddress(gap.filter),
          current: isGapShown(gap.filter, startFilter),
        }))}
      />
      <DataGrid<Operator>
        key={startFilter ?? ""}
        id="operators"
        noun={["operator", "operators"]}
        entity="operators"
        columns={columns}
        load={(request, signal) =>
          api.request("get", "/api/v1/operators", { query: queryParams(request), signal })
        }
        rowId={(operator) => operator.hid}
        rowLink={(operator) => operatorPath(operator.hid)}
        dimmed={(operator) => operator.record_status !== "active"}
        shortFilter="is_open:eq:true label:prefix:Op"
        quickFields={["label"]}
        startFilter={startFilter}
        switches={{ archived: "Include archived", drafts: "Include drafts" }}
      >
        {allows(user.role, "inventory") && !adding && (
          <button type="button" className="primary" onClick={() => setAdding(true)}>
            New operator
          </button>
        )}
      </DataGrid>
    </>
  );
}

/** Operators → one label: who is behind it, what it is on, and the ways to change that. */
export function OperatorDetail() {
  const { hid = "" } = useParams();
  const { user } = useAuth();
  const mayEdit = allows(user.role, "inventory");
  const operator = useLoad(`operator ${hid}`, (signal) =>
    api.request("get", "/api/v1/operators/{hid}", { path: { hid }, signal }),
  );
  const [done, setDone] = useState("");
  const record = operator.data;
  const mark = markOf(record);
  useTitle(record ? record.label : "Operator");
  const specs = useMemo(() => operatorSpecs(), []);

  function changed(text: string) {
    setDone(text);
    operator.reload();
  }

  return (
    <>
      <p className="crumbs">
        <Link to="/operators">Operators</Link>
      </p>
      <h1>{mark ? <OperatorMark mark={mark} testId="operator-heading" /> : "Operator"}</h1>
      <Problem error={operator.error} />
      <Notice text={done} />
      {operator.loading && !record && <p role="status">Loading…</p>}
      {record && (
        <>
          <dl className="facts" data-testid="operator-facts">
            <dt>Label</dt>
            <dd>{record.label}</dd>
            <dt>Person behind it</dt>
            <dd data-testid="operator-person" data-open={record.is_open ? "true" : "false"}>
              {record.contact ? (
                <>
                  <Link to={`/contacts/${encodeURIComponent(record.contact.hid)}`}>
                    {record.contact.name}
                  </Link>
                  {record.contact.record_status === "retired" && (
                    <span className="badge">Retired</span>
                  )}
                </>
              ) : (
                <span className="muted">Nobody</span>
              )}
              {record.is_open && record.record_status !== "retired" && (
                <span className="muted">
                  {" "}
                  · an open assignment: what the label is on still shows it, marked as open
                </span>
              )}
            </dd>
            <dt>Internal or external</dt>
            <dd data-testid="operator-scope" data-scope={record.scope ?? ""}>
              {record.scope ? (
                <>
                  {scopeLabel(record.scope)}
                  <span className="muted"> · {scopeHint(record.scope)}</span>
                </>
              ) : (
                // Nobody is behind the label, or only a person who is retired: it is open.
                <span className="muted">
                  {record.contact
                    ? "Neither: the person behind it is retired, and the label is open"
                    : "Neither: nobody is behind it"}
                </span>
              )}
            </dd>
            {record.contact && (
              <>
                <dt>Email</dt>
                <dd data-testid="operator-email">
                  {record.contact.email || <span className="muted">—</span>}
                </dd>
                <dt>Numbers</dt>
                <dd data-testid="operator-numbers">
                  {numbersText(record.contact.phone, record.contact.phone2) || (
                    <span className="muted">—</span>
                  )}
                </dd>
              </>
            )}
            {record.user && (
              <>
                <dt>User</dt>
                <dd data-testid="operator-user">
                  {allows(user.role, "admin") ? (
                    <Link to={`/admin/users/${encodeURIComponent(record.user.hid)}`}>
                      {record.user.username}
                    </Link>
                  ) : (
                    <span className="mono">{record.user.username}</span>
                  )}
                  <span className="muted"> · the person behind it signs in as this user</span>
                </dd>
              </>
            )}
            <dt>Description</dt>
            <dd>{record.description || <span className="muted">—</span>}</dd>
            <dt>Colour</dt>
            <dd>
              <ColourShown colour={record.colour} testId="operator-colour" />
            </dd>
            <dt>Record status</dt>
            <dd>
              {record.record_status === "retired"
                ? "Released"
                : optionLabel(RECORD_STATUSES, record.record_status)}
            </dd>
            <dt>Changed</dt>
            <dd>
              <Time at={record.updated_at} />
            </dd>
            <dt>HID</dt>
            <dd className="mono">{record.hid}</dd>
          </dl>
          <On operator={record} />
          {/* 0.9.13: Details first, above the person's email and numbers (P-284). */}
          {mayEdit && record.record_status !== "retired" && (
            <section aria-labelledby="details">
              <h2 id="details">Details</h2>
              <EditForm<Operator, Schemas["OperatorPatch"]>
                key={`${record.hid} ${record.row_version}`}
                specs={specs}
                record={record}
                save={(body) =>
                  api.request("patch", "/api/v1/operators/{hid}", {
                    path: { hid: record.hid },
                    body,
                  })
                }
                onSaved={() => changed("The operator was saved.")}
                onReload={operator.reload}
              />
            </section>
          )}
          {mayEdit && record.record_status !== "retired" && record.contact && (
            <section aria-labelledby="person-details">
              <h2 id="person-details">The person&apos;s email and numbers</h2>
              <p className="hint">
                Those of {record.contact.name}&apos;s contact: changed here, they are changed on the
                contact, and so wherever that person is named.
              </p>
              <ContactChanges
                hid={record.contact.hid}
                fields={["email", "phone", "phone2"]}
                submitLabel="Save on the contact"
                onSaved={() => changed(`The contact ${record.contact?.name ?? ""} was saved.`)}
              />
            </section>
          )}
          {mayEdit && record.record_status !== "retired" && (
            <HandOver
              key={`hand ${record.hid} ${record.row_version}`}
              operator={record}
              onChanged={changed}
              onReload={operator.reload}
            />
          )}
          {mayEdit && (
            <Release
              key={`status ${record.hid} ${record.row_version}`}
              operator={record}
              onChanged={changed}
              onReload={operator.reload}
            />
          )}
        </>
      )}
    </>
  );
}

/**
 * What the label is on: the items it is in force for, counted by the server, and the
 * groups and places that are given it as their own, each a link.
 */
function On({ operator }: { operator: Operator }) {
  const on = useLoad(`operator-on ${operator.hid} ${operator.row_version}`, async (signal) => {
    const given = { filter: `operator_hid:eq:${operator.hid}`, limit: EVERY };
    const [items, groups, regions, sites, locations] = await Promise.all([
      api.request("post", "/api/v1/items/query", {
        body: queryBody({
          filter: { field: "effective.operator_hid", op: "eq", value: operator.hid },
          sort: [],
          limit: 1,
          offset: 0,
          include_archived: false,
          include_drafts: false,
        }),
        signal,
      }),
      api.request("get", "/api/v1/device-groups", { query: { ...given, limit: 1 }, signal }),
      api.request("get", "/api/v1/regions", { query: given, signal }),
      api.request("get", "/api/v1/sites", { query: given, signal }),
      api.request("get", "/api/v1/locations", { query: given, signal }),
    ]);
    return {
      items: items.total,
      groups: groups.total,
      places: [
        ...regions.items.map((place) => ({ level: "region", hid: place.hid, path: place.path })),
        ...sites.items.map((place) => ({ level: "site", hid: place.hid, path: place.path })),
        ...locations.items.map((place) => ({
          level: "location",
          hid: place.hid,
          path: place.path,
        })),
      ],
    };
  });
  const data = on.data;
  return (
    <section aria-labelledby="on">
      <h2 id="on">What it is on</h2>
      <Problem error={on.error} />
      {on.loading && !data && (
        <p role="status" className="muted loading-late">
          Counting…
        </p>
      )}
      {data && (
        <>
          <p data-testid="operator-on">
            In force for{" "}
            <Link to={operatedItemsPath(operator.hid)}>{plural(data.items, "item")}</Link>: those
            given it, and those that have it from the item they are in, from their group or from
            where they are. Given to{" "}
            <Link to={operatedGroupsPath(operator.hid)}>{plural(data.groups, "device group")}</Link>{" "}
            and {plural(data.places.length, "place")} as their own.
          </p>
          {/* 0.9.4: what it is on, drawn as a tree of boxes (P-177). */}
          <OnTree operator={operator} />
        </>
      )}
    </section>
  );
}

/**
 * What the label is on, as a tree of boxes (P-177): the operator at the top, then its
 * places, its groups and its own items, each box with its counts, every count a link to
 * exactly those items, and the exceptions within it marked.
 */
function OnTree({ operator }: { operator: Operator }) {
  const found = useLoad(`operator-tree ${operator.hid} ${operator.row_version}`, (signal) =>
    api.request("get", "/api/v1/operators/{hid}/assignments", {
      path: { hid: operator.hid },
      signal,
    }),
  );
  const data = found.data;
  const mark = markOf(operator);
  return (
    <div data-testid="operator-tree">
      <Problem error={found.error} />
      {found.loading && !data && (
        <p role="status" className="muted loading-late">
          Drawing what it is on…
        </p>
      )}
      {data && (
        <>
          <BoxTree
            label={`What ${operator.label} is on`}
            root={{
              key: operator.hid,
              kind: "operator",
              title: mark ? <OperatorMark mark={mark} withPerson /> : operator.label,
              counts: [totalCount(data)],
            }}
            columns={assignmentColumns(data)}
          />
          <p className="hint">
            Each count leads to its items in the grid, the minor items among them. A box with
            something marked ! holds items beneath it that have another operator, their own or from
            a group that ranks first. A place or a group with more beneath it than twenty shows the
            first twenty, and leads to the rest.
          </p>
        </>
      )}
    </div>
  );
}

interface ChangeProps {
  operator: Operator;
  onChanged: (text: string) => void;
  onReload: () => void;
}

/** The fields of a new person, as the server names them in a refusal. */
const PERSON_FIELDS = ["contact_hid", "name", "email", "phone", "phone2"];

/**
 * The contact a choice of the person comes to: the one chosen, or a new one made from
 * what was typed, or none. A contact made is handed to `onMade` before anything else is
 * sent, so that a form which is refused afterwards holds it, and does not make it twice.
 */
async function contactOf(
  choice: PersonChoice,
  onMade: (made: Option) => void,
): Promise<string | null> {
  const read = readPerson(choice);
  if (!read.ok) return null;
  if (read.person === null) return read.contactHid;
  const contact = await api.request("post", "/api/v1/contacts", {
    body: { ...read.person, record_status: "active" },
  });
  onMade({ value: contact.hid, label: personLabel(contact) });
  return contact.hid;
}

interface NewOperatorProps {
  onCreated: (operator: Operator) => void;
  onCancel: () => void;
}

/** The username asked for of a user chosen, and the label the form had filled in before. */
interface Naming {
  hid: string;
  username: Promise<string | null>;
  filled: string;
}

/**
 * A new operator: its label, colour, status and description, and the person behind it,
 * a user, another contact, a new person whose name, email and numbers make a new
 * contact, or nobody for now, an open assignment.
 */
function NewOperator({ onCreated, onCancel }: NewOperatorProps) {
  const specs = useMemo(() => operatorSpecs(), []);
  const [values, setValues] = useState<FormValues>(() => ({
    ...formOf(specs),
    record_status: "active",
  }));
  const [person, setPerson] = useState<PersonChoice>(() => personChoice("none"));
  const [made, setMade] = useState<Option | null>(null);
  const [found, setFound] = useState<Record<string, string>>({});
  const action = useAction();
  const names = [...specs.map((spec) => spec.name), ...PERSON_FIELDS];
  const errors: Record<string, string> = { ...action.error?.fields, ...found };
  // 0.9.13: the colour starts at the next that no operator has, until one is chosen; a
  // colour chosen blank is no colour (P-285).
  const nextColour = useNextColour();
  const [colourChosen, setColourChosen] = useState(false);
  const shown =
    colourChosen || nextColour.next === null ? values : { ...values, colour: nextColour.next };
  // 0.9.13: a user chosen as the person behind it names the label with its username,
  // while the label is blank or still what the form filled in (P-284).
  const naming = useRef<Naming | null>(null);
  const filled = useRef("");
  // Create waits for what has not come yet, the username and the colour, and is pressed once.
  const [waiting, setWaiting] = useState(false);
  const busy = action.busy || waiting;

  function change(name: string, value: FormValue) {
    if (name === "colour") setColourChosen(true);
    setValues((was) => ({ ...was, [name]: value }));
  }

  /** Read the username of the user chosen, and fill the label with it when it comes. */
  function nameFrom(choice: PersonChoice) {
    if (choice.way !== "user" || choice.contactHid === "") {
      naming.current = null;
      return;
    }
    if (naming.current?.hid === choice.contactHid) return;
    const hid = choice.contactHid;
    const username = api.request("get", "/api/v1/contacts/{hid}", { path: { hid } }).then(
      (contact) => contact.user?.username ?? null,
      // A contact that is not read names nothing: the label is typed.
      () => null,
    );
    const asked: Naming = { hid, username, filled: filled.current };
    naming.current = asked;
    void username.then((name) => {
      if (naming.current !== asked || name === null) return;
      setValues((was) => ({
        ...was,
        label: labelFor(typeof was.label === "string" ? was.label : "", asked.filled, name),
      }));
      filled.current = name;
    });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    let ready = shown;
    const asked = naming.current;
    const colourPending = !colourChosen && nextColour.next === null;
    if (asked || colourPending) {
      setWaiting(true);
      try {
        const [name, colour] = await Promise.all([
          asked ? asked.username : null,
          colourPending ? nextColour.wait() : null,
        ]);
        const typed = typeof ready.label === "string" ? ready.label : "";
        ready = {
          ...ready,
          ...(asked && naming.current === asked
            ? { label: labelFor(typed, asked.filled, name) }
            : {}),
          ...(colour ? { colour } : {}),
        };
      } finally {
        setWaiting(false);
      }
    }
    const built = buildCreate<Schemas["OperatorCreate"]>(specs, ready);
    const read = readPerson(person);
    const wrong = { ...built.errors, ...(read.ok ? {} : { [read.field]: read.error }) };
    setFound(wrong);
    if (Object.keys(wrong).length > 0) {
      action.clear();
      return;
    }
    const result = await action.run(async () => {
      const contact = await contactOf(person, (one) => {
        setMade(one);
        setPerson(personChoice("contact", one.value));
      });
      return api.request("post", "/api/v1/operators", {
        body: { ...built.body, ...(contact ? { contact_hid: contact } : {}) },
      });
    });
    if (result.ok) onCreated(result.value);
  }

  return (
    <section className="panel" aria-labelledby="new-operator">
      <h2 id="new-operator">New operator</h2>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={names} />
        {made && action.error && (
          <p className="hint" data-testid="contact-made">
            The contact {made.label} was made, and is chosen below as the person behind it.
          </p>
        )}
        <FormFields
          specs={specs}
          values={shown}
          onChange={change}
          errors={errors}
          disabled={busy}
        />
        <PersonChooser
          legend="Person behind it"
          name="new-operator"
          ways={["user", "contact", "new", "none"]}
          wayLabels={{ none: "Nobody: an open assignment" }}
          choice={person}
          onChange={(next) => {
            setFound({});
            setPerson(next);
            nameFrom(next);
          }}
          errors={errors}
          known={made ? [made] : []}
          hint="The member of the team the label stands for: internal where that person is a user, external where not. A user chosen gives the label its username, unless one is typed."
          disabled={busy}
        />
        <p className="actions">
          <button type="submit" className="primary" disabled={busy}>
            Create operator
          </button>
          <button type="button" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
        </p>
        {waiting && (
          <p role="status" className="muted">
            Waiting for what the form fills in, the username or the colour…
          </p>
        )}
      </form>
    </section>
  );
}

/**
 * Hand the label over to another person, or leave it open. Everything the label is on
 * follows at once: nothing is written to any of it. 0.9.3: the person is a user, another
 * contact, or a new person, whose name, email and numbers make a new contact (P-172).
 */
function HandOver({ operator, onChanged, onReload }: ChangeProps) {
  const [to, setTo] = useState<PersonChoice>(() => personChoice("user"));
  const [made, setMade] = useState<Option | null>(null);
  const [found, setFound] = useState<Record<string, string>>({});
  const action = useAction();
  const errors: Record<string, string> = { ...action.error?.fields, ...found };

  async function send(choice: PersonChoice | null, done: string) {
    if (choice) {
      const read = readPerson(choice);
      if (!read.ok) {
        action.clear();
        setFound({ [read.field]: read.error });
        return;
      }
    }
    setFound({});
    const result = await action.run(async () => {
      const contact = choice
        ? await contactOf(choice, (one) => {
            setMade(one);
            setTo(personChoice("contact", one.value));
          })
        : null;
      return api.request("patch", "/api/v1/operators/{hid}", {
        path: { hid: operator.hid },
        body: { row_version: operator.row_version, contact_hid: contact },
      });
    });
    if (result.ok) {
      const name = result.value.contact?.name;
      onChanged(done.replace("{name}", name ?? "another person"));
    }
  }

  const chosen =
    to.way === "new" || (to.contactHid !== "" && to.contactHid !== operator.contact_hid);
  return (
    <section aria-labelledby="hand-over">
      <h2 id="hand-over">Hand over, or leave open</h2>
      <p className="hint">
        For a new hire, or when the team swaps its assignments: another person behind the label
        takes over every item, group and place the label is on, at once. Left open, the label stays
        on all of it, marked as open, until somebody is put behind it.
      </p>
      <Problem error={action.error} shown={PERSON_FIELDS} onReload={onReload} />
      {made && action.error && (
        <p className="hint" data-testid="contact-made">
          The contact {made.label} was made, and is chosen below.
        </p>
      )}
      <PersonChooser
        legend="Hand over to"
        name="hand-over"
        ways={["user", "contact", "new"]}
        choice={to}
        onChange={(next) => {
          setFound({});
          setTo(next);
        }}
        errors={errors}
        known={made ? [made] : []}
        disabled={action.busy}
      />
      <p className="actions">
        <button
          type="button"
          className="primary"
          disabled={action.busy || !chosen}
          onClick={() => send(to, `${operator.label} was handed over to {name}.`)}
        >
          Hand over
        </button>
        <button
          type="button"
          disabled={action.busy || operator.contact_hid === null}
          onClick={() => send(null, `${operator.label} is left open: nobody is behind it for now.`)}
        >
          Leave open
        </button>
      </p>
    </section>
  );
}

/** Release what the label is on, or bring a released label back. Nothing is deleted. */
function Release({ operator, onChanged, onReload }: ChangeProps) {
  const action = useAction();

  async function release() {
    const result = await action.run(() =>
      api.request("post", "/api/v1/operators/{hid}/retire", {
        path: { hid: operator.hid },
        body: { row_version: operator.row_version },
      }),
    );
    if (result.ok) onChanged(`${operator.label} was released.`);
  }

  async function bringBack() {
    const result = await action.run(() =>
      api.request("patch", "/api/v1/operators/{hid}", {
        path: { hid: operator.hid },
        body: { row_version: operator.row_version, record_status: "active" },
      }),
    );
    if (result.ok) onChanged(`${operator.label} is back: what it was on has it again.`);
  }

  const released = operator.record_status === "retired";
  return (
    <section aria-labelledby="release">
      <h2 id="release">{released ? "Released" : "Release"}</h2>
      <Problem error={action.error} onReload={onReload} />
      {released ? (
        <>
          <p>
            This label is released: it stands for nothing. Each item, group and place it was on has
            the operator of the next level up, or none. It is still on them, and brought back it is
            their operator again.
          </p>
          <p className="actions">
            <button type="button" onClick={bringBack} disabled={action.busy}>
              Bring back
            </button>
          </p>
        </>
      ) : (
        <>
          <p>
            Releasing lets go of everything the label is on, all at once: each item, group and place
            then has the operator of the next level up, or none. Nothing is written to any of them,
            and the label can be brought back.
          </p>
          <p className="actions">
            <ConfirmButton
              label="Release"
              title={`Release ${operator.label}?`}
              confirmLabel="Release"
              onConfirm={release}
              disabled={action.busy}
            >
              <p>
                {operator.uses > 0
                  ? `It is given to ${plural(operator.uses, "item, group or place", "items, groups and places")}, which then have the operator of the next level up, or none.`
                  : "It is given to nothing."}{" "}
                The label can be brought back.
              </p>
            </ConfirmButton>
          </p>
        </>
      )}
    </section>
  );
}
