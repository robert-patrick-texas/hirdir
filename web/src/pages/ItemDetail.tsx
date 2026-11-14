import { type FormEvent, type ReactNode, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { Addresses, ManagementAddresses } from "../components/Addresses";
import { BringBackElsewhere, refusedForItsPlace } from "../components/BringBack";
import { ConfirmButton } from "../components/ConfirmButton";
import { CheckField, SelectField } from "../components/Field";
import { HealthWithReasons, Observation, ObservedText } from "../components/Health";
import { Memberships, MinorItems, Place, Replacement } from "../components/ItemStructure";
import { Operator, OperatorNote } from "../components/Operator";
import { Pager } from "../components/Pager";
import { Notice, Problem } from "../components/Problem";
import { EditForm } from "../components/RecordForm";
import { Time } from "../components/Time";
import {
  effectiveLabel,
  effectiveText,
  inheritHint,
  isInherited,
  sourceHint,
  sourceLabel,
} from "../lib/effective";
import { formatMac, formatValue, itemName } from "../lib/format";
import { CONDITION_LIST } from "../lib/health";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import {
  DISPOSITIONS,
  dispositionsIn,
  mayBeOnline,
  mayInheritAgain,
  nextStates,
  onlineText,
  type Rule,
  standingOf,
  stateNames,
} from "../lib/lifecycle";
import {
  useChoices,
  useEntryOptions,
  useOwnerOptions,
  useRules,
  useTags,
  withCurrent,
} from "../lib/lists";
import { operatorOptionLabel } from "../lib/operators";
import {
  CATALOG_KINDS,
  choiceLabel,
  choiceOptions,
  optionLabel,
  RECORD_STATUSES,
  SETTABLE_STATUSES,
} from "../lib/options";
import { ownerOption } from "../lib/owners";
import type { FieldSpec } from "../lib/patch";
import { placePath } from "../lib/places";
import { fieldErrors } from "../lib/problems";
import { allows } from "../lib/roles";

type Item = Schemas["ItemOut"];
type Choice = Schemas["ChoiceOut"];
/** The fields an item inherits from its catalog entry. */
type Inherited =
  | "est_value"
  | "support_weight"
  | "annual_support_cost"
  | "end_of_sale"
  | "end_of_sw_support"
  | "end_of_hw_support"
  | "ldos";

const HISTORY_PAGE = 50;

/** Those fields as people read them. */
const INHERITED: ReadonlyArray<[field: Inherited, label: string]> = [
  ["est_value", "Estimated value"],
  ["support_weight", "Support weight"],
  ["annual_support_cost", "Annual support cost"],
  ["end_of_sale", "End of sale"],
  ["end_of_sw_support", "End of software support"],
  ["end_of_hw_support", "End of hardware support"],
  ["ldos", "Last day of support (LDoS)"],
];

function Dash() {
  return <span className="muted">—</span>;
}

/** Items → one item: what it is, the values in force, its standing, and its history. */
export function ItemDetail() {
  const { hid = "" } = useParams();
  const { user } = useAuth();
  const mayEdit = allows(user.role, "inventory");
  const item = useLoad(`item ${hid}`, (signal) =>
    api.request("get", "/api/v1/items/{hid}", { path: { hid }, signal }),
  );
  const choices = useChoices();
  const rules = useRules();
  const [done, setDone] = useState("");
  const states = useMemo(() => stateNames(rules.data ?? []), [rules.data]);
  useTitle(item.data ? itemName(item.data) : "Item");

  function changed(text: string) {
    setDone(text);
    item.reload();
  }

  const record = item.data;
  return (
    <>
      <p className="crumbs">
        <Link to="/items">Items</Link>
      </p>
      <h1>
        {record ? itemName(record) : "Item"}
        {record && record.record_status !== "active" && (
          <span className="badge">{optionLabel(RECORD_STATUSES, record.record_status)}</span>
        )}
      </h1>
      <Problem error={item.error} />
      <Problem error={choices.error ?? rules.error} />
      <Notice text={done} />
      {item.loading && !record && <p role="status">Loading…</p>}
      {record && (
        <>
          <Facts item={record} choices={choices.data} />
          <Doing
            key={`doing ${record.hid} ${record.row_version}`}
            item={record}
            choices={choices.data}
            mayEdit={mayEdit && record.record_status !== "retired"}
            onChanged={changed}
            onReload={item.reload}
          />
          <Place
            key={`place ${record.hid} ${record.row_version}`}
            item={record}
            mayEdit={mayEdit && record.record_status !== "retired"}
            onChanged={changed}
            onReload={item.reload}
          />
          <MinorItems
            item={record}
            states={states}
            mayEdit={mayEdit && record.record_status !== "retired"}
            onChanged={changed}
          />
          <Memberships item={record} />
          <Addresses
            key={`addresses ${record.hid}`}
            holder={{ item_hid: record.hid }}
            whose={itemName(record)}
            mayEdit={mayEdit && record.record_status !== "retired"}
            onChanged={item.reload}
          />
          <ValuesInForce item={record} />
          <Lifecycle
            key={`standing ${record.hid} ${record.row_version}`}
            item={record}
            rules={rules.data ?? []}
            choices={choices.data}
            mayEdit={mayEdit && record.record_status !== "retired"}
            mayForce={allows(user.role, "admin")}
            onChanged={changed}
            onReload={item.reload}
          />
          {mayEdit && record.record_status !== "retired" && (
            <Details
              key={`details ${record.hid} ${record.row_version}`}
              item={record}
              onSaved={() => changed("The item was saved.")}
              onReload={item.reload}
            />
          )}
          <Replacement
            key={`replacement ${record.hid} ${record.row_version}`}
            item={record}
            choices={choices.data}
            mayEdit={mayEdit && record.record_status !== "retired"}
            onChanged={changed}
            onReload={item.reload}
          />
          {mayEdit && (
            <RecordStatus
              key={`status ${record.hid} ${record.row_version}`}
              item={record}
              onChanged={changed}
              onReload={item.reload}
            />
          )}
          <History item={record} />
        </>
      )}
    </>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children || <Dash />}</dd>
    </>
  );
}

