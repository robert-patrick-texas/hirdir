// The parts of a circuit's page (P-145 to P-150): what it is, its two sides, where its
// cost counts, its carriers with their numbers, its cost lines with the totals, the
// devices it connects and its groups. Each part is changed by its own route, and each
// change says what it did; a value the server refuses is shown under its field, with
// the server's reason.

import { type FormEvent, type ReactNode, useState } from "react";
import { Link } from "react-router";
import { api, type Schemas } from "../api";
import {
  CARRIER_ROLE_LIST,
  CIRCUIT_TYPE_LIST,
  type Circuit,
  circuitGroupPath,
  connectedHids,
  countingSide,
  devicePath,
  devicesBody,
  lineCarrier,
  mbpsText,
  moneyText,
  notInServiceText,
  otherSide,
  ownerPath,
  type PendingDevice,
  rateText,
  readMoney,
  SIDES,
  type Side,
  sideLabel,
  sideOf,
  vendorPath,
  weightHint,
} from "../lib/circuits";
import { effectiveText } from "../lib/effective";
import { itemName, today } from "../lib/format";
import { useAction } from "../lib/hooks";
import { useVendorOptions } from "../lib/lists";
import { choiceLabel, choiceOptions, optionLabel, RECORD_STATUSES } from "../lib/options";
import { canonicalDecimal } from "../lib/patch";
import { placePath } from "../lib/places";
import { fieldErrors } from "../lib/problems";
import { dateValue, decimalValue } from "../lib/sort";
import { useSorting } from "../lib/useSorting";
import { ConfirmButton } from "./ConfirmButton";
import { SelectField, TextAreaField, TextField } from "./Field";
import { ItemPicker } from "./ItemPicker";
import { Problem } from "./Problem";
import { findGroups, SearchPicker } from "./SearchPicker";
import { SortTh } from "./SortTh";
import { Time } from "./Time";

type Choice = Schemas["ChoiceOut"];
type Carrier = Schemas["CircuitCarrierOut"];
type CostLine = Schemas["CircuitCostOut"];
type Device = Schemas["CircuitDeviceOut"];

export function Dash() {
  return <span className="muted">—</span>;
}

function Fact({
  label,
  children,
  testId,
}: {
  label: string;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <>
      <dt>{label}</dt>
      <dd {...(testId ? { "data-testid": testId } : {})}>{children || <Dash />}</dd>
    </>
  );
}

function yes(value: boolean): string {
  return value ? "Yes" : "No";
}

/** What a whole number typed into a form is, or null for none or one that is no number. */
function whole(typed: string): number | null {
  const text = typed.trim();
  return /^\d{1,4}$/.test(text) ? Number.parseInt(text, 10) : null;
}

// --- what it is -----------------------------------------------------------------------

interface CircuitFactsProps {
  circuit: Circuit;
  choices: readonly Choice[] | undefined;
}

/** What a circuit is: its fields, and what the server works out when it is read. */
export function CircuitFacts({ circuit, choices }: CircuitFactsProps) {
  const weight = circuit.effective.support_weight;
  return (
    <section aria-labelledby="circuit">
      <h2 id="circuit">Circuit</h2>
      <dl className="facts">
        <Fact label="Name">{circuit.name}</Fact>
        <Fact label="Enterprise circuit ID" testId="enterprise-id">
          {circuit.enterprise_circuit_id && (
            <span className="mono">{circuit.enterprise_circuit_id}</span>
          )}
        </Fact>
        <Fact label="Type">{choiceLabel(choices, CIRCUIT_TYPE_LIST, circuit.circuit_type)}</Fact>
        <Fact label="Speed" testId="speed">
          {circuit.speed && (
            <>
              <strong>{circuit.speed}</strong>
              <span className="muted">
                {" "}
                · port {mbpsText(circuit.port_mbps)} Mbps · down{" "}
                <span
                  data-testid="rate-down"
                  data-source={circuit.effective.down_mbps.source}
                  className={
                    circuit.effective.down_mbps.source === "port" ? "inherited" : undefined
                  }
                >
                  {rateText(circuit.effective.down_mbps)}
                </span>{" "}
                · up{" "}
                <span
                  data-testid="rate-up"
                  data-source={circuit.effective.up_mbps.source}
                  className={circuit.effective.up_mbps.source === "port" ? "inherited" : undefined}
                >
                  {rateText(circuit.effective.up_mbps)}
                </span>
              </span>
            </>
          )}
        </Fact>
        <Fact label="Description">{circuit.description}</Fact>
        <Fact label="In service today" testId="in-service">
          {yes(circuit.in_service)}
        </Fact>
        <Fact label="Carries production">{yes(circuit.production)}</Fact>
        <Fact label="Installed on">{circuit.a_installed_on}</Fact>
        <Fact label="Activated on">{circuit.a_activated_on}</Fact>
        <Fact label="Disconnected on">{circuit.a_disconnected_on}</Fact>
        <Fact label="Billing account">{circuit.billing_account}</Fact>
        <Fact label="Billing contract">{circuit.billing_contract}</Fact>
        <Fact label="Owner" testId="owner">
          {circuit.owner && (
            <>
              <Link to={ownerPath(circuit.owner.hid)}>{circuit.owner.label}</Link>
              {circuit.owner_exception && (
                <span className="badge" data-testid="owner-exception">
                  Outside the operations team
                </span>
              )}
            </>
          )}
        </Fact>
        {circuit.owner_exception && (
          <Fact label="Reason for the exception">
            {circuit.owner_exception_reason}
            <span className="muted"> · the owner&apos;s own reason</span>
          </Fact>
        )}
        <Fact label="Support weight" testId="support-weight">
          {weight.value !== null && (
            <span
              data-source={weight.source}
              className={weight.source === "own" ? undefined : "inherited"}
            >
              {effectiveText(weight)}
              <span className="muted"> · {weightHint(weight)}</span>
            </span>
          )}
        </Fact>
        <Fact label="Tags">{circuit.tags.join(", ")}</Fact>
        <Fact label="Notes">{circuit.notes}</Fact>
        <Fact label="Changed">
          <Time at={circuit.updated_at} />
        </Fact>
        <Fact label="HID">
          <span className="mono">{circuit.hid}</span>
        </Fact>
      </dl>
    </section>
  );
}

