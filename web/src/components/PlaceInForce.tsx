// What a place has in force, and how each thing stands: inherited from a level above,
// the place's own, or the place's own where a level above has one too, which is an
// override. The server says all of it in `GET …/effective`: the source of each thing and
// the level it overrides. This only shows it, so that it is seen at a glance: what is
// inherited is lighter and marked "Inherited", an override is marked "Overrides", each
// with the level as a link. The marks are words, never a colour alone.

import type { ReactNode } from "react";
import { Link } from "react-router";
import { api } from "../api";
import type { Loaded, useAction } from "../lib/hooks";
import { markOf } from "../lib/operators";
import { optionLabel, RECORD_STATUSES } from "../lib/options";
import {
  addressLines,
  clearedShipAddress,
  contactLine,
  type Level,
  noContactText,
  overriddenLevel,
  type Place,
  type PlaceEffective,
  type RoleContacts,
  type Standing,
  standingOf,
} from "../lib/places";
import type { SortColumns } from "../lib/sort";
import { useSorting } from "../lib/useSorting";
import { OperatorMark } from "./Operator";
import { Problem } from "./Problem";
import { SortTh } from "./SortTh";

/** The address of the page of a place, with the view of the tree kept. */
export type To = (level: string, hid: string) => { pathname: string; search: string };

type InForceValue = Pick<
  PlaceEffective["ship_instructions"],
  "source" | "source_hid" | "source_path" | "overrides_hid" | "overrides_path"
>;

function Dash() {
  return <span className="muted">—</span>;
}

interface StandsProps {
  /** One thing in force, as the server says where it came from and what it overrides. */
  value: InForceValue;
  /** The path of the site of the place, when the place is a location. */
  sitePath: string | null;
  level: Level;
  to: To;
  /** More to say after the level, as that the address is a street address. */
  children?: ReactNode;
}

/**
 * How one thing in force stands, in words: inherited from a level, which is named and
 * linked; the place's own; or the place's own overriding a level, which is named and
 * linked too.
 */
export function Stands({ value, sitePath, level, to, children }: StandsProps) {
  const standing = standingOf(value);
  if (standing === "none") return <span className="muted">Not set</span>;
  if (standing === "inherited") {
    return (
      <span data-standing="inherited">
        <span className="badge badge-plain mark">Inherited</span> from the {value.source}{" "}
        {value.source_hid ? (
          <Link to={to(value.source, value.source_hid)}>
            {value.source_path ?? value.source_hid}
          </Link>
        ) : (
          (value.source_path ?? "")
        )}
        {children}
      </span>
    );
  }
  if (standing === "override" && value.overrides_hid) {
    const above = value.overrides_path ?? value.overrides_hid;
    return (
      <span data-standing="override">
        Set here <span className="badge mark">Overrides</span>{" "}
        <Link to={to(overriddenLevel(level, sitePath, above), value.overrides_hid)}>{above}</Link>
        {children}
      </span>
    );
  }
  return (
    <span data-standing="own">
      Set here
      {children}
    </span>
  );
}

/** How one thing in force stands, as the words `Stands` shows: nothing when it is not set. */
function standsText(value: InForceValue): string {
  const standing = standingOf(value);
  if (standing === "none") return "";
  if (standing === "inherited") {
    return `Inherited from the ${value.source} ${value.source_path ?? value.source_hid ?? ""}`;
  }
  if (standing === "override" && value.overrides_hid) {
    return `Set here Overrides ${value.overrides_path ?? value.overrides_hid}`;
  }
  return "Set here";
}

// What the table of contacts in force is sorted by: the role, the contacts as the cell
// lists them, and the level they came from. A role with nobody in it comes last.
const CONTACT_COLUMNS: SortColumns<RoleContacts> = {
  role: (role) => role.label,
  contacts: (role) => role.contacts.map(contactLine).join(", "),
  from: standsText,
};

