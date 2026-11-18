import { useState } from "react";
import { Link } from "react-router";
import type { Schemas } from "../api";
import { itemName } from "../lib/format";
import {
  defaultRole,
  groupTypeLabel,
  type PendingMember,
  roleLabel,
  roleOptions,
} from "../lib/groups";
import { dispositionsIn, intentChoices, type Rule } from "../lib/lifecycle";
import { MAJOR_ONLY, memberOffer, SPARES } from "../lib/pick";
import { nextSort, type SortColumns, type SortState, sortRows } from "../lib/sort";
import { dropsText, type Joining, joinStanding, offeredPosition } from "../lib/stacks";
import type { SortControl } from "../lib/useSorting";
import { CheckField, SelectField } from "./Field";
import { ItemPicker } from "./ItemPicker";
import { SortTh } from "./SortTh";

type Item = Schemas["ItemOut"];

interface MemberPickerProps {
  /** The type of the group: it says which roles there are. */
  type: string;
  /** The items chosen so far, with the role and position of each. */
  pending: readonly PendingMember[];
  onChange: (pending: PendingMember[]) => void;
  /** Items that are members already, and so are not offered. */
  taken?: readonly string[];
  /** The positions that are taken already, to offer the next one. */
  positions?: ReadonlyArray<number | null>;
  /**
   * 0.9.6: the position the server offers the next member, the stack's `next_position`:
   * the lowest that no current member holds (P-219). Left out, the lowest free from 1.
   */
  next?: number | null;
  /** What is wrong with a row, by the HID of its item. */
  errors?: Readonly<Record<string, string>>;
  /** The member that holds the position a row was refused, as a link, by the HID of its item (P-219). */
  holders?: Readonly<Record<string, { to: string; label: string }>>;
  /**
   * 0.9.6: the members join a stack, by Add members, and 0.9.8 by New group (P-244): each
   * has the box of the stack's name and place (P-217), shown where the type is a stack.
   * The lifecycle rules say what a spare is offered.
   */
  joins?: boolean;
  rules?: readonly Rule[];
  disabled?: boolean;
}

// What the table of the items to add is sorted by: each column by what its cell shows.
const COLUMNS: SortColumns<PendingMember> = {
  item: (row) => row.name,
  role: (row) => roleLabel(row.role),
  position: (row) => row.position,
};

/**
 * The order the rows are shown in: the one a press on a header made, by the HIDs of the
 * items. It is made at the press and then left alone, so that a row does not move away
 * from under the cursor while its role or its position is being changed. A row that is
 * not in it, one added since, comes after the others.
 */
interface Shown {
  state: SortState | null;
  order: readonly string[];
}

function inOrder(pending: readonly PendingMember[], order: readonly string[]): PendingMember[] {
  const place = new Map(order.map((hid, index) => [hid, index]));
  const at = (row: PendingMember) => place.get(row.item_hid) ?? place.size;
  return [...pending].sort((one, other) => at(one) - at(other));
}

/**
 * Choose several items to become members of a group together, each with its role and
 * position. Nothing is sent from here: the form around it sends them all in one
 * request, so that the group is checked once they are all in. The table is sorted by its
 * headers; that changes the order on show only, not the order the members are sent in.
 */