function Facts({ item, choices }: { item: Item; choices: readonly Choice[] | undefined }) {
  const { catalog } = item;
  // The owner in force: a minor item with none of its own has the owner of the item it is in.
  const owner = item.effective.owner_hid;
  const ownerInherited = isInherited(owner);
  // The location in force, likewise: a minor item is where the item it is in is.
  const location = item.effective.location_hid;
  const locationInherited = isInherited(location);
  return (
    <section aria-labelledby="identity">
      <h2 id="identity">Identity</h2>
      <dl className="facts">
        <Fact label="Name">{item.name}</Fact>
        <Fact label="Hostname">{item.hostname}</Fact>
        <Fact label="FQDN">{item.fqdn}</Fact>
        <Fact label="Serial number">
          {item.serial_number && <span className="mono">{item.serial_number}</span>}
        </Fact>
        <Fact label="Asset tag">{item.asset_tag}</Fact>
        <Fact label="MAC address">
          {item.mac_address && <span className="mono">{formatMac(item.mac_address)}</span>}
        </Fact>
        <Fact label="Catalog entry">
          {catalog && (
            <>
              <Link to={`/catalog/${encodeURIComponent(catalog.hid)}`}>
                {catalog.vendor} {catalog.pid}
              </Link>
              {catalog.model_name && <span className="muted"> · {catalog.model_name}</span>}
            </>
          )}
        </Fact>
        <Fact label="Kind, type, function">
          {catalog &&
            [
              optionLabel(CATALOG_KINDS, catalog.kind),
              choiceLabel(choices, "catalog_type", catalog.type),
              choiceLabel(choices, "catalog_function", catalog.function),
            ]
              .filter(Boolean)
              .join(" · ")}
        </Fact>
        <Fact label="Owner">
          {typeof owner.value === "string" && (
            <span data-testid="owner" data-source={owner.source}>
              <Link to={`/owners/${encodeURIComponent(owner.value)}`}>{effectiveLabel(owner)}</Link>
              {ownerInherited && (
                <span className="inherited">
                  {" "}
                  · {sourceLabel(owner)}
                  {owner.source_hid && (
                    <>
                      {": "}
                      <Link to={`/items/${encodeURIComponent(owner.source_hid)}`}>
                        the item that has it
                      </Link>
                    </>
                  )}
                </span>
              )}
              {item.owner_exception && (
                <span className="badge" data-testid="owner-exception">
                  Outside the operations team
                </span>
              )}
            </span>
          )}
        </Fact>
        {item.owner_exception && typeof owner.value === "string" && (
          <Fact label="Reason for the exception">
            <span data-testid="owner-exception-reason">{item.owner_exception_reason}</span>
            <span className="muted">
              {" "}
              · the owner&apos;s own reason, changed on{" "}
              <Link to={`/owners/${encodeURIComponent(owner.value)}`}>the page of the owner</Link>
            </span>
          </Fact>
        )}
        <Fact label="Operator">
          <Operator effective={item.effective.operator_hid} testId="operator" />
        </Fact>
        <Fact label="Location">
          {typeof location.value === "string" && (
            <span data-testid="location" data-source={location.source}>
              <Link to={placePath("location", location.value)}>{effectiveLabel(location)}</Link>
              <span className={locationInherited ? "inherited" : "muted"}>
                {" "}
                · {sourceLabel(location)}
                {locationInherited && location.source_hid && (
                  <>
                    {": "}
                    <Link to={`/items/${encodeURIComponent(location.source_hid)}`}>
                      the item that has it
                    </Link>
                  </>
                )}
              </span>
            </span>
          )}
        </Fact>
        <Fact label="Site">
          {location.site && location.site_hid && (
            <Link to={placePath("site", location.site_hid)} data-testid="site">
              {location.site}
            </Link>
          )}
        </Fact>
        <Fact label="Region">
          {location.region && location.region_hid && (
            <Link to={placePath("region", location.region_hid)} data-testid="region">
              {location.region}
            </Link>
          )}
        </Fact>
        <Fact label="Management address">
          <ManagementAddresses addresses={item.addresses} />
        </Fact>
        <Fact label="Quantity">{String(item.quantity)}</Fact>
        <Fact label="Tags">{item.tags.join(", ")}</Fact>
        <Fact label="Description">{item.description}</Fact>
        <Fact label="Comments">{item.comments}</Fact>
        <Fact label="Procured">{item.procured_on}</Fact>
        <Fact label="Delivered">{item.delivered_on}</Fact>
        <Fact label="In service">{item.in_service_on}</Fact>
        <Fact label="Warranty">
          {(item.warranty_start || item.warranty_end) &&
            `${item.warranty_start ?? "…"} to ${item.warranty_end ?? "…"}`}
        </Fact>
        <Fact label="Created">
          <Time at={item.created_at} />
        </Fact>
        <Fact label="Changed">
          <Time at={item.updated_at} />
        </Fact>
        <Fact label="HID">
          <span className="mono">{item.hid}</span>
        </Fact>
      </dl>
    </section>
  );
}

