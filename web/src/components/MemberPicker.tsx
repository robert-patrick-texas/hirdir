import { useState } from "react";
import type { Schemas } from "../api";
import { itemName } from "../lib/format";
import {
  defaultRole,
  groupTypeLabel,
  nextPosition,
  type PendingMember,
  roleLabel,
  roleOptions,
} from "../lib/groups";
import { MAJOR_ONLY } from "../lib/pick";
import { nextSort, type SortColumns, type SortState, sortRows } from "../lib/sort";
import type { SortControl } from "../lib/useSorting";
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
  /** What is wrong with a row, by the HID of its item. */
  errors?: Readonly<Record<string, string>>;
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
  const { type, pending, onChange, taken = [], positions = [], errors = {}, disabled } = props;
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

  function add(item: Item) {
    const used = [...positions, ...pending.map((row) => Number(row.position) || null)];
    onChange([
      ...pending,
      {
        item_hid: item.hid,
        name: itemName(item),
        role: defaultRole(type),
        position: numbered ? String(nextPosition(used)) : "",
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
        taken={[...taken, ...pending.map((row) => row.item_hid)]}
        onPick={add}
        {...(disabled === undefined ? {} : { disabled })}
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
                      <span className="field-error"> {errors[row.item_hid]}</span>
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
    </div>
  );
}