/** The class of what is shown lighter: what came from a level above. */
function lighter(standing: Standing): string | undefined {
  return standing === "inherited" ? "inherited" : undefined;
}

interface InForceProps {
  level: Level;
  place: Place;
  /** What the server says the place has in force. */
  effective: Loaded<PlaceEffective>;
  mayEdit: boolean;
  to: To;
  /** Give up the place's own value, so that the one from above is in force again. */
  onInheritAgain: (body: Record<string, unknown>, done: string) => Promise<void>;
  /** The refusal of that, and whether it is under way. */
  action: ReturnType<typeof useAction>;
  onReload: () => void;
}

/**
 * What the place has in force: the contacts of each role, and the shipping address and
 * instructions, each with how it stands. An override is given up with one button, which
 * puts what the level above has in force again.
 */
export function InForce(props: InForceProps) {
  const { level, place, effective, mayEdit, to, onInheritAgain, action, onReload } = props;
  const data = effective.data;
  const sitePath = "site" in place ? place.site.path : null;
  const stands = { sitePath, level, to };
  // The operator of what is at this place and has none from elsewhere.
  const operator = markOf(data?.operator.value);
  const sorting = useSorting(data?.contacts, CONTACT_COLUMNS);
  return (
    <section aria-labelledby="in-force">
      <h3 id="in-force">In force</h3>
      <p className="hint">
        What holds for this {level}: its own where it has any, and otherwise what the nearest level
        above it has. What is marked Inherited comes from the level named, and is shown lighter.
        What is marked Overrides is this {level}&apos;s own, in place of what that level has.
        Nothing is copied down, so a change above shows here at once.
      </p>
      <Problem error={effective.error} />
      <Problem error={action.error} onReload={onReload} />
      {effective.loading && !data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {data && (
        <>
          <div className="scroll">
            <table data-testid="in-force-contacts">
              <caption className="visually-hidden">
                The contacts in force for {place.path}, by role, each with the level it came from
              </caption>
              <thead>
                <tr>
                  <SortTh sort={sorting} column="role">
                    Role
                  </SortTh>
                  <SortTh sort={sorting} column="contacts">
                    Contacts
                  </SortTh>
                  <SortTh sort={sorting} column="from">
                    From
                  </SortTh>
                </tr>
              </thead>
              <tbody>
                {sorting.rows.map((role) => {
                  const standing = standingOf(role);
                  return (
                    <tr
                      key={role.role}
                      data-role={role.role}
                      data-source={role.source}
                      data-standing={standing}
                      data-stopped={role.stopped ? "true" : "false"}
                    >
                      <th scope="row">{role.label}</th>
                      <td className={lighter(standing)}>
                        {role.contacts.length > 0 ? (
                          <ul className="plain-list">
                            {role.contacts.map((contact) => (
                              <li key={contact.assignment_hid}>
                                <Link
                                  to={`/contacts/${encodeURIComponent(contact.contact_hid)}`}
                                  {...(standing === "inherited"
                                    ? { className: "link-inherited" }
                                    : {})}
                                >
                                  {contact.name}
                                </Link>
                                {contactLine({ ...contact, name: "" }) && (
                                  <span> · {contactLine({ ...contact, name: "" })}</span>
                                )}
                                {contact.record_status !== "active" && (
                                  <span className="badge">
                                    {optionLabel(RECORD_STATUSES, contact.record_status)}
                                  </span>
                                )}
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <span className="muted">{noContactText(role)}</span>
                        )}
                      </td>
                      <td className={lighter(standing)}>
                        <Stands value={role} {...stands} />
                      </td>
                    </tr>
                  );
                })}
                {data.contacts.length === 0 && (
                  <tr>
                    <td colSpan={3} className="muted">
                      The list of contact roles is empty.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <dl className="facts" data-testid="in-force-shipping">
            <dt>Operator</dt>
            <dd
              data-testid="place-operator"
              data-source={data.operator.source}
              data-standing={standingOf(data.operator)}
              className={lighter(standingOf(data.operator))}
            >
              {operator ? (
                <OperatorMark mark={operator} withPerson />
              ) : (
                <span className="muted">Nobody</span>
              )}
              {" · "}
              <Stands value={data.operator} {...stands} />
            </dd>
            <dt>Shipping address</dt>
            <dd
              data-testid="ship-address"
              data-source={data.ship_address.source}
              data-standing={standingOf(data.ship_address)}
              data-same-as-address={data.ship_address.same_as_address ? "true" : "false"}
              className={lighter(standingOf(data.ship_address))}
            >
              {addressLines(data.ship_address.value).join(", ") || <Dash />}
              {" · "}
              <Stands value={data.ship_address} {...stands}>
                {data.ship_address.same_as_address &&
                  (data.ship_address.source === "own"
                    ? ": it is the street address, by the tick"
                    : ", whose street address it is")}
              </Stands>
              {mayEdit && standingOf(data.ship_address) === "override" && (
                <button
                  type="button"
                  className="again"
                  disabled={action.busy}
                  onClick={() =>
                    onInheritAgain(
                      clearedShipAddress(level),
                      `${place.name} has the shipping address of ${data.ship_address.overrides_path} again.`,
                    )
                  }
                >
                  Use the address from {data.ship_address.overrides_path} again
                </button>
              )}
            </dd>
            <dt>Shipping instructions</dt>
            <dd
              data-testid="ship-instructions"
              data-source={data.ship_instructions.source}
              data-standing={standingOf(data.ship_instructions)}
              className={lighter(standingOf(data.ship_instructions))}
            >
              {data.ship_instructions.value || <Dash />}
              {" · "}
              <Stands value={data.ship_instructions} {...stands} />
              {mayEdit && standingOf(data.ship_instructions) === "override" && (
                <button
                  type="button"
                  className="again"
                  disabled={action.busy}
                  onClick={() =>
                    onInheritAgain(
                      { ship_instructions: null },
                      `${place.name} has the shipping instructions of ${data.ship_instructions.overrides_path} again.`,
                    )
                  }
                >
                  Use the instructions from {data.ship_instructions.overrides_path} again
                </button>
              )}
            </dd>
          </dl>
        </>
      )}
    </section>
  );
}

interface ShippingNoteProps {
  /** The shipping address in force for the place a form is of, or for the one a new place is made in. */
  address: PlaceEffective["ship_address"];
  /** The level of the place that address is in force for. */
  of: Level;
  /** The level of the place the form is of. */
  level: Level;
  sitePath: string | null;
  to: To;
  /** True in the form of a place that is still to be made: what is in force is what it would have. */
  beforeItExists?: boolean;
}

/**
 * What a form says above its shipping address inputs, so that the operator sees what
 * applies before typing: the address that is inherited, read-only, with the level it
 * comes from; or that the place has its own, and what that overrides.
 */
export function ShippingNote(props: ShippingNoteProps) {
  const { address, of, level, sitePath, to, beforeItExists } = props;
  const standing = beforeItExists && address.source !== "none" ? "inherited" : standingOf(address);
  const lines = addressLines(address.value).join(", ");
  const from = address.source_hid ? (
    <Link to={to(address.source === "own" ? of : address.source, address.source_hid)}>
      {address.source_path ?? address.source_hid}
    </Link>
  ) : (
    (address.source_path ?? "")
  );
  if (standing === "none") {
    return (
      <p className="form-note" data-testid="shipping-note" data-standing="none">
        No shipping address is in force: there is none above to inherit.
      </p>
    );
  }
  if (standing === "inherited") {
    return (
      <p className="form-note inherited" data-testid="shipping-note" data-standing="inherited">
        <span className="badge badge-plain mark">Inherited</span> {lines}.{" "}
        {beforeItExists ? "It will be inherited from " : "Inherited from "}
        {from}
        {address.same_as_address && ": the street address of that place"}.{" "}
        {level === "region"
          ? "Enter an address here to override it."
          : "Enter an address here, or tick the box, to override it."}
      </p>
    );
  }
  const above = address.overrides_path ?? address.overrides_hid;
  return (
    <p className="form-note" data-testid="shipping-note" data-standing={standing}>
      {address.same_as_address
        ? "Deliveries go to the street address of this place."
        : `This ${level} has a shipping address of its own.`}{" "}
      {standing === "override" && address.overrides_hid && above ? (
        <>
          <span className="badge mark">Overrides</span>{" "}
          <Link to={to(overriddenLevel(level, sitePath, above), address.overrides_hid)}>
            {above}
          </Link>
          , whose address is in force again when this one is cleared.
        </>
      ) : (
        "No level above has one."
      )}
    </p>
  );
}

/**
 * The same for the operator of a place that exists: the one it has from a level above,
 * shown before one is chosen, or that its own overrides the one above.
 */
export function PlaceOperatorNote(props: {
  operator: PlaceEffective["operator"];
  level: Level;
  sitePath: string | null;
  to: To;
}) {
  const { operator, level, sitePath, to } = props;
  const standing = standingOf(operator);
  const mark = markOf(operator.value);
  if (standing === "inherited" && operator.source_hid && mark) {
    return (
      <p
        className="form-note inherited"
        data-testid="place-operator-note"
        data-standing="inherited"
      >
        <span className="badge badge-plain mark">Inherited</span>{" "}
        <OperatorMark mark={mark} withPerson />. Inherited from{" "}
        <Link to={to(operator.source, operator.source_hid)}>
          {operator.source_path ?? operator.source_hid}
        </Link>
        . Choose an operator here to override it.
      </p>
    );
  }
  if (standing === "override" && operator.overrides_hid) {
    const above = operator.overrides_path ?? operator.overrides_hid;
    return (
      <p className="form-note" data-testid="place-operator-note" data-standing="override">
        This {level} has an operator of its own. <span className="badge mark">Overrides</span>{" "}
        <Link to={to(overriddenLevel(level, sitePath, above), operator.overrides_hid)}>
          {above}
        </Link>
        , whose operator is in force again when this one is cleared.
      </p>
    );
  }
  return null;
}

/** The same for the shipping instructions of a place that exists. */
export function InstructionsNote(props: {
  instructions: PlaceEffective["ship_instructions"];
  level: Level;
  sitePath: string | null;
  to: To;
}) {
  const { instructions, level, sitePath, to } = props;
  const standing = standingOf(instructions);
  if (standing === "inherited" && instructions.source_hid) {
    return (
      <p className="form-note inherited" data-testid="instructions-note" data-standing="inherited">
        <span className="badge badge-plain mark">Inherited</span> {instructions.value}. Inherited
        from{" "}
        <Link to={to(instructions.source, instructions.source_hid)}>
          {instructions.source_path ?? instructions.source_hid}
        </Link>
        . Enter instructions here to override them.
      </p>
    );
  }
  if (standing === "override" && instructions.overrides_hid) {
    const above = instructions.overrides_path ?? instructions.overrides_hid;
    return (
      <p className="form-note" data-testid="instructions-note" data-standing="override">
        This {level} has instructions of its own. <span className="badge mark">Overrides</span>{" "}
        <Link to={to(overriddenLevel(level, sitePath, above), instructions.overrides_hid)}>
          {above}
        </Link>
        , whose instructions are in force again when these are cleared.
      </p>
    );
  }
  return null;
}

/** Read what a place has in force. */
export function readEffective(
  level: Level,
  hid: string,
  signal: AbortSignal,
): Promise<PlaceEffective> {
  const options = { path: { hid }, signal };
  if (level === "region") return api.request("get", "/api/v1/regions/{hid}/effective", options);
  if (level === "site") return api.request("get", "/api/v1/sites/{hid}/effective", options);
  return api.request("get", "/api/v1/locations/{hid}/effective", options);
}
