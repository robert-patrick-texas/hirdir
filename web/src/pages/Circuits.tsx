// Circuits (P-145 to P-154): the grid of circuits, the form for a new one, and the page
// of each, with its sides, where it counts, its carriers, its cost lines, its devices,
// its contacts and its groups.

import { useMemo, useState } from "react";
import { Link, NavLink, useNavigate, useParams, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { CircuitContacts } from "../components/CircuitContacts";
import {
  CircuitCarriers,
  CircuitCosts,
  CircuitDevices,
  CircuitFacts,
  CircuitGroupsOf,
  CircuitSides,
  WhereItCounts,
} from "../components/CircuitParts";
import { CircuitsGrid } from "../components/CircuitsGrid";
import { Notice, Problem } from "../components/Problem";
import { CreateForm, EditForm } from "../components/RecordForm";
import { References } from "../components/References";
import { Retire } from "../components/Retire";
import {
  CIRCUIT_TYPE_LIST,
  type Circuit,
  circuitPath,
  mbpsText,
  SIDES,
  sideLabel,
  switchesOf,
} from "../lib/circuits";
import { useLoad, useTitle } from "../lib/hooks";
import {
  useChoices,
  useOwnerOptions,
  useSettings,
  useTags,
  useVendorOptions,
  withCurrent,
} from "../lib/lists";
import { choiceOptions, optionLabel, RECORD_STATUSES, SETTABLE_STATUSES } from "../lib/options";
import { ownerOption } from "../lib/owners";
import type { FieldSpec, Option } from "../lib/patch";
import { allows } from "../lib/roles";

type Choice = Schemas["ChoiceOut"];

/** The second row of navigation on the pages of circuits and of circuit groups. */
export function CircuitsNav() {
  return (
    <nav className="sub" aria-label="Circuits">
      <ul>
        <li>
          <NavLink to="/circuits" end>
            Circuits
          </NavLink>
        </li>
        <li>
          <NavLink to="/circuit-groups">Circuit groups</NavLink>
        </li>
      </ul>
    </nav>
  );
}

/** The lists the form of a circuit offers, read once for the page. */
function useCircuitLists() {
  const choices = useChoices();
  const vendors = useVendorOptions();
  const owners = useOwnerOptions();
  const tags = useTags();
  // The same object while what was read stays the same, so that the fields are made once.
  const lists = useMemo(
    () => ({
      choices: choices.data,
      vendors: vendors.data,
      owners: owners.data,
      tags: (tags.data ?? []).map((tag) => tag.label),
    }),
    [choices.data, vendors.data, owners.data, tags.data],
  );
  return {
    lists,
    error: choices.error ?? vendors.error ?? owners.error ?? tags.error,
    ready: !choices.loading && !vendors.loading && !owners.loading && !tags.loading,
  };
}

interface Lists {
  choices: readonly Choice[] | undefined;
  vendors: readonly Option[] | undefined;
  owners: readonly Option[] | undefined;
  tags: readonly string[];
}

const NOTE_HINT =
  "Where it ends: carrier network, cloud on-ramp, demarc in the basement. Needed where the side has no location.";

/**
 * The fields of a circuit, for the form that makes one and for the one that changes it.
 * The speed is entered as the port, and the rates down and up, which are left blank for
 * the full rate of the port. A side is a location, chosen as a location is chosen
 * elsewhere, or none and a note of where it ends. The side its cost counts at is chosen
 * when it is made, and switched on its page.
 */
function circuitSpecs(lists: Lists, record: Circuit | null, settingSide: string): FieldSpec[] {
  const making = record === null;
  const sideFields = SIDES.flatMap(({ value: side, label }): FieldSpec[] => {
    const at = record ? (side === "a" ? record.a_side : record.z_side) : null;
    return [
      {
        name: `${side}_location_hid`,
        label: `${label}: location`,
        kind: "location",
        blank: "No location: it ends outside the network",
        options: at ? [{ value: at.location_hid, label: at.path }] : [],
        heading: label,
      },
      {
        name: `${side}_note`,
        label: `${label}: note`,
        kind: "text",
        maxLength: 200,
        hint: NOTE_HINT,
      },
    ];
  });
  const owner = record?.owner
    ? ownerOption({ ...record.owner, exception_reason: record.owner_exception_reason })
    : null;
  return [
    {
      name: "name",
      label: "Name",
      kind: "text",
      required: true,
      maxLength: 200,
      heading: "Circuit",
    },
    {
      name: "enterprise_circuit_id",
      label: "Enterprise circuit ID",
      kind: "text",
      maxLength: 100,
      hint: "The enterprise's own ID, assigned locally. No two circuits have the same one.",
    },
    {
      name: "circuit_type",
      label: "Type",
      kind: "choice",
      blank: "No type",
      options: choiceOptions(lists.choices, CIRCUIT_TYPE_LIST, record?.circuit_type ?? null),
    },
    { name: "description", label: "Description", kind: "longtext", maxLength: 10000 },
    {
      name: "port_mbps",
      label: "Port speed (Mbps)",
      kind: "decimal",
      places: 2,
      hint: "The speed of the physical interface: 1000 for 1G.",
      heading: "Speed",
    },
    {
      name: "down_mbps",
      label: "Rate down (Mbps)",
      kind: "decimal",
      places: 2,
      hint: "The rate it is limited to, download. Blank: the full rate of the port.",
    },
    {
      name: "up_mbps",
      label: "Rate up (Mbps)",
      kind: "decimal",
      places: 2,
      hint: "The rate it is limited to, upload. Blank: the full rate of the port.",
    },
    ...sideFields,
    ...(making
      ? [
          {
            name: "cost_side",
            label: "Its cost counts at",
            kind: "choice",
            blank: `As the setting says: the ${sideLabel(settingSide === "z" ? "z" : "a")}`,
            options: SIDES,
            hint: "The side whose site its cost and its support weight count at. It can be switched on its page.",
            heading: "Where it counts",
          } satisfies FieldSpec,
        ]
      : []),
    {
      name: "carrier_hid",
      label: "Carrier",
      kind: "choice",
      blank: "No carrier",
      options: withCurrent(
        lists.vendors,
        record?.carrier ? { value: record.carrier.hid, label: record.carrier.name } : null,
      ),
      hint: "The primary carrier, or the other party that provides it: a vendor. The others are named on its page.",
      heading: "Carrier and billing",
    },
    {
      name: "carrier_circuit_number",
      label: "Carrier's circuit number",
      kind: "text",
      maxLength: 100,
      hint: "The number the primary carrier gives it, where it gives one.",
    },
    { name: "billing_account", label: "Billing account", kind: "text", maxLength: 200 },
    { name: "billing_contract", label: "Billing contract", kind: "text", maxLength: 200 },
    { name: "installed_on", label: "Installed on", kind: "date", heading: "Dates" },
    {
      name: "activated_on",
      label: "Activated on",
      kind: "date",
      hint: "The carrier bills it from this day.",
    },
    {
      name: "disconnected_on",
      label: "Disconnected on",
      kind: "date",
      hint: "The last day it was in service.",
    },
    making
      ? {
          name: "production",
          label: "Carries production",
          kind: "choice",
          options: [
            { value: "true", label: "Yes" },
            { value: "false", label: "No" },
          ],
          hint: "Whether it carries the enterprise's production work. It changes nothing of what it costs.",
          heading: "Its standing",
        }
      : {
          name: "production",
          label: "Carries production",
          kind: "boolean",
          hint: "Whether it carries the enterprise's production work. It changes nothing of what it costs.",
          heading: "Its standing",
        },
    {
      name: "support_weight",
      label: "Support weight",
      kind: "decimal",
      places: 2,
      hint: "The work it adds. Blank: the default of circuits, where an Admin has set one.",
    },
    {
      name: "owner_hid",
      label: "Owner",
      kind: "choice",
      blank: "No owner",
      options: withCurrent(lists.owners, owner),
      hint: "The person or team responsible for it, its primary stakeholder. Who pays for it is said by a tag or in the notes.",
    },
    {
      name: "record_status",
      label: "Record status",
      kind: "choice",
      options: SETTABLE_STATUSES,
      hint: "A draft is left out of counts and default views",
    },
    {
      name: "tags",
      label: "Tags",
      kind: "set",
      options: [...new Set([...lists.tags, ...(record?.tags ?? [])])].map((label) => ({
        value: label,
        label,
      })),
      hint: "A tag is made under Admin, then used here",
    },
    { name: "notes", label: "Notes", kind: "longtext", maxLength: 10000 },
  ];
}

/** What the form of a new circuit sends: whether it carries production comes as text. */
type NewCircuitBody = Omit<Schemas["CircuitCreate"], "production"> & { production?: string };

function NewCircuit({
  onCancel,
  onCreated,
}: {
  onCancel: () => void;
  onCreated: (circuit: Circuit) => void;
}) {
  const { lists, error, ready } = useCircuitLists();
  const settings = useSettings();
  const settingSide = String(
    settings.data?.find((setting) => setting.key === "circuit_cost_side")?.value ?? "a",
  );
  const specs = useMemo(() => circuitSpecs(lists, null, settingSide), [lists, settingSide]);
  if (!ready || settings.loading) {
    return (
      <p role="status" className="muted loading-late">
        Loading…
      </p>
    );
  }
  return (
    <>
      <Problem error={error ?? settings.error} />
      <CreateForm<NewCircuitBody, Circuit>
        title="New circuit"
        specs={specs}
        start={{ production: "true", record_status: "active" }}
        create={({ production, ...body }) =>
          api.request("post", "/api/v1/circuits", {
            body: { ...body, production: production !== "false" },
          })
        }
        onCreated={onCreated}
        onCancel={onCancel}
        submitLabel="Create circuit"
      />
    </>
  );
}

/**
 * Circuits: the grid of circuits, filtered, sorted and exported by the server as the
 * item grid is, and the form for a new one. A link may bring a filter in its address,
 * as a row of the report of what circuits cost does, and ask for drafts and retired ones.
 */
export function Circuits() {
  useTitle("Circuits");
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const startFilter = params.get("filter");
  // As the item grid takes them, `archived=1` and `drafts=1`, or by the names of the
  // list's own parameters, as a row of the report of what circuits cost hands them on.
  const { archived: withArchived, drafts: withDrafts } = switchesOf(params);
  const [adding, setAdding] = useState(false);
  const mayChange = allows(user.role, "inventory");

  return (
    <>
      <CircuitsNav />
      <h1>Circuits</h1>
      <p>
        Telecommunication circuits beside the inventory. Each side is a location, or none where it
        ends outside the network; its carriers are vendors; its devices are items and device groups.
      </p>
      {adding && (
        <NewCircuit
          onCancel={() => setAdding(false)}
          onCreated={(circuit) => navigate(circuitPath(circuit.hid))}
        />
      )}
      <CircuitsGrid
        key={`${startFilter ?? ""} ${withArchived} ${withDrafts}`}
        id="circuits"
        shortFilter="circuit_type:eq:internet effective.down_mbps:lt:100"
        startFilter={startFilter}
        startSwitches={
          withArchived || withDrafts
            ? {
                ...(withArchived ? { archived: true } : {}),
                ...(withDrafts ? { drafts: true } : {}),
              }
            : null
        }
        switches
      >
        {mayChange && !adding && (
          <button type="button" className="primary" onClick={() => setAdding(true)}>
            New circuit
          </button>
        )}
      </CircuitsGrid>
    </>
  );
}

/** Circuits → one circuit. */
export function CircuitDetail() {
  const { hid = "" } = useParams();
  const { user } = useAuth();
  const mayEdit = allows(user.role, "inventory");
  const circuit = useLoad(`circuit ${hid}`, (signal) =>
    api.request("get", "/api/v1/circuits/{hid}", { path: { hid }, signal }),
  );
  const choices = useChoices();
  const [done, setDone] = useState("");
  const record = circuit.data;
  useTitle(record ? record.name : "Circuit");

  function changed(text: string) {
    setDone(text);
    circuit.reload();
  }

  const open = mayEdit && record !== undefined && record.record_status !== "retired";
  return (
    <>
      <CircuitsNav />
      <p className="crumbs">
        <Link to="/circuits">Circuits</Link>
      </p>
      <h1>
        {record ? record.name : "Circuit"}
        {record?.speed && <span className="badge badge-plain">{record.speed}</span>}
        {record && record.record_status !== "active" && (
          <span className="badge" data-testid="circuit-status">
            {optionLabel(RECORD_STATUSES, record.record_status)}
          </span>
        )}
      </h1>
      <Problem error={circuit.error} />
      <Problem error={choices.error} />
      <Notice text={done} />
      {circuit.loading && !record && <p role="status">Loading…</p>}
      {record && (
        <>
          <CircuitFacts circuit={record} choices={choices.data} />
          <CircuitSides circuit={record} />
          <WhereItCounts
            key={`counts ${record.hid} ${record.row_version}`}
            circuit={record}
            mayEdit={open}
            onChanged={changed}
            onReload={circuit.reload}
          />
          <CircuitCarriers
            circuit={record}
            choices={choices.data}
            mayEdit={open}
            onChanged={changed}
          />
          <CircuitCosts circuit={record} mayEdit={open} onChanged={changed} />
          <CircuitDevices circuit={record} mayEdit={open} onChanged={changed} />
          <CircuitContacts
            circuit={record}
            choices={choices.data}
            mayEdit={open}
            onChanged={changed}
          />
          <CircuitGroupsOf circuit={record} />
          {/* 0.9.0: its own references, as a letter of authorization (P-158). */}
          <References
            key={`references ${record.hid}`}
            holder={{ kind: "circuit", hid: record.hid }}
            mayEdit={mayEdit}
          />
          {open && (
            <CircuitDetails
              key={`details ${record.hid} ${record.row_version}`}
              circuit={record}
              onSaved={() => changed("The circuit was saved.")}
              onReload={circuit.reload}
            />
          )}
          {mayEdit && (
            <Retire
              what="circuit"
              name={record.name}
              retired={record.record_status === "retired"}
              about="A retired circuit is left out of lists and of what circuits cost, unless they are asked for it. Its carriers, cost lines, devices and contacts stay on record, and it stays listed in its groups."
              retiredAbout={
                record.disconnected_on
                  ? `This circuit is retired. It was in service until ${record.disconnected_on}, and counts for that time in what circuits cost.`
                  : "This circuit is retired, with no day it was disconnected: it was taken out, and is in service on no day."
              }
              retire={() =>
                api.request("post", "/api/v1/circuits/{hid}/retire", {
                  path: { hid: record.hid },
                  body: { row_version: record.row_version },
                })
              }
              bringBack={() =>
                api.request("patch", "/api/v1/circuits/{hid}", {
                  path: { hid: record.hid },
                  body: { row_version: record.row_version, record_status: "active" },
                })
              }
              onChanged={changed}
              onReload={circuit.reload}
            />
          )}
        </>
      )}
    </>
  );
}

interface CircuitDetailsProps {
  circuit: Circuit;
  onSaved: () => void;
  onReload: () => void;
}

/** The form for everything about a circuit but the side it counts at. Only what was changed is sent. */
function CircuitDetails({ circuit, onSaved, onReload }: CircuitDetailsProps) {
  const { lists, error, ready } = useCircuitLists();
  const specs = useMemo(() => circuitSpecs(lists, circuit, circuit.cost_side), [lists, circuit]);
  const port = circuit.port_mbps ? `${mbpsText(circuit.port_mbps)} Mbps` : "";
  const hints = port
    ? {
        down_mbps: circuit.down_mbps
          ? "Set here. Blank: the full rate of the port."
          : `Blank: the full rate of the port, ${port}.`,
        up_mbps: circuit.up_mbps
          ? "Set here. Blank: the full rate of the port."
          : `Blank: the full rate of the port, ${port}.`,
      }
    : undefined;
  return (
    <section aria-labelledby="details">
      <h2 id="details">Details</h2>
      <Problem error={error} />
      {!ready && <p role="status">Loading…</p>}
      {ready && (
        <EditForm<Circuit, Schemas["CircuitPatch"]>
          specs={specs}
          record={circuit}
          {...(hints ? { hints } : {})}
          save={(body) =>
            api.request("patch", "/api/v1/circuits/{hid}", { path: { hid: circuit.hid }, body })
          }
          onSaved={onSaved}
          onReload={onReload}
        />
      )}
    </section>
  );
}