// --- its two sides --------------------------------------------------------------------

/** Each side: its location's path and site, or its note where it has none. */
export function CircuitSides({ circuit }: { circuit: Circuit }) {
  const counting = countingSide(circuit);
  return (
    <section aria-labelledby="sides">
      <h2 id="sides">Its two sides</h2>
      <p className="hint">
        The A side is the source and the Z side the destination. A side at a location has that
        location&apos;s site, region, address and site contacts; one with no location ends outside
        the network, and its note says where.
      </p>
      <dl className="facts">
        {SIDES.map(({ value: side, label }) => {
          const { at, note } = sideOf(circuit, side);
          return (
            <Fact key={side} label={label} testId={`side-${side}`}>
              <span data-location={at?.location_hid ?? ""}>
                {at ? (
                  <>
                    <Link to={placePath("location", at.location_hid)}>{at.path}</Link>
                    {at.record_status !== "active" && (
                      <span className="badge">
                        {optionLabel(RECORD_STATUSES, at.record_status)}
                      </span>
                    )}
                    <span className="muted">
                      {" "}
                      · site <Link to={placePath("site", at.site_hid)}>{at.site_path}</Link>
                    </span>
                  </>
                ) : (
                  <span className="muted">No location</span>
                )}
                {note && (
                  <span data-testid={`note-${side}`}>
                    {" "}
                    · <em>{note}</em>
                  </span>
                )}
                {counting === side && (
                  <span className="badge badge-plain mark" data-testid={`counts-${side}`}>
                    Its cost counts here
                  </span>
                )}
              </span>
            </Fact>
          );
        })}
      </dl>
    </section>
  );
}

// --- where it counts ------------------------------------------------------------------

interface ChangeProps {
  circuit: Circuit;
  mayEdit: boolean;
  onChanged: (text: string) => void;
}

/**
 * The side whose site the cost and the support weight of the circuit count at, and the
 * control that switches it to the other side. A circuit counts at its A side unless it
 * is switched, one circuit at a time (P-150).
 */
export function WhereItCounts(props: ChangeProps & { onReload: () => void }) {
  const { circuit, mayEdit, onChanged, onReload } = props;
  const action = useAction();
  const named = circuit.cost_side;
  const counting = countingSide(circuit);
  const other = otherSide(named);
  const otherAt = sideOf(circuit, other).at;

  async function switchSide() {
    const result = await action.run(() =>
      api.request("patch", "/api/v1/circuits/{hid}", {
        path: { hid: circuit.hid },
        body: { row_version: circuit.row_version, cost_side: other },
      }),
    );
    if (result.ok) onChanged(`The cost of ${circuit.name} now counts at its ${sideLabel(other)}.`);
  }

  return (
    <section aria-labelledby="counts">
      <h2 id="counts">Where it counts</h2>
      <Problem error={action.error} shown={[]} onReload={onReload} />
      <p data-testid="counts-at" data-side={named} data-counting={counting}>
        Its cost and its support weight count at its <strong>{sideLabel(named)}</strong>
        {counting !== named && (
          <>, which has no location: they count at the {sideLabel(counting)}</>
        )}
        {circuit.cost_site_path ? (
          <>
            , at the site{" "}
            <Link to={placePath("site", circuit.cost_site_hid ?? "")} data-testid="cost-site">
              {circuit.cost_site_path}
            </Link>
            .
          </>
        ) : (
          "."
        )}
      </p>
      {mayEdit && (
        <p className="actions">
          <button type="button" disabled={action.busy} onClick={switchSide}>
            Count it at the {sideLabel(other)}
          </button>
          <span className="hint">
            {otherAt
              ? ` Its cost and its weight then count at ${otherAt.site_path}.`
              : ` The ${sideLabel(other)} has no location: it would count at the ${sideLabel(named)} still, until it has one.`}
          </span>
        </p>
      )}
    </section>
  );
}

// --- its carriers ---------------------------------------------------------------------

/** One row of the table of carriers: the primary one, or another in its part. */
interface CarrierRow {
  key: string;
  vendorHid: string;
  vendor: string;
  role: string;
  number: string | null;
  priority: number | null;
  notes: string | null;
  link: Carrier | null;
}