interface DoingProps {
  item: Item;
  choices: readonly Choice[] | undefined;
  mayEdit: boolean;
  onChanged: (text: string) => void;
  onReload: () => void;
}

/**
 * How the item is doing. Three facts are kept apart: the condition, which a person
 * records; what is observed, with the moment it was seen; and the intent, which is under
 * Lifecycle. The health is what the server makes of the three, with its reasons.
 */
function Doing({ item, choices, mayEdit, onChanged, onReload }: DoingProps) {
  const [condition, setCondition] = useState(item.condition ?? "");
  const saving = useAction();
  const seeing = useAction();
  const conditions = choiceOptions(choices, CONDITION_LIST, item.condition);
  const refused = fieldErrors(saving.error, ["condition"]).shown;
  const intent = item.effective.expected_online.value;

  async function saveCondition(event: FormEvent) {
    event.preventDefault();
    const result = await saving.run(() =>
      api.request("patch", "/api/v1/items/{hid}", {
        path: { hid: item.hid },
        body: { row_version: item.row_version, condition: condition === "" ? null : condition },
      }),
    );
    if (result.ok) onChanged("The condition of the item was saved.");
  }

  return (
    <section aria-labelledby="doing">
      <h2 id="doing">Condition and health</h2>
      <dl className="facts">
        <dt>Health</dt>
        <dd>
          <HealthWithReasons health={item.health} testId="health" />
        </dd>
        <dt>Condition</dt>
        <dd data-testid="condition" data-condition={item.condition ?? ""}>
          {choiceLabel(choices, CONDITION_LIST, item.condition) || (
            <span className="muted">Nobody has said</span>
          )}
        </dd>
        <dt>Observed</dt>
        <dd data-testid="observed" data-observed={item.observed_status ?? ""}>
          <ObservedText status={item.observed_status} at={item.observed_at} />
        </dd>
        <dt>Expected online</dt>
        <dd>{typeof intent === "boolean" ? intent ? "Yes" : "No" : <Dash />}</dd>
      </dl>
      <p className="hint">
        The condition is the state of the hardware as a person knows it, and holds while the item is
        on a shelf. What is observed is what is seen of the item on the network, or Present: what a
        person saw of something that is never on the network. Health is worked out from the two and
        from whether the item is expected online, each time the item is read. None of them moves the
        item in the lifecycle: a move is made under Lifecycle, with its own reason.
        {!item.is_major &&
          " A minor item inherits neither: each is a fact about one piece of hardware."}
      </p>
      {mayEdit && (
        <>
          <section aria-labelledby="set-condition" className="panel">
            <h3 id="set-condition">Record the condition</h3>
            <form onSubmit={saveCondition} className="stack" noValidate>
              <Problem error={saving.error} shown={["condition"]} onReload={onReload} />
              <div className="inline">
                <SelectField
                  label="Condition"
                  name="condition"
                  value={condition}
                  onChange={setCondition}
                  disabled={saving.busy}
                  error={refused.condition}
                  hint="Untested is new and not yet tried, and so of unknown health"
                >
                  <option value="">Nobody has said</option>
                  {conditions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </SelectField>
              </div>
              <p className="actions">
                <button
                  type="submit"
                  className="primary"
                  disabled={saving.busy || condition === (item.condition ?? "")}
                >
                  Save condition
                </button>
              </p>
            </form>
          </section>
          <section aria-labelledby="set-observed" className="panel">
            <h3 id="set-observed">Record what is seen</h3>
            <Observation
              whose={itemName(item)}
              status={item.observed_status}
              busy={seeing.busy}
              error={seeing.error}
              onReload={onReload}
              onChange={async (patch, done) => {
                const result = await seeing.run(() =>
                  api.request("patch", "/api/v1/items/{hid}", {
                    path: { hid: item.hid },
                    body: { row_version: item.row_version, ...patch },
                  }),
                );
                if (result.ok) onChanged(done);
              }}
            />
          </section>
        </>
      )}
    </section>
  );
}

/** Every field the item inherits: the value in force, and where it came from. */
function ValuesInForce({ item }: { item: Item }) {
  return (
    <section aria-labelledby="values">
      <h2 id="values">Values in force</h2>
      <p className="hint">
        A blank on the item inherits from its catalog entry. A value set on the item overrides it.
      </p>
      <div className="scroll">
        <table className="narrow">
          <caption className="visually-hidden">Values in force, each with its source</caption>
          <thead>
            <tr>
              <th scope="col">Field</th>
              <th scope="col">Value in force</th>
              <th scope="col">Source</th>
            </tr>
          </thead>
          <tbody>
            {INHERITED.map(([field, label]) => {
              const effective = item.effective[field];
              const inherited = isInherited(effective);
              return (
                <tr key={field} data-field={field} data-source={effective.source}>
                  <th scope="row">{label}</th>
                  <td
                    className={inherited ? "inherited" : undefined}
                    title={sourceHint(effective) || undefined}
                  >
                    {effectiveText(effective) || <Dash />}
                  </td>
                  <td className={inherited ? "inherited" : undefined}>
                    {sourceLabel(effective)}
                    <span className="visually-hidden"> ({effective.source})</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

interface LifecycleProps {
  item: Item;
  rules: readonly Rule[];
  choices: readonly Choice[] | undefined;
  mayEdit: boolean;
  mayForce: boolean;
  onChanged: (text: string) => void;
  onReload: () => void;
}

/** The item's standing, and the two ways to change it: a move, and an edit within a state. */
function Lifecycle(props: LifecycleProps) {
  const { item, rules, choices, mayEdit } = props;
  const standing = standingOf(item);
  const lighter = standing.inherited ? "inherited" : undefined;
  const allowed = dispositionsIn(rules, item.lifecycle_state, item.disposition);
  const withinState = useMemo<FieldSpec[]>(
    () => [
      {
        name: "disposition",
        label: "Disposition",
        kind: "choice",
        blank: "None",
        options: DISPOSITIONS.map((name) => ({ value: name, label: name })),
      },
      // An item with a state is expected online or it is not: there is no blank to choose.
      { name: "expected_online", label: "Expected online", kind: "tristate" },
    ],
    [],
  );
  const hint =
    allowed.length > 0
      ? `An item in ${item.lifecycle_state} is ${allowed.join(" or ")}.`
      : `An item in ${item.lifecycle_state} carries no disposition.`;

  return (
    <section aria-labelledby="lifecycle">
      <h2 id="lifecycle">Lifecycle</h2>
      {/* The standing in force. For a minor item with no state of its own it is that of
          the item above it, shown lighter, and the page says whose it is. */}
      <dl
        className="facts"
        data-testid="standing"
        data-source={item.effective.lifecycle_state.source}
      >
        <dt>State</dt>
        <dd data-testid="state" className={lighter}>
          {standing.state ?? <Dash />}
        </dd>
        <dt>Disposition</dt>
        <dd data-testid="disposition" className={lighter}>
          {standing.disposition ?? <Dash />}
        </dd>
        <dt>Intent</dt>
        <dd data-testid="intent" className={lighter}>
          {onlineText(standing.online) || <Dash />}
        </dd>
        <dt>Reason</dt>
        <dd>{choiceLabel(choices, "state_reason", item.state_reason) || <Dash />}</dd>
        <dt>Since</dt>
        <dd>
          <Time at={item.state_changed_at} />
        </dd>
      </dl>
      {!item.is_major && !item.lifecycle_state && (
        <p data-testid="standing-inherited">
          {standing.inherited && standing.sourceHid ? (
            <>
              This minor item has no state of its own. Its state, disposition and intent are those
              of{" "}
              <Link to={`/items/${encodeURIComponent(standing.sourceHid)}`}>
                {standing.sourceHid === item.parent?.hid
                  ? itemName(item.parent)
                  : "the nearest item above it that has a state"}
              </Link>
              , taken together, and follow it. Moving it to a state gives it a standing of its own.
            </>
          ) : (
            "This minor item has no state of its own, and no item above it has one either."
          )}
        </p>
      )}
      {mayEdit && mayInheritAgain(item) && (
        <InheritAgain item={item} onChanged={props.onChanged} onReload={props.onReload} />
      )}
      {mayEdit && <Transition {...props} />}
      {mayEdit && item.lifecycle_state && (
        <section aria-labelledby="standing-form" className="panel">
          <h3 id="standing-form">Change the disposition or the intent</h3>
          <p className="hint">
            Within a state this is an ordinary change. {hint} The state itself is changed by a move.
          </p>
          <EditForm<Item, Schemas["ItemPatch"]>
            specs={withinState}
            record={item}
            save={(body) =>
              api.request("patch", "/api/v1/items/{hid}", { path: { hid: item.hid }, body })
            }
            onSaved={() => props.onChanged("The item's standing was changed.")}
            onReload={props.onReload}
            submitLabel="Save standing"
          />
        </section>
      )}
    </section>
  );
}

/**
 * Return a minor item that has a state of its own to the standing of the item it is in.
 * It is a move to no state, recorded like any other.
 */
function InheritAgain({
  item,
  onChanged,
  onReload,
}: Pick<LifecycleProps, "item" | "onChanged" | "onReload">) {
  const action = useAction();
  const above = item.parent ? itemName(item.parent) : "the item it is in";

  async function inherit() {
    const result = await action.run(() =>
      api.request("post", "/api/v1/items/{hid}/transition", {
        path: { hid: item.hid },
        body: { row_version: item.row_version, to: null },
      }),
    );
    if (result.ok) onChanged(`The item has the standing of ${above} again.`);
  }

  return (
    <section aria-labelledby="inherit-again" className="panel">
      <h3 id="inherit-again">A state of its own</h3>
      <Problem error={action.error} onReload={onReload} />
      <p>
        This minor item has a state of its own, so it no longer follows {above}. Returning it gives
        up its own state, disposition and intent together. The move is in the history like any
        other.
      </p>
      <p className="actions">
        <button type="button" onClick={inherit} disabled={action.busy}>
          Return to the standing of {above}
        </button>
      </p>
    </section>
  );
}

/** Move an item to another state, recording who, when, from, to and why. */
function Transition({ item, rules, choices, mayForce, onChanged, onReload }: LifecycleProps) {
  const [force, setForce] = useState(false);
  const [to, setTo] = useState("");
  const [reason, setReason] = useState("");
  const [disposition, setDisposition] = useState("");
  const [online, setOnline] = useState("");
  const action = useAction();
  const targets = nextStates(rules, item.lifecycle_state, force);
  const target = targets.includes(to) ? to : "";
  const reasons = choiceOptions(choices, "state_reason");
  const dispositions = dispositionsIn(rules, target, item.disposition);
  const known = ["to", "reason", "disposition", "expected_online", "force"];
  const refused = fieldErrors(action.error, known).shown;

  async function submit(event: FormEvent) {
    event.preventDefault();
    // What is left as the rules have it is not sent, so that the rules decide it.
    const body: Schemas["Transition"] = { row_version: item.row_version, to: target };
    if (reason) body.reason = reason;
    if (disposition && dispositions.includes(disposition)) body.disposition = disposition;
    if (online) body.expected_online = online === "true";
    if (force) body.force = true;
    const result = await action.run(() =>
      api.request("post", "/api/v1/items/{hid}/transition", { path: { hid: item.hid }, body }),
    );
    if (result.ok) onChanged(`The item was moved to ${target}.`);
  }

  return (
    <section aria-labelledby="move" className="panel">
      <h3 id="move">Move to another state</h3>
      {targets.length === 0 ? (
        <p>
          An item in {item.lifecycle_state} does not move on.
          {mayForce ? " An Admin may force a move." : ""}
        </p>
      ) : (
        !item.lifecycle_state && (
          <p className="hint">
            {item.is_major
              ? "An item with no state may be given any."
              : "A minor item with no state of its own may be given any."}
          </p>
        )
      )}
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={known} onReload={onReload} />
        <div className="fields">
          <SelectField
            label="Move to"
            name="to"
            value={target}
            onChange={setTo}
            required
            error={refused.to}
            disabled={targets.length === 0}
          >
            <option value="">Choose a state</option>
            {targets.map((state) => (
              <option key={state} value={state}>
                {state}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="Reason"
            name="reason"
            value={reason}
            onChange={setReason}
            required={force}
            error={refused.reason}
            hint={force ? "A forced move needs a reason" : "Optional"}
          >
            <option value="">No reason given</option>
            {reasons.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="Disposition"
            name="disposition"
            value={dispositions.includes(disposition) ? disposition : ""}
            onChange={setDisposition}
            error={refused.disposition}
            disabled={target === "" || dispositions.length === 0}
            hint={
              target !== "" && dispositions.length === 0
                ? `An item in ${target} carries none`
                : "Optional"
            }
          >
            <option value="">As the rules set it</option>
            {dispositions.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="Expected online"
            name="expected_online"
            value={online}
            onChange={setOnline}
            error={refused.expected_online}
            hint={
              target !== "" && !mayBeOnline(rules, target)
                ? `An item in ${target} is not expected online`
                : "Optional"
            }
          >
            <option value="">As the rules set it</option>
            <option value="true">Yes</option>
            <option value="false">No</option>
          </SelectField>
        </div>
        {mayForce && item.lifecycle_state && (
          <CheckField
            label="Force a move the rules do not list"
            name="force"
            checked={force}
            onChange={setForce}
            hint="For an Admin, with a reason. The move is marked as forced in the history."
            error={refused.force}
          />
        )}
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || target === ""}>
            Move
          </button>
        </p>
      </form>
    </section>
  );
}

interface DetailsProps {
  item: Item;
  onSaved: () => void;
  onReload: () => void;
}

/** The form for everything about an item but its state. Only what was changed is sent. */
function Details({ item, onSaved, onReload }: DetailsProps) {
  const entries = useEntryOptions();
  const owners = useOwnerOptions();
  const tags = useTags();
  const specs = useMemo<FieldSpec[]>(() => {
    const { catalog, owner } = item;
    const minor = !item.is_major;
    // The owners to choose from, the item's own among them as the item names it, also
    // when the list no longer brings it. One outside the team says so, with its reason.
    const offered = withCurrent(
      owners.data,
      owner && ownerOption({ ...owner, exception_reason: item.owner_exception_reason }),
    );
    return [
      {
        name: "catalog_entry_hid",
        label: "Catalog entry",
        kind: "choice",
        blank: "No catalog entry",
        options: withCurrent(
          entries.data,
          catalog && { value: catalog.hid, label: catalog.pid, group: catalog.vendor },
        ),
        heading: "Identity",
      },
      { name: "serial_number", label: "Serial number", kind: "text", maxLength: 100 },
      { name: "asset_tag", label: "Asset tag", kind: "text", maxLength: 100 },
      {
        name: "name",
        label: "Name",
        kind: "text",
        maxLength: 200,
        hint: "Left blank, the hostname is shown",
      },
      { name: "hostname", label: "Hostname", kind: "text", maxLength: 255 },
      { name: "fqdn", label: "FQDN", kind: "text", maxLength: 255 },
      {
        name: "mac_address",
        label: "MAC address",
        kind: "text",
        maxLength: 40,
        hint: "In any common notation",
      },
      { name: "quantity", label: "Quantity", kind: "integer", hint: "Seats or licences" },
      {
        name: "owner_hid",
        label: "Owner",
        kind: "choice",
        blank: minor ? "The owner of the item it is in" : "No owner",
        options: offered,
      },
      {
        name: "operator_hid",
        label: "Operator",
        kind: "operator",
        blank: "None of its own",
        options: item.operator
          ? [{ value: item.operator.hid, label: operatorOptionLabel(item.operator) }]
          : [],
      },
      {
        name: "location_hid",
        label: "Location",
        kind: "location",
        blank: minor ? "Where the item it is in is" : "No location",
        options: item.location ? [{ value: item.location.hid, label: item.location.path }] : [],
      },
      {
        name: "record_status",
        label: "Record status",
        kind: "choice",
        options: SETTABLE_STATUSES,
        hint: "A draft is left out of counts and default views",
      },
      { name: "description", label: "Description", kind: "longtext", maxLength: 10000 },
      { name: "comments", label: "Comments", kind: "longtext", maxLength: 10000 },
      {
        name: "tags",
        label: "Tags",
        kind: "set",
        // Every tag there is, and any the item carries that the list did not bring.
        options: [...new Set([...(tags.data ?? []).map((tag) => tag.label), ...item.tags])].map(
          (label) => ({ value: label, label }),
        ),
        hint: "A tag is made under Admin, then used here",
      },
      { name: "procured_on", label: "Procured on", kind: "date", heading: "Dates" },
      { name: "delivered_on", label: "Delivered on", kind: "date" },
      { name: "in_service_on", label: "In service on", kind: "date" },
      { name: "warranty_start", label: "Warranty start", kind: "date" },
      { name: "warranty_end", label: "Warranty end", kind: "date" },
      {
        name: "est_value",
        label: "Estimated value",
        kind: "decimal",
        places: 2,
        heading: "Overrides of what the catalog entry says",
      },
      { name: "support_weight", label: "Support weight", kind: "decimal", places: 2 },
      { name: "annual_support_cost", label: "Annual support cost", kind: "decimal", places: 2 },
      { name: "end_of_sale", label: "End of sale", kind: "date" },
      { name: "end_of_sw_support", label: "End of software support", kind: "date" },
      { name: "end_of_hw_support", label: "End of hardware support", kind: "date" },
      { name: "ldos", label: "Last day of support (LDoS)", kind: "date" },
    ];
  }, [item, entries.data, owners.data, tags.data]);

  // Under each field that inherits: what a blank shows, or that it is set here.
  const hints: Record<string, string> = {};
  if (!item.is_major) {
    const inForce = item.effective.owner_hid;
    hints.owner_hid = item.owner_hid
      ? "Set here. Choose the blank to have the owner of the item it is in again."
      : inForce.value === null
        ? "Blank, and no item above it has an owner."
        : `Blank has ${effectiveLabel(inForce)}, the owner of the item it is in.`;
    const where = item.effective.location_hid;
    hints.location_hid = item.location_hid
      ? "Set here. Clear it to be where the item it is in is again."
      : where.value === null
        ? "None, and no item above it has a location."
        : `None of its own: it is in ${effectiveLabel(where)}, where the item it is in is.`;
  }
  for (const [field] of INHERITED) {
    hints[field] = inheritHint(
      item[field],
      item.effective[field].source === "own" ? null : item.effective[field],
    );
  }
  // The operator: with one of its own the form says how to give it up; with none it
  // shows the one in force from above, read-only, before anybody is chosen.
  if (item.operator_hid) {
    hints.operator_hid =
      "The label of who of the team looks after it. Set here: clear it to have the operator from above again, if there is one.";
  } else {
    hints.operator_hid = "The label of who of the team looks after it.";
  }
  const notes = item.operator_hid
    ? undefined
    : {
        operator_hid: <OperatorNote effective={item.effective.operator_hid} what="item" />,
      };
  const ready = !entries.loading && !owners.loading && !tags.loading;

  return (
    <section aria-labelledby="details">
      <h2 id="details">Details</h2>
      <Problem error={entries.error ?? owners.error ?? tags.error} />
      {!ready && <p role="status">Loading…</p>}
      {ready && (
        <EditForm<Item, Schemas["ItemPatch"]>
          specs={specs}
          record={item}
          hints={hints}
          {...(notes ? { notes } : {})}
          save={(body) =>
            api.request("patch", "/api/v1/items/{hid}", { path: { hid: item.hid }, body })
          }
          onSaved={onSaved}
          onReload={onReload}
        />
      )}
    </section>
  );
}

interface RecordStatusProps {
  item: Item;
  onChanged: (text: string) => void;
  onReload: () => void;
}

/** Retire an item, or bring a retired one back. Nothing is ever deleted. */
function RecordStatus({ item, onChanged, onReload }: RecordStatusProps) {
  const action = useAction();
  const name = itemName(item);

  async function retire() {
    const result = await action.run(() =>
      api.request("post", "/api/v1/items/{hid}/retire", {
        path: { hid: item.hid },
        body: { row_version: item.row_version },
      }),
    );
    if (result.ok) onChanged("The item was retired.");
  }

  /** Bring the item back: as it was, or with another location, or none, in the same change. */
  async function bringBack(location?: string | null) {
    const result = await action.run(() =>
      api.request("patch", "/api/v1/items/{hid}", {
        path: { hid: item.hid },
        body: {
          row_version: item.row_version,
          record_status: "active",
          ...(location === undefined ? {} : { location_hid: location }),
        },
      }),
    );
    if (result.ok) onChanged("The item is active again.");
  }

  return (
    <section aria-labelledby="retire">
      <h2 id="retire">{item.record_status === "retired" ? "Retired" : "Retire"}</h2>
      <Problem error={action.error} onReload={onReload} labels={{ record_status: "" }} />
      {item.record_status === "retired" ? (
        <>
          <p>
            This item is retired. It is left out of counts and default views, and its record and
            history are kept.
          </p>
          <p className="actions">
            <button type="button" onClick={() => bringBack()} disabled={action.busy}>
              Bring back as active
            </button>
          </p>
          {refusedForItsPlace(action.error) && (
            <BringBackElsewhere
              what="item"
              blank={item.is_major ? "No location" : "Where the item it is in is"}
              busy={action.busy}
              onBringBack={bringBack}
            />
          )}
        </>
      ) : (
        <>
          <p>
            A retired item is left out of counts and default views. Its record and history are kept,
            and it can be brought back.
          </p>
          <p className="actions">
            <ConfirmButton
              label="Retire item"
              title={`Retire ${name}?`}
              confirmLabel="Retire item"
              onConfirm={retire}
              disabled={action.busy}
            >
              <p>The item stays in the inventory and can be brought back.</p>
              {item.groups.length > 0 && (
                <p>
                  Its {item.groups.length === 1 ? "membership" : "memberships"} of{" "}
                  {item.groups.map((group) => group.name).join(", ")} end
                  {item.groups.length === 1 ? "s" : ""} today, and stay
                  {item.groups.length === 1 ? "s" : ""} on record with that day.
                </p>
              )}
            </ConfirmButton>
          </p>
        </>
      )}
    </section>
  );
}

/** Every change made to the item, newest first: who, when, what was and what is. */
function History({ item }: { item: Item }) {
  const [offset, setOffset] = useState(0);
  // The version is part of the key, so the history is read again after every change.
  const history = useLoad(`history ${item.hid} ${item.row_version} ${offset}`, (signal) =>
    api.request("get", "/api/v1/items/{hid}/history", {
      path: { hid: item.hid },
      query: { limit: HISTORY_PAGE, offset },
      signal,
    }),
  );
  const events = history.data?.items ?? [];

  return (
    <section aria-labelledby="history">
      <h2 id="history">History</h2>
      <Problem error={history.error} />
      {history.loading && !history.data && <p role="status">Loading…</p>}
      {history.data && (
        <>
          <div className="scroll">
            <table className="history">
              <caption className="visually-hidden">Changes to this item, newest first</caption>
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Who</th>
                  <th scope="col">Action</th>
                  <th scope="col">Field</th>
                  <th scope="col">Was</th>
                  <th scope="col">Is</th>
                </tr>
              </thead>
              {events.map((event) => {
                const changes = event.changes.length > 0 ? event.changes : [{}];
                return (
                  <tbody key={event.hid} data-action={event.action}>
                    {changes.map((change, place) => {
                      const field = typeof change.field === "string" ? change.field : "";
                      return (
                        <tr key={`${event.hid} ${field || place}`}>
                          {place === 0 && (
                            <>
                              <td className="nowrap" rowSpan={changes.length}>
                                <Time at={event.at} />
                              </td>
                              <td rowSpan={changes.length}>{event.actor_name ?? <Dash />}</td>
                              <td rowSpan={changes.length}>{event.action}</td>
                            </>
                          )}
                          <td>{field}</td>
                          <td>{field && formatValue(change.old)}</td>
                          <td>{field && formatValue(change.new)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                );
              })}
              {events.length === 0 && (
                <tbody>
                  <tr>
                    <td colSpan={6} className="muted">
                      There are no changes on record.
                    </td>
                  </tr>
                </tbody>
              )}
            </table>
          </div>
          <Pager
            total={history.data.total}
            limit={HISTORY_PAGE}
            offset={offset}
            noun="events"
            onChange={setOffset}
          />
        </>
      )}
    </section>
  );
}