export function MemberPicker(props: MemberPickerProps) {
  const {
    type,
    pending,
    onChange,
    taken = [],
    positions = [],
    next: nextFree,
    errors = {},
    disabled,
  } = props;
  const { holders = {}, rules = [], joins = false } = props;
  const roles = roleOptions(type);
  const numbered = type === "stack";
  // The members of a stack and of a cluster are major items.
  const majorOnly = type === "stack" || type === "cluster";
  const [shown, setShown] = useState<Shown>({ state: null, order: [] });
  const rows = inOrder(pending, shown.order);
  // A header says that the table is sorted by it only while that is so: not after a
  // change to a row, or another row, has left the rows in another order.
  const still = sortRows(rows, COLUMNS, shown.state).every((row, index) => row === rows[index]);
  const state = still ? shown.state : null;
  const sorting: SortControl = {
    state,
    by: (column) => {
      const next = nextSort(state, column);
      const order = sortRows(pending, COLUMNS, next).map((row) => row.item_hid);
      setShown({ state: next, order });
    },
    enabled: true,
  };

  const waiting = joins && rules.length === 0;

  function add(item: Item) {
    const used = [...positions, ...pending.map((row) => Number(row.position) || null)];
    onChange([
      ...pending,
      {
        item_hid: item.hid,
        name: itemName(item),
        role: defaultRole(type),
        position: numbered ? String(offeredPosition(nextFree, used)) : "",
        // 0.9.6: a switch that joins a stack takes its name and place, ticked from the
        // start, and a spare is offered Production and expected online (P-217).
        // 0.9.8: New group keeps it for any type, and shows the box for a stack (P-244).
        ...(joins ? joining(item, rules) : {}),
      },
    ]);
  }

  function set(hid: string, change: Partial<PendingMember>) {
    onChange(pending.map((row) => (row.item_hid === hid ? { ...row, ...change } : row)));
  }

  return (
    <div className="member-picker">
      <ItemPicker
        label="Find an item to add"
        hint={
          majorOnly
            ? `Type a part of its name, serial number or asset tag. The members of a ${groupTypeLabel(type).toLowerCase()} are major items.`
            : "Type a part of its name, serial number or asset tag."
        }
        only={majorOnly ? MAJOR_ONLY : null}
        // 0.9.6: the spares first, each with where it stands (P-221).
        first={SPARES}
        standing={(item) => memberOffer(item, type)}
        taken={[...taken, ...pending.map((row) => row.item_hid)]}
        onPick={add}
        // A switch picked before the lifecycle rules are read would not be offered
        // Production, and would join as the spare it was: the picker waits for them.
        {...(waiting ? { disabled: true } : disabled === undefined ? {} : { disabled })}
      />
      {pending.length > 0 && (
        <div className="scroll">
          <table className="narrow" data-testid="pending-members">
            <caption className="visually-hidden">The items to add, each with its role</caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="item">
                  Item
                </SortTh>
                <SortTh sort={sorting} column="role">
                  Role
                </SortTh>
                <SortTh sort={sorting} column="position">
                  Position
                </SortTh>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.item_hid} data-item={row.item_hid}>
                  <th scope="row">
                    {row.name}
                    {errors[row.item_hid] && (
                      <span className="field-error" data-testid="member-error">
                        {" "}
                        {errors[row.item_hid]}
                        {holders[row.item_hid] && (
                          <>
                            {" "}
                            It is held by{" "}
                            <Link to={holders[row.item_hid]?.to ?? ""}>
                              {holders[row.item_hid]?.label}
                            </Link>
                            .
                          </>
                        )}
                      </span>
                    )}
                  </th>
                  <td>
                    <select
                      aria-label={`Role of ${row.name}`}
                      value={row.role}
                      disabled={disabled}
                      onChange={(event) => set(row.item_hid, { role: event.target.value })}
                    >
                      {roles.map((role) => (
                        <option key={role.value} value={role.value}>
                          {role.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      type="text"
                      className="short"
                      inputMode="numeric"
                      autoComplete="off"
                      aria-label={`Position of ${row.name}`}
                      aria-invalid={errors[row.item_hid] ? true : undefined}
                      value={row.position}
                      disabled={disabled}
                      onChange={(event) => set(row.item_hid, { position: event.target.value })}
                    />
                  </td>
                  <td className="row-actions">
                    <button
                      type="button"
                      disabled={disabled}
                      aria-label={`Do not add ${row.name}`}
                      onClick={() =>
                        onChange(pending.filter((one) => one.item_hid !== row.item_hid))
                      }
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {numbered &&
        joins &&
        rows.map((row) => (
          <JoinBox
            key={row.item_hid}
            row={row}
            rules={rules}
            onChange={(change) => set(row.item_hid, change)}
            {...(disabled === undefined ? {} : { disabled })}
          />
        ))}
    </div>
  );
}

/** What of an item chosen for a stack the box needs, and what it is offered from the start. */
export function joining(item: Item, rules: readonly Rule[]): Partial<PendingMember> {
  const has: Joining = {
    hostname: item.hostname,
    fqdn: item.fqdn,
    addresses: item.addresses,
    location: item.location,
    lifecycle_state: item.lifecycle_state,
    disposition: item.disposition,
  };
  const state = item.lifecycle_state;
  const standing = joinStanding(
    has,
    dispositionsIn(rules, state, item.disposition),
    intentChoices(rules, state, "Production"),
  );
  return { joining: has, drop: true, ...standing };
}

interface JoinBoxProps {
  row: PendingMember;
  rules: readonly Rule[];
  onChange: (change: Partial<PendingMember>) => void;
  disabled?: boolean;
}

/**
 * Under the members chosen for a stack, for each: the box, ticked from the start, "It
 * takes the stack's name and place", with the line of exactly what it removes from this
 * switch, read from the switch as it was chosen; and for a spare, the disposition and the
 * intent it is given, as the rule of its state allows. Unticked, nothing of it is sent.
 */
export function JoinBox({ row, rules, onChange, disabled }: JoinBoxProps) {
  const has = row.joining ?? {};
  const state = has.lifecycle_state;
  const kept = has.disposition ?? null;
  const drop = row.drop === true;
  const dispositions = dispositionsIn(rules, state, kept);
  const disposition = row.disposition ?? "";
  const intents = intentChoices(rules, state, disposition || kept);
  const spare = kept === "Spare";
  return (
    <fieldset className="plain join-box" data-testid="join-box" data-item={row.item_hid}>
      <legend>{row.name}</legend>
      <CheckField
        label="It takes the stack's name and place"
        name={`drop-${row.item_hid}`}
        checked={drop}
        disabled={disabled}
        onChange={(on) => onChange({ drop: on })}
      />
      <p className="hint" data-testid="drops">
        {drop
          ? dropsText(row.name, has)
          : `${row.name} keeps its own name, addresses and place: nothing of it is changed.`}
      </p>
      {drop && spare && (
        <div className="fields">
          <SelectField
            label="Disposition"
            name={`disposition-${row.item_hid}`}
            value={disposition}
            disabled={disabled}
            onChange={(value) => onChange({ disposition: value })}
            hint="A spare that joins a stack is in production."
          >
            <option value="">As it is ({kept})</option>
            {dispositions.map((one) => (
              <option key={one} value={one}>
                {one}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="Expected online"
            name={`online-${row.item_hid}`}
            value={row.online ?? ""}
            disabled={disabled}
            onChange={(value) => onChange({ online: value })}
          >
            <option value="">As it is</option>
            {intents.map((one) => (
              <option key={String(one)} value={String(one)}>
                {one ? "Yes" : "No"}
              </option>
            ))}
          </SelectField>
        </div>
      )}
    </fieldset>
  );
}