/**
 * The carriers of a circuit: the primary carrier, with the number it gives the circuit,
 * changed under Details, and the others, each a vendor in its part with its own number,
 * added, changed and removed here (P-148).
 */
export function CircuitCarriers(props: ChangeProps & { choices: readonly Choice[] | undefined }) {
  const { circuit, choices, mayEdit, onChanged } = props;
  const removing = useAction();
  const [editing, setEditing] = useState<string | null>(null);
  const others = circuit.carriers ?? [];
  const rows: CarrierRow[] = [
    ...(circuit.carrier
      ? [
          {
            key: "primary",
            vendorHid: circuit.carrier.hid,
            vendor: circuit.carrier.name,
            role: "Primary carrier",
            number: circuit.carrier_circuit_number,
            priority: null,
            notes: null,
            link: null,
          },
        ]
      : []),
    ...others.map((link) => ({
      key: link.hid,
      vendorHid: link.vendor_hid,
      vendor: link.vendor,
      role: choiceLabel(choices, CARRIER_ROLE_LIST, link.role),
      number: link.circuit_number,
      priority: link.priority,
      notes: link.notes,
      link,
    })),
  ];
  const sorting = useSorting(rows, {
    vendor: (row) => row.vendor,
    role: (row) => row.role,
    number: (row) => row.number,
    priority: (row) => row.priority,
    notes: (row) => row.notes,
  });
  const chosen = others.find((link) => link.hid === editing) ?? null;

  async function remove(link: Carrier) {
    const result = await removing.run(() =>
      api.request("delete", "/api/v1/circuits/{hid}/carriers/{link_hid}", {
        path: { hid: circuit.hid, link_hid: link.hid },
      }),
    );
    if (result.ok) onChanged(`${link.vendor} is no longer a carrier of ${circuit.name}.`);
  }

  return (
    <section aria-labelledby="carriers" data-testid="carriers">
      <h2 id="carriers">Carriers</h2>
      <p className="hint">
        The primary carrier, or the other party that provides the circuit, and the number it gives
        it are changed under Details. The others, a local exchange carrier or the provider of a
        cross-connect, are named here, each in its part and with the number it gives the circuit.
      </p>
      <Problem error={removing.error} />
      {rows.length === 0 ? (
        <p className="muted">No carrier is named.</p>
      ) : (
        <div className="scroll">
          <table>
            <caption className="visually-hidden">The carriers of {circuit.name}</caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="vendor">
                  Carrier
                </SortTh>
                <SortTh sort={sorting} column="role">
                  Part
                </SortTh>
                <SortTh sort={sorting} column="number">
                  Circuit number
                </SortTh>
                <SortTh sort={sorting} column="priority" className="number">
                  Priority
                </SortTh>
                <SortTh sort={sorting} column="notes">
                  Notes
                </SortTh>
                {mayEdit && <th scope="col">Change</th>}
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((row) => (
                <tr key={row.key} data-carrier={row.vendor} data-primary={row.link === null}>
                  <th scope="row">
                    <Link to={vendorPath(row.vendorHid)}>{row.vendor}</Link>
                  </th>
                  <td data-testid="carrier-role">{row.role}</td>
                  <td className="mono" data-testid="carrier-number">
                    {row.number || <Dash />}
                  </td>
                  <td className="number">{row.priority ?? <Dash />}</td>
                  <td>{row.notes || <Dash />}</td>
                  {mayEdit && (
                    <td className="row-actions">
                      {row.link === null ? (
                        <span className="muted">Changed under Details</span>
                      ) : (
                        <>
                          <button
                            type="button"
                            onClick={() => setEditing(row.key)}
                            disabled={removing.busy}
                          >
                            Change
                          </button>
                          <ConfirmButton
                            label="Remove"
                            title={`Remove ${row.vendor} as a carrier of ${circuit.name}?`}
                            confirmLabel="Remove the carrier"
                            onConfirm={() => row.link && remove(row.link)}
                            disabled={removing.busy}
                          >
                            <p>
                              For a carrier that was named by mistake. The vendor itself stays, and
                              the removal is in the audit trail with what it was. A carrier that a
                              cost line names is not removed while it does.
                            </p>
                          </ConfirmButton>
                        </>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {mayEdit && chosen && (
        <CarrierForm
          key={`${chosen.hid} ${chosen.row_version}`}
          circuit={circuit}
          choices={choices}
          link={chosen}
          onDone={(text) => {
            setEditing(null);
            onChanged(text);
          }}
          onCancel={() => setEditing(null)}
        />
      )}
      {mayEdit && !chosen && (
        <CarrierForm circuit={circuit} choices={choices} link={null} onDone={onChanged} />
      )}
    </section>
  );
}

interface CarrierFormProps {
  circuit: Circuit;
  choices: readonly Choice[] | undefined;
  /** The carrier to change, or null to name another. */
  link: Carrier | null;
  onDone: (text: string) => void;
  onCancel?: () => void;
}

/** Name another carrier of a circuit, or change one: its vendor, part, number, priority, notes. */
function CarrierForm({ circuit, choices, link, onDone, onCancel }: CarrierFormProps) {
  const vendors = useVendorOptions();
  const [vendor, setVendor] = useState(link?.vendor_hid ?? "");
  const [role, setRole] = useState(link?.role ?? "");
  const [number, setNumber] = useState(link?.circuit_number ?? "");
  const [priority, setPriority] = useState(link ? String(link.priority) : "");
  const [notes, setNotes] = useState(link?.notes ?? "");
  const action = useAction();
  const known = ["vendor_hid", "role", "circuit_number", "priority", "notes"];
  const refused = fieldErrors(action.error, known).shown;
  const order = whole(priority);
  const badPriority = priority.trim() !== "" && order === null;
  const ready = vendor !== "" && role !== "" && !badPriority;
  // A vendor is named once on a circuit: those named already are not offered.
  const named = new Set([
    ...(circuit.carrier_hid ? [circuit.carrier_hid] : []),
    ...(circuit.carriers ?? []).map((one) => one.vendor_hid),
  ]);
  const offered = (vendors.data ?? []).filter(
    (option) => option.value === link?.vendor_hid || !named.has(option.value),
  );
  const heading = link ? `Change ${link.vendor}` : "Name another carrier";
  const id = link ? `carrier-form-${link.hid}` : "carrier-form";

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready) return;
    const text = (value: string) => (value.trim() === "" ? null : value.trim());
    if (link === null) {
      const body: Schemas["CircuitCarrierAdd"] = {
        vendor_hid: vendor,
        role,
        circuit_number: text(number),
        notes: text(notes),
        ...(order === null ? {} : { priority: order }),
      };
      const result = await action.run(() =>
        api.request("post", "/api/v1/circuits/{hid}/carriers", {
          path: { hid: circuit.hid },
          body,
        }),
      );
      if (!result.ok) return;
      onDone(`${result.value.vendor} is now a carrier of ${circuit.name}.`);
      setVendor("");
      setNumber("");
      setPriority("");
      setNotes("");
      return;
    }
    const body: Schemas["CircuitCarrierPatch"] = { row_version: link.row_version };
    if (vendor !== link.vendor_hid) body.vendor_hid = vendor;
    if (role !== link.role) body.role = role;
    if (text(number) !== link.circuit_number) body.circuit_number = text(number);
    if (text(notes) !== link.notes) body.notes = text(notes);
    if (order !== null && order !== link.priority) body.priority = order;
    const result = await action.run(() =>
      api.request("patch", "/api/v1/circuits/{hid}/carriers/{link_hid}", {
        path: { hid: circuit.hid, link_hid: link.hid },
        body,
      }),
    );
    if (result.ok) onDone(`${result.value.vendor} was saved as a carrier of ${circuit.name}.`);
  }

  return (
    <section aria-labelledby={id} className="panel">
      <h3 id={id}>{heading}</h3>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={vendors.error ?? action.error} shown={known} />
        <div className="fields">
          <SelectField
            label="Carrier"
            name="vendor_hid"
            value={vendor}
            onChange={setVendor}
            required
            disabled={action.busy}
            error={refused.vendor_hid}
            hint="A vendor, from the one list of vendors. A vendor is named once on a circuit."
          >
            <option value="">Choose a vendor</option>
            {offered.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="Part"
            name="role"
            value={role}
            onChange={setRole}
            required
            disabled={action.busy}
            error={refused.role}
          >
            <option value="">Choose its part</option>
            {choiceOptions(choices, CARRIER_ROLE_LIST, link?.role ?? null).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </SelectField>
          <TextField
            label="Circuit number"
            name="circuit_number"
            value={number}
            onChange={setNumber}
            maxLength={100}
            autoComplete="off"
            disabled={action.busy}
            error={refused.circuit_number}
            hint="The number this carrier gives the circuit, where it gives one."
          />
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
            hint="The order in which they are listed. Left blank, after the last."
          />
          <TextAreaField
            label="Notes"
            name="notes"
            value={notes}
            onChange={setNotes}
            maxLength={10000}
            disabled={action.busy}
            error={refused.notes}
          />
        </div>
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || !ready}>
            {link ? "Save the carrier" : "Name the carrier"}
          </button>
          {onCancel && (
            <button type="button" onClick={onCancel} disabled={action.busy}>
              Cancel
            </button>
          )}
        </p>
      </form>
    </section>
  );
}

// --- its cost lines -------------------------------------------------------------------

/**
 * The cost of a circuit: the lines the carrier bills each month, each with its dates,
 * and the monthly cost, the sum of the lines billed today, beside the annual cost,
 * twelve times that. A new rate is a line that ends and one that begins; a line entered
 * by mistake is removed (P-150).
 */
export function CircuitCosts({ circuit, mayEdit, onChanged }: ChangeProps) {
  const removing = useAction();
  const [editing, setEditing] = useState<string | null>(null);
  const [ending, setEnding] = useState<string | null>(null);
  const lines = circuit.costs ?? [];
  const primary = circuit.carrier?.name ?? null;
  const sorting = useSorting(lines, {
    description: (line) => line.description,
    monthly: (line) => decimalValue(line.monthly_cost),
    carrier: (line) => lineCarrier(line, primary),
    starts: (line) => dateValue(line.starts_on),
    ends: (line) => dateValue(line.ends_on),
    billed: (line) => (line.in_date ? "Yes" : "No"),
    notes: (line) => line.notes,
  });
  const chosen = lines.find((line) => line.hid === editing) ?? null;
  const toEnd = lines.find((line) => line.hid === ending) ?? null;

  async function remove(line: CostLine) {
    const result = await removing.run(() =>
      api.request("delete", "/api/v1/circuits/{hid}/costs/{line_hid}", {
        path: { hid: circuit.hid, line_hid: line.hid },
      }),
    );
    if (result.ok) onChanged(`The line ${line.description} was removed from ${circuit.name}.`);
  }

  return (
    <section aria-labelledby="costs" data-testid="costs">
      <h2 id="costs">Cost</h2>
      <dl className="totals" data-testid="cost-totals">
        <div>
          <dt>Monthly cost</dt>
          <dd data-testid="monthly-cost">{moneyText(circuit.monthly_cost)}</dd>
        </div>
        <div>
          <dt>Annual cost</dt>
          <dd data-testid="annual-cost">{moneyText(circuit.annual_cost)}</dd>
        </div>
      </dl>
      <p className="hint">
        The monthly cost is the sum of the lines billed today, while the circuit is in service; the
        annual cost is twelve times that. A credit is a line below zero. A line billed for a time is
        given an end; one entered by mistake is removed.
      </p>
      {!circuit.in_service && (
        <p className="alert alert-info" data-testid="not-in-service">
          {notInServiceText(circuit, today())}
        </p>
      )}
      <Problem error={removing.error} />
      {lines.length === 0 ? (
        <p className="muted">No cost line is entered.</p>
      ) : (
        <div className="scroll">
          <table>
            <caption className="visually-hidden">The cost lines of {circuit.name}</caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="description">
                  Line
                </SortTh>
                <SortTh sort={sorting} column="monthly" className="number">
                  Monthly cost
                </SortTh>
                <SortTh sort={sorting} column="carrier">
                  Billed by
                </SortTh>
                <SortTh sort={sorting} column="starts">
                  Starts
                </SortTh>
                <SortTh sort={sorting} column="ends">
                  Ends
                </SortTh>
                <SortTh sort={sorting} column="billed">
                  Billed today
                </SortTh>
                <SortTh sort={sorting} column="notes">
                  Notes
                </SortTh>
                {mayEdit && <th scope="col">Change</th>}
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((line) => (
                <tr
                  key={line.hid}
                  data-line={line.description}
                  className={line.in_date ? undefined : "row-dim"}
                >
                  <th scope="row">{line.description}</th>
                  <td className="number" data-testid="line-cost">
                    {moneyText(line.monthly_cost)}
                  </td>
                  <td className={line.vendor_hid ? undefined : "inherited"}>
                    {lineCarrier(line, primary)}
                  </td>
                  <td>{line.starts_on || <Dash />}</td>
                  <td data-testid="line-ends">{line.ends_on || <Dash />}</td>
                  <td data-testid="line-billed">{yes(line.in_date)}</td>
                  <td>{line.notes || <Dash />}</td>
                  {mayEdit && (
                    <td className="row-actions">
                      <button
                        type="button"
                        onClick={() => {
                          setEnding(null);
                          setEditing(line.hid);
                        }}
                        disabled={removing.busy}
                      >
                        Change
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setEditing(null);
                          setEnding(line.hid);
                        }}
                        disabled={removing.busy}
                      >
                        End
                      </button>
                      <ConfirmButton
                        label="Remove"
                        title={`Remove the line ${line.description}?`}
                        confirmLabel="Remove the line"
                        onConfirm={() => remove(line)}
                        disabled={removing.busy}
                      >
                        <p>
                          For a line entered by mistake: it is taken out of every figure, also of
                          the years it was billed in. A line that was billed for a time is given an
                          end instead. The removal is in the audit trail with what it was.
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
      {mayEdit && toEnd && (
        <EndLine
          key={`end ${toEnd.hid} ${toEnd.row_version}`}
          circuit={circuit}
          line={toEnd}
          onDone={(text) => {
            setEnding(null);
            onChanged(text);
          }}
          onCancel={() => setEnding(null)}
        />
      )}
      {mayEdit && chosen && (
        <CostForm
          key={`${chosen.hid} ${chosen.row_version}`}
          circuit={circuit}
          line={chosen}
          onDone={(text) => {
            setEditing(null);
            onChanged(text);
          }}
          onCancel={() => setEditing(null)}
        />
      )}
      {mayEdit && !chosen && !toEnd && (
        <CostForm circuit={circuit} line={null} onDone={onChanged} />
      )}
    </section>
  );
}

/** The carriers a cost line may name: blank for the primary one, or one of the others. */
function lineCarriers(circuit: Circuit): Array<{ value: string; label: string }> {
  const primary = circuit.carrier?.name;
  return [
    { value: "", label: primary ? `${primary} (the primary carrier)` : "The primary carrier" },
    ...(circuit.carriers ?? []).map((link) => ({ value: link.vendor_hid, label: link.vendor })),
  ];
}

interface CostFormProps {
  circuit: Circuit;
  /** The line to change, or null to add one. */
  line: CostLine | null;
  onDone: (text: string) => void;
  onCancel?: () => void;
}

/** Add a cost line, or change one: what it is, what it costs a month, who bills it, its dates. */
function CostForm({ circuit, line, onDone, onCancel }: CostFormProps) {
  const [description, setDescription] = useState(line?.description ?? "");
  const [cost, setCost] = useState(line?.monthly_cost ?? "");
  const [vendor, setVendor] = useState(line?.vendor_hid ?? "");
  const [starts, setStarts] = useState(line?.starts_on ?? "");
  const [ends, setEnds] = useState(line?.ends_on ?? "");
  const [notes, setNotes] = useState(line?.notes ?? "");
  const action = useAction();
  const known = ["description", "monthly_cost", "vendor_hid", "starts_on", "ends_on", "notes"];
  const refused = fieldErrors(action.error, known).shown;
  const amount = readMoney(cost);
  const badAmount = "error" in amount ? amount.error : undefined;
  const ready = description.trim() !== "" && "value" in amount && amount.value !== null;
  const id = line ? `cost-form-${line.hid}` : "cost-form";

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready || !("value" in amount) || amount.value === null) return;
    const text = (value: string) => (value.trim() === "" ? null : value.trim());
    if (line === null) {
      const body: Schemas["CircuitCostAdd"] = {
        description: description.trim(),
        monthly_cost: amount.value,
        vendor_hid: text(vendor),
        starts_on: text(starts),
        ends_on: text(ends),
        notes: text(notes),
      };
      const result = await action.run(() =>
        api.request("post", "/api/v1/circuits/{hid}/costs", { path: { hid: circuit.hid }, body }),
      );
      if (!result.ok) return;
      onDone(`The line ${result.value.description} was added to ${circuit.name}.`);
      setDescription("");
      setCost("");
      setStarts("");
      setEnds("");
      setNotes("");
      return;
    }
    const body: Schemas["CircuitCostPatch"] = { row_version: line.row_version };
    if (description.trim() !== line.description) body.description = description.trim();
    if (canonicalDecimal(amount.value) !== canonicalDecimal(line.monthly_cost)) {
      body.monthly_cost = amount.value;
    }
    if (text(vendor) !== line.vendor_hid) body.vendor_hid = text(vendor);
    if (text(starts) !== line.starts_on) body.starts_on = text(starts);
    if (text(ends) !== line.ends_on) body.ends_on = text(ends);
    if (text(notes) !== line.notes) body.notes = text(notes);
    const result = await action.run(() =>
      api.request("patch", "/api/v1/circuits/{hid}/costs/{line_hid}", {
        path: { hid: circuit.hid, line_hid: line.hid },
        body,
      }),
    );
    if (result.ok) onDone(`The line ${result.value.description} was saved.`);
  }

  return (
    <section aria-labelledby={id} className="panel">
      <h3 id={id}>{line ? `Change the line ${line.description}` : "Add a cost line"}</h3>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={known} />
        <div className="fields">
          <TextField
            label="Line"
            name="description"
            value={description}
            onChange={setDescription}
            required
            maxLength={200}
            autoComplete="off"
            disabled={action.busy}
            error={refused.description}
            hint="As the carrier bills it: Port, Local loop, Access, Promotional credit. No two lines of a circuit have the same."
          />
          <TextField
            label="Monthly cost"
            name="monthly_cost"
            value={cost}
            onChange={setCost}
            required
            inputMode="decimal"
            maxLength={20}
            autoComplete="off"
            disabled={action.busy}
            error={refused.monthly_cost ?? badAmount}
            hint="Below zero for a credit."
          />
          <SelectField
            label="Billed by"
            name="vendor_hid"
            value={vendor}
            onChange={setVendor}
            disabled={action.busy}
            error={refused.vendor_hid}
            hint="The primary carrier, or one of the others named above."
          >
            {lineCarriers(circuit).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </SelectField>
          <TextField
            label="Billed from"
            name="starts_on"
            type="date"
            value={starts}
            onChange={setStarts}
            disabled={action.busy}
            error={refused.starts_on}
            hint="Blank: from the start."
          />
          <TextField
            label="Billed until"
            name="ends_on"
            type="date"
            value={ends}
            onChange={setEnds}
            disabled={action.busy}
            error={refused.ends_on}
            hint="Blank: with no end."
          />
          <TextAreaField
            label="Notes"
            name="notes"
            value={notes}
            onChange={setNotes}
            maxLength={10000}
            disabled={action.busy}
            error={refused.notes}
          />
        </div>
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || !ready}>
            {line ? "Save the line" : "Add the line"}
          </button>
          {onCancel && (
            <button type="button" onClick={onCancel} disabled={action.busy}>
              Cancel
            </button>
          )}
        </p>
      </form>
    </section>
  );
}

/** Give a cost line an end: the last day it is billed. A new rate is a line that begins after it. */
function EndLine(props: {
  circuit: Circuit;
  line: CostLine;
  onDone: (text: string) => void;
  onCancel: () => void;
}) {
  const { circuit, line, onDone, onCancel } = props;
  const [day, setDay] = useState(line.ends_on ?? today());
  const action = useAction();
  const refused = fieldErrors(action.error, ["ends_on"]).shown;
  const id = `end-line-${line.hid}`;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (day.trim() === "") return;
    const result = await action.run(() =>
      api.request("patch", "/api/v1/circuits/{hid}/costs/{line_hid}", {
        path: { hid: circuit.hid, line_hid: line.hid },
        body: { row_version: line.row_version, ends_on: day.trim() },
      }),
    );
    if (result.ok) onDone(`The line ${line.description} is billed until ${day.trim()}.`);
  }

  return (
    <section aria-labelledby={id} className="panel">
      <h3 id={id}>End the line {line.description}</h3>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={["ends_on"]} />
        <div className="fields">
          <TextField
            label="Last day billed"
            name="ends_on"
            type="date"
            value={day}
            onChange={setDay}
            required
            disabled={action.busy}
            error={refused.ends_on}
          />
        </div>
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || day.trim() === ""}>
            End the line
          </button>
          <button type="button" onClick={onCancel} disabled={action.busy}>
            Cancel
          </button>
        </p>
      </form>
    </section>
  );
}

// --- its devices ----------------------------------------------------------------------

/**
 * The devices a circuit connects, each on its side: the router at each end, or the pair
 * of routers in a group that share it. Chosen from the inventory several at a time, and
 * sent together. One connected by mistake, or whose device was taken out, is removed
 * (P-147).
 */
export function CircuitDevices({ circuit, mayEdit, onChanged }: ChangeProps) {
  const removing = useAction();
  const moving = useAction();
  const devices = circuit.devices ?? [];
  const sorting = useSorting(devices, {
    side: (device) => device.side,
    device: (device) => device.name,
    kind: (device) => (device.item_hid ? "Item" : "Device group"),
    status: (device) => device.record_status,
    notes: (device) => device.notes,
  });

  async function remove(device: Device) {
    const result = await removing.run(() =>
      api.request("delete", "/api/v1/circuits/{hid}/devices/{link_hid}", {
        path: { hid: circuit.hid, link_hid: device.hid },
      }),
    );
    if (result.ok) onChanged(`${device.name} is no longer connected to ${circuit.name}.`);
  }

  async function move(device: Device) {
    const side = otherSide(device.side);
    const result = await moving.run(() =>
      api.request("patch", "/api/v1/circuits/{hid}/devices/{link_hid}", {
        path: { hid: circuit.hid, link_hid: device.hid },
        body: { row_version: device.row_version, side },
      }),
    );
    if (result.ok) onChanged(`${device.name} is now on the ${sideLabel(side)} of ${circuit.name}.`);
  }

  return (
    <section aria-labelledby="devices" data-testid="devices">
      <h2 id="devices">Devices</h2>
      <Problem error={removing.error ?? moving.error} />
      {devices.length === 0 ? (
        <p className="muted">No device is connected.</p>
      ) : (
        <div className="scroll">
          <table>
            <caption className="visually-hidden">The devices {circuit.name} connects</caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="side">
                  Side
                </SortTh>
                <SortTh sort={sorting} column="device">
                  Device
                </SortTh>
                <SortTh sort={sorting} column="kind">
                  Kind
                </SortTh>
                <SortTh sort={sorting} column="status">
                  Status
                </SortTh>
                <SortTh sort={sorting} column="notes">
                  Notes
                </SortTh>
                {mayEdit && <th scope="col">Change</th>}
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((device) => (
                <tr
                  key={device.hid}
                  data-device={device.name}
                  data-side={device.side}
                  className={device.record_status === "retired" ? "row-dim" : undefined}
                >
                  <td>{sideLabel(device.side)}</td>
                  <th scope="row">
                    <Link to={devicePath(device)}>{device.name}</Link>
                  </th>
                  <td>{device.item_hid ? "Item" : "Device group"}</td>
                  <td>
                    {device.record_status === "active" ? (
                      "Active"
                    ) : (
                      <span className="badge">
                        {optionLabel(RECORD_STATUSES, device.record_status)}
                      </span>
                    )}
                  </td>
                  <td>{device.notes || <Dash />}</td>
                  {mayEdit && (
                    <td className="row-actions">
                      <button
                        type="button"
                        onClick={() => move(device)}
                        disabled={moving.busy || removing.busy}
                      >
                        To the {sideLabel(otherSide(device.side))}
                      </button>
                      <ConfirmButton
                        label="Disconnect"
                        title={`Disconnect ${device.name} from ${circuit.name}?`}
                        confirmLabel="Disconnect"
                        onConfirm={() => remove(device)}
                        disabled={removing.busy}
                      >
                        <p>
                          For a device connected by mistake, or one that was taken out. The device
                          itself stays, and the removal is in the audit trail with what it was.
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
      {mayEdit && <ConnectDevices circuit={circuit} onChanged={onChanged} />}
    </section>
  );
}

/** Choose items and device groups to connect, each on its side, and connect them together. */
function ConnectDevices({
  circuit,
  onChanged,
}: {
  circuit: Circuit;
  onChanged: (text: string) => void;
}) {
  const [side, setSide] = useState<Side>("a");
  const [pending, setPending] = useState<PendingDevice[]>([]);
  const action = useAction();
  const taken = [...connectedHids(circuit.devices ?? []), ...pending.map((device) => device.hid)];
  const rows = useSorting(pending, {
    device: (device) => device.name,
    kind: (device) => device.kind,
    side: (device) => device.side,
  });

  function add(device: PendingDevice) {
    setPending((was) => (was.some((one) => one.hid === device.hid) ? was : [...was, device]));
  }

  function setSideOf(hid: string, next: Side) {
    setPending((was) => was.map((one) => (one.hid === hid ? { ...one, side: next } : one)));
  }

  async function connect(event: FormEvent) {
    event.preventDefault();
    if (pending.length === 0) return;
    const result = await action.run(() =>
      api.request("post", "/api/v1/circuits/{hid}/devices", {
        path: { hid: circuit.hid },
        body: devicesBody(pending),
      }),
    );
    if (!result.ok) return;
    const count = pending.length;
    setPending([]);
    onChanged(
      count === 1
        ? `${pending[0]?.name ?? "The device"} is now connected to ${circuit.name}.`
        : `${count} devices are now connected to ${circuit.name}.`,
    );
  }

  return (
    <section aria-labelledby="connect-devices" className="panel">
      <h3 id="connect-devices">Connect devices</h3>
      <p className="hint">
        Choose the items and device groups of the inventory it connects, as many as there are, each
        on its side, then connect them together. A device is connected to a circuit once; a retired
        one is not offered.
      </p>
      <form onSubmit={connect} className="stack" noValidate>
        <Problem error={action.error} />
        <div className="fields">
          <SelectField
            label="Side of what is chosen next"
            name="side"
            value={side}
            onChange={(next) => setSide(next === "z" ? "z" : "a")}
            disabled={action.busy}
          >
            {SIDES.map((one) => (
              <option key={one.value} value={one.value}>
                {one.label}
              </option>
            ))}
          </SelectField>
          <ItemPicker
            label="Add an item"
            taken={taken}
            disabled={action.busy}
            onPick={(item) =>
              add({
                kind: "item",
                hid: item.hid,
                name: itemName(item),
                side,
              })
            }
          />
          <SearchPicker
            label="Add a device group"
            hint="Type a part of its name: a pair of routers that share the circuit, a stack, a cluster."
            noun={["device group", "device groups"]}
            find={findGroups}
            taken={taken}
            disabled={action.busy}
            onPick={(offer) => add({ kind: "group", hid: offer.hid, name: offer.label, side })}
          />
        </div>
        {pending.length > 0 && (
          <div className="scroll">
            <table data-testid="devices-to-connect">
              <caption>The devices to connect</caption>
              <thead>
                <tr>
                  <SortTh sort={rows} column="device">
                    Device
                  </SortTh>
                  <SortTh sort={rows} column="kind">
                    Kind
                  </SortTh>
                  <SortTh sort={rows} column="side">
                    Side
                  </SortTh>
                  <th scope="col">Leave out</th>
                </tr>
              </thead>
              <tbody>
                {rows.rows.map((device) => (
                  <tr key={device.hid} data-device={device.name}>
                    <th scope="row">{device.name}</th>
                    <td>{device.kind === "item" ? "Item" : "Device group"}</td>
                    <td>
                      <SelectField
                        label={`Side of ${device.name}`}
                        name={`side-${device.hid}`}
                        value={device.side}
                        onChange={(next) => setSideOf(device.hid, next === "z" ? "z" : "a")}
                        disabled={action.busy}
                      >
                        {SIDES.map((one) => (
                          <option key={one.value} value={one.value}>
                            {one.label}
                          </option>
                        ))}
                      </SelectField>
                    </td>
                    <td>
                      <button
                        type="button"
                        disabled={action.busy}
                        onClick={() =>
                          setPending((was) => was.filter((one) => one.hid !== device.hid))
                        }
                      >
                        Leave out
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || pending.length === 0}>
            {pending.length === 0
              ? "Connect the devices"
              : pending.length === 1
                ? "Connect 1 device"
                : `Connect ${pending.length} devices`}
          </button>
        </p>
      </form>
    </section>
  );
}

// --- its groups -----------------------------------------------------------------------

/** The groups a circuit is in, each leading to its page. Circuits are put into a group there. */
export function CircuitGroupsOf({ circuit }: { circuit: Circuit }) {
  const groups = circuit.groups ?? [];
  const sorting = useSorting(groups, {
    name: (group) => group.name,
    status: (group) => group.record_status,
  });
  return (
    <section aria-labelledby="circuit-groups" data-testid="groups-of-circuit">
      <h2 id="circuit-groups">Groups</h2>
      <p className="hint">
        A circuit may be in any number of groups. It is put into a group, and taken out of one, on
        the page of the group, under <Link to="/circuit-groups">Circuit groups</Link>.
      </p>
      {groups.length === 0 ? (
        <p className="muted">It is in no group.</p>
      ) : (
        <div className="scroll">
          <table>
            <caption className="visually-hidden">The groups {circuit.name} is in</caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="name">
                  Group
                </SortTh>
                <SortTh sort={sorting} column="status">
                  Status
                </SortTh>
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((group) => (
                <tr key={group.hid} data-group={group.name}>
                  <th scope="row">
                    <Link to={circuitGroupPath(group.hid)}>{group.name}</Link>
                  </th>
                  <td>{optionLabel(RECORD_STATUSES, group.record_status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
