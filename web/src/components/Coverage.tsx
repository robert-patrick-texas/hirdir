// Coverage: which items are under which contract, and for which days. It is shown and
// changed from three places: the page of a contract, as a grid of the items it covers;
// the page of an item, as the contracts that cover it; and the item grid, where the rows
// selected are put under a contract in one request. A coverage is ended with a date and
// is never removed.

import { type FormEvent, useMemo, useState } from "react";
import { Link } from "react-router";
import { api, type Schemas } from "../api";
import {
  CONTRACT_STATUSES,
  COVER_AT_ONCE,
  COVER_MOST,
  type Contract,
  type Coverage,
  contractLabel,
  contractPath,
  coverageDay,
  coverBatches,
  coverBody,
  endable,
  RENEWAL_PENDING,
  RENEWAL_PENDING_NOTE,
  renewalPending,
} from "../lib/contracts";
import { formatTime, itemName, plural, today } from "../lib/format";
import { queryBody } from "../lib/gridQuery";
import { useAction, useLoad } from "../lib/hooks";
import { EVERY } from "../lib/lists";
import { optionLabel, RECORD_STATUSES } from "../lib/options";
import { fieldErrors } from "../lib/problems";
import { dateValue } from "../lib/sort";
import { type Chosen, chosenCount, type GridView } from "../lib/transfer";
import { useSorting } from "../lib/useSorting";
import { ConfirmButton } from "./ConfirmButton";
import { ContractField } from "./ContractField";
import { TextField } from "./Field";
import type { GridColumn } from "./grid/columns";
import { DataGrid } from "./grid/DataGrid";
import { ItemPicker } from "./ItemPicker";
import { Notice, Problem } from "./Problem";
import { SortTh } from "./SortTh";

type Item = Schemas["ItemOut"];

/** What is said of a coverage that hirdir ended on the day its item left service. */
const LEFT_SERVICE_NOTE =
  "Ended on the day the item was retired, released or archived. The vendor still counts it until it has been told: say so here once it has.";

/** What is said before a coverage is removed outright. */
const REMOVE_NOTE =
  "Removing is for a coverage that was a mistake, as an item put under the wrong contract: it is gone, and the audit trail holds what it was. Cover that was true for a time is ended with a date instead, and stays on record.";

/** What the page says of the dates of a coverage, wherever they are asked for. */
const DATES_HINT =
  "Left blank, the coverage is for the contract's own period, whatever that becomes when the contract is renewed.";

interface DatesProps {
  starts: string;
  ends: string;
  onStarts: (value: string) => void;
  onEnds: (value: string) => void;
  errors: Readonly<Record<string, string>>;
  disabled: boolean;
}

function Dates({ starts, ends, onStarts, onEnds, errors, disabled }: DatesProps) {
  return (
    <>
      <TextField
        label="Covered from"
        name="starts_on"
        type="date"
        value={starts}
        onChange={onStarts}
        disabled={disabled}
        error={errors.starts_on}
        hint={DATES_HINT}
      />
      <TextField
        label="Covered until"
        name="ends_on"
        type="date"
        value={ends}
        onChange={onEnds}
        disabled={disabled}
        error={errors.ends_on}
      />
    </>
  );
}

interface EndCoverageProps {
  /** The coverages to end, as they were read: each goes with its own version. */
  coverages: readonly Coverage[];
  onEnded: (text: string) => void;
  onClose: () => void;
  /** Read the coverages again, as when one of them has changed since. */
  onReload: () => void;
}

/**
 * End coverage: give each coverage chosen its last day. Nothing is removed, so last
 * year's answer stays on record. Each coverage is one change of its own; the first that
 * is refused stops the rest, and the page says how many were ended.
 */
export function EndCoverage({ coverages, onEnded, onClose, onReload }: EndCoverageProps) {
  const [day, setDay] = useState(() => today());
  const [ended, setEnded] = useState(0);
  const action = useAction();
  const refused = fieldErrors(action.error, ["ends_on"]).shown;

  async function submit(event: FormEvent) {
    event.preventDefault();
    let count = 0;
    setEnded(0);
    const result = await action.run(async () => {
      for (const coverage of coverages) {
        await api.request("patch", "/api/v1/contracts/{hid}/coverage/{coverage_hid}", {
          path: { hid: coverage.contract_hid, coverage_hid: coverage.hid },
          body: { row_version: coverage.row_version, ends_on: day },
        });
        count += 1;
        setEnded(count);
      }
    });
    if (result.ok) {
      onEnded(
        `${plural(count, "coverage was", "coverages were")} ended on ${day}. Nothing was removed.`,
      );
    }
  }

  const [first] = coverages;
  const what =
    coverages.length === 1 && first
      ? `the coverage of ${itemName(first.item)} under ${first.contract.number}`
      : `${coverages.length} coverages`;
  return (
    <section className="panel" aria-labelledby="end-coverage" data-testid="end-coverage">
      <h3 id="end-coverage">End {what}</h3>
      <p className="hint">
        The last day the cover holds. The coverage stays on record with that day, and is in force
        until the day has passed. A coverage is never removed.
      </p>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem
          error={action.error}
          shown={["ends_on"]}
          onReload={() => {
            onReload();
            onClose();
          }}
        />
        {action.error && ended > 0 && (
          <p className="warning">
            {plural(ended, "coverage was", "coverages were")} ended before this one was refused.
          </p>
        )}
        <div className="fields">
          <TextField
            label="Last day"
            name="ends_on"
            type="date"
            value={day}
            onChange={setDay}
            disabled={action.busy}
            error={refused.ends_on}
            required
          />
        </div>
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || day === ""}>
            End {coverages.length === 1 ? "coverage" : `${coverages.length} coverages`}
          </button>
          <button
            type="button"
            disabled={action.busy}
            onClick={() => {
              // Some may have been ended before a refusal: the rows are read again.
              if (ended > 0) onReload();
              onClose();
            }}
          >
            Cancel
          </button>
        </p>
      </form>
    </section>
  );
}

// --- the page of an item ---------------------------------------------------------------

interface ItemCoverageProps {
  item: Item;
  mayEdit: boolean;
  /** Something of the coverage changed: the item is read again, and says so. */
  onChanged: (text: string) => void;
}

/**
 * The contracts that cover an item, now and before: each with its days in force. The
 * item holds nothing of a contract but the link, so the number, the period and the
 * status shown are the contract's, read as the page is.
 */
export function ItemCoverage({ item, mayEdit, onChanged }: ItemCoverageProps) {
  const [turn, setTurn] = useState(0);
  const [adding, setAdding] = useState(false);
  const [ending, setEnding] = useState<string | null>(null);
  const found = useLoad(`item-coverage ${item.hid} ${turn}`, (signal) =>
    api.request("get", "/api/v1/contract-coverage", {
      query: { filter: `item_hid:eq:${item.hid}`, limit: EVERY, sort: ["-in_force"] },
      signal,
    }),
  );
  const rows = found.data?.items ?? [];
  const sorting = useSorting(rows, {
    contract: (row) => row.contract.number,
    vendor: (row) => row.contract.vendor,
    status: (row) => optionLabel(CONTRACT_STATUSES, row.contract.status),
    starts: (row) => dateValue(row.effective_starts_on),
    ends: (row) => dateValue(row.effective_ends_on),
    in_force: (row) => row.in_force,
  });
  const day = today();
  const open = rows.find((row) => row.hid === ending) ?? null;
  const action = useAction();
  const pending = renewalPending(item.coverage);

  function changed(text: string) {
    setAdding(false);
    setEnding(null);
    setTurn((count) => count + 1);
    onChanged(text);
  }

  /** Say that the vendor has been told the item left: the mark is cleared. */
  async function vendorTold(row: Coverage) {
    const result = await action.run(() =>
      api.request("patch", "/api/v1/contracts/{hid}/coverage/{coverage_hid}", {
        path: { hid: row.contract_hid, coverage_hid: row.hid },
        body: { row_version: row.row_version, left_service: false },
      }),
    );
    if (result.ok) {
      changed(`${row.contract.vendor} has been told that ${itemName(item)} left service.`);
    }
  }

  /** Remove a coverage that was a mistake. What it was is in the audit trail. */
  async function remove(row: Coverage) {
    const result = await action.run(() =>
      api.request("delete", "/api/v1/contracts/{hid}/coverage/{coverage_hid}", {
        path: { hid: row.contract_hid, coverage_hid: row.hid },
      }),
    );
    if (result.ok) {
      changed(`The coverage of ${itemName(item)} under ${row.contract.number} was removed.`);
    }
  }

  return (
    <section aria-labelledby="coverage">
      <h2 id="coverage">Coverage</h2>
      <dl className="facts" data-testid="item-coverage-facts">
        <dt>Covered today</dt>
        <dd data-testid="item-covered" data-covered={item.covered ? "true" : "false"}>
          {item.covered ? "Yes" : "No: no contract covers it today"}
          {pending && (
            <span className="badge" data-testid="item-renewal-pending">
              {RENEWAL_PENDING_NOTE}
            </span>
          )}
        </dd>
        <dt>Contracts that cover it today</dt>
        <dd data-testid="item-contract-count" data-count={item.contract_count}>
          {item.contract_count}
          {item.contract_count > 1 && (
            <span className="muted">
              {" "}
              · more than one: worth a look before a renewal, since two contracts for one device are
              usually one too many
            </span>
          )}
        </dd>
        <dt>Covered until</dt>
        <dd data-testid="item-covered-until">
          {item.covered_until ??
            (pending ? (
              <span className="muted">No day is known: the renewal is pending</span>
            ) : item.covered ? (
              <span className="muted">No end is named</span>
            ) : (
              <span className="muted">—</span>
            ))}
        </dd>
      </dl>
      <Problem error={found.error} />
      <Problem error={action.error} onReload={() => setTurn((count) => count + 1)} />
      {found.loading && !found.data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {found.data && rows.length === 0 && (
        <p className="muted">It has never been under a contract.</p>
      )}
      {rows.length > 0 && (
        <div className="scroll">
          <table data-testid="item-coverage">
            <caption className="visually-hidden">
              The coverage of {itemName(item)} under contracts, what is in force today first
            </caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="contract">
                  Contract
                </SortTh>
                <SortTh sort={sorting} column="vendor">
                  Vendor
                </SortTh>
                <SortTh sort={sorting} column="status">
                  Status of the contract
                </SortTh>
                <SortTh sort={sorting} column="starts">
                  Covered from
                </SortTh>
                <SortTh sort={sorting} column="ends">
                  Covered until
                </SortTh>
                <SortTh sort={sorting} column="in_force">
                  In force today
                </SortTh>
                {mayEdit && (
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((row) => {
                const starts = coverageDay(row.starts_on, row.effective_starts_on);
                const ends = coverageDay(row.ends_on, row.effective_ends_on);
                return (
                  <tr
                    key={row.hid}
                    data-contract={row.contract.number}
                    data-in-force={row.in_force ? "true" : "false"}
                    data-left-service={row.left_service ? "true" : "false"}
                    className={row.in_force ? undefined : "muted"}
                  >
                    <th scope="row">
                      <Link to={contractPath(row.contract_hid)}>{row.contract.number}</Link>
                      {row.contract.record_status !== "active" && (
                        <span className="badge">
                          {optionLabel(RECORD_STATUSES, row.contract.record_status)}
                        </span>
                      )}
                    </th>
                    <td>{row.contract.vendor}</td>
                    <td
                      title={
                        row.contract.status === RENEWAL_PENDING ? RENEWAL_PENDING_NOTE : undefined
                      }
                    >
                      {optionLabel(CONTRACT_STATUSES, row.contract.status)}
                    </td>
                    <CoverageDay day={starts} blank="From the beginning" />
                    <CoverageDay day={ends} blank="Until further notice" />
                    <td>
                      {row.in_force ? "Yes" : "No"}
                      {row.left_service && (
                        <span
                          className="badge"
                          data-testid="left-service"
                          title={LEFT_SERVICE_NOTE}
                        >
                          Ended: it left service
                        </span>
                      )}
                    </td>
                    {mayEdit && (
                      <td className="row-actions">
                        {row.left_service && (
                          <button
                            type="button"
                            disabled={action.busy}
                            aria-label={`The vendor has been told, for ${row.contract.number}`}
                            onClick={() => vendorTold(row)}
                          >
                            Vendor told
                          </button>
                        )}
                        {endable(row, day) && row.contract.record_status !== "retired" && (
                          <button
                            type="button"
                            disabled={action.busy}
                            aria-label={`End the coverage under ${row.contract.number}`}
                            onClick={() => {
                              setAdding(false);
                              setEnding(row.hid);
                            }}
                          >
                            End
                          </button>
                        )}
                        <ConfirmButton
                          label="Remove"
                          title={`Remove the coverage under ${row.contract.number}?`}
                          confirmLabel="Remove the coverage"
                          onConfirm={() => remove(row)}
                          disabled={action.busy}
                        >
                          <p>{REMOVE_NOTE}</p>
                        </ConfirmButton>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {rows.length > 0 && (
        <p className="hint">
          A day shown lighter is the contract&apos;s: the coverage has none of its own, and follows
          the contract when it is renewed. A coverage that was ended because the item left service
          is marked until the vendor has been told. End is for cover that was true for a time;
          Remove is for one that was a mistake.
        </p>
      )}
      {mayEdit && open && (
        <EndCoverage
          key={`${open.hid} ${open.row_version}`}
          coverages={[open]}
          onEnded={changed}
          onClose={() => setEnding(null)}
          onReload={() => setTurn((count) => count + 1)}
        />
      )}
      {mayEdit && !adding && (
        <p className="actions">
          <button
            type="button"
            onClick={() => {
              setEnding(null);
              setAdding(true);
            }}
          >
            Cover with a contract
          </button>
        </p>
      )}
      {mayEdit && adding && (
        <CoverItems
          rows={{ kind: "rows", hids: [item.hid] }}
          view={null}
          what={itemName(item)}
          onCovered={(text) => changed(text)}
          onClose={() => setAdding(false)}
        />
      )}
    </section>
  );
}

function CoverageDay({ day, blank }: { day: { text: string; inherited: boolean }; blank: string }) {
  if (day.text === "") return <td className="muted">{blank}</td>;
  return (
    <td
      className={day.inherited ? "nowrap inherited" : "nowrap"}
      title={day.inherited ? "The contract's: the coverage has none of its own" : undefined}
    >
      {day.text}
    </td>
  );
}

// --- the item grid: cover the rows selected --------------------------------------------

interface CoverItemsProps {
  /** The items to cover: particular ones by their HIDs, or all that a filter keeps. */
  rows: Chosen;
  /** The view of the grid the rows were chosen in: what "all that match" means. */
  view: GridView | null;
  /** What is covered, when it is one thing with a name: the name of the item. */
  what?: string;
  onCovered: (text: string) => void;
  onClose: () => void;
}

/** Every HID a view keeps, read a page at a time. More than the page takes in one go is refused. */
async function hidsOf(view: GridView, count: number): Promise<string[]> {
  if (count > COVER_MOST) {
    throw new Error(
      `${count} items are more than the ${COVER_MOST} that are put under a contract in one go. Narrow the filter.`,
    );
  }
  const hids: string[] = [];
  for (let offset = 0; offset < count; offset += EVERY) {
    const page = await api.request("post", "/api/v1/items/query", {
      body: {
        ...queryBody({
          filter: view.filter,
          // By HID, so that the pages hold every item once whatever else changes meanwhile.
          sort: ["hid"],
          limit: EVERY,
          offset,
          include_archived: view.include_archived,
          include_drafts: view.include_drafts,
        }),
        fields: ["hid"],
      },
    });
    hids.push(...page.items.map((item) => item.hid));
    if (page.items.length < EVERY) break;
  }
  return hids;
}

/**
 * Put items under a contract: the rows selected in the item grid, or one item from its
 * own page. A request takes a thousand items, and either all of its items are covered or
 * none is; more than a thousand go as one request after another, and should one of them
 * be refused the page says how many were covered before it. A contract is one record
 * applied to many items: nothing is written to any of them.
 */
export function CoverItems({ rows, view, what, onCovered, onClose }: CoverItemsProps) {
  const [contract, setContract] = useState("");
  const [starts, setStarts] = useState("");
  const [ends, setEnds] = useState("");
  const [covered, setCovered] = useState(0);
  const action = useAction();
  const known = ["contract_hid", "starts_on", "ends_on"];
  const refused = fieldErrors(action.error, known).shown;
  const count = chosenCount(rows);
  const whom = what ?? plural(count, "item");
  const several = count > COVER_AT_ONCE;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setCovered(0);
    const result = await action.run(async () => {
      const hids = rows.kind === "rows" ? rows.hids : view ? await hidsOf(view, rows.count) : [];
      let done = 0;
      let number = "the contract";
      for (const batch of coverBatches(hids)) {
        const made = await api.request("post", "/api/v1/contracts/{hid}/coverage", {
          path: { hid: contract },
          body: coverBody(batch, starts, ends),
        });
        done += made.length;
        number = made[0]?.contract.number ?? number;
        setCovered(done);
      }
      return { done, number };
    });
    if (!result.ok) return;
    const { done, number } = result.value;
    onCovered(
      `${plural(done, "item is", "items are")} now under ${number}. Nothing was written to ${done === 1 ? "it" : "any of them"}.`,
    );
  }

  return (
    <section className="panel" aria-labelledby="cover-items" data-testid="cover-items">
      <h2 id="cover-items">Cover {whom} with a contract</h2>
      <p className="hint">
        {rows.kind === "all" && `All ${plural(count, "item")} that match the filter. `}
        {several
          ? `They go ${COVER_AT_ONCE} to a request, one request after another: each request covers all of its items, or none.`
          : "In one request: all of them, or none."}{" "}
        An item under a contract holds only the link: the number, the period and the support level
        it shows are the contract&apos;s.
      </p>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={known} labels={{ items: "The items" }} />
        {action.error && covered > 0 && (
          <p className="warning">
            {plural(covered, "item was", "items were")} put under the contract before this was
            refused, and {covered === 1 ? "is" : "are"} covered.
          </p>
        )}
        <div className="fields">
          <ContractField
            label="Contract"
            name="contract_hid"
            value={contract}
            onChange={setContract}
            blank="No contract chosen"
            disabled={action.busy}
            error={refused.contract_hid}
          />
          <Dates
            starts={starts}
            ends={ends}
            onStarts={setStarts}
            onEnds={setEnds}
            errors={refused}
            disabled={action.busy}
          />
        </div>
        <p className="actions">
          <button
            type="submit"
            className="primary"
            disabled={action.busy || contract === "" || count === 0}
          >
            Cover {whom}
          </button>
          <button type="button" onClick={onClose} disabled={action.busy}>
            Cancel
          </button>
        </p>
      </form>
    </section>
  );
}

// --- the page of a contract ------------------------------------------------------------

const COVERAGE_COLUMNS: GridColumn<Coverage>[] = [
  {
    id: "item.name",
    header: "Item",
    kind: "text",
    column: "item",
    value: (row) => itemName(row.item),
    link: true,
    width: 220,
  },
  {
    id: "item.pid",
    header: "PID",
    kind: "text",
    column: null,
    value: (row) => row.item.pid,
    width: 150,
  },
  {
    id: "item.serial_number",
    header: "Serial number",
    kind: "text",
    column: null,
    value: (row) => row.item.serial_number,
    mono: true,
    width: 150,
  },
  {
    id: "item.asset_tag",
    header: "Asset tag",
    kind: "text",
    column: null,
    value: (row) => row.item.asset_tag,
    hide: true,
  },
  {
    // The item's own lifecycle state: an item that has left service may still be covered.
    id: "item.lifecycle_state",
    header: "State of the item",
    kind: "choice",
    column: null,
    value: (row) => row.item_lifecycle_state,
    width: 150,
  },
  {
    id: "item.record_status",
    header: "Record status of the item",
    kind: "choice",
    column: null,
    value: (row) => optionLabel(RECORD_STATUSES, row.item_record_status),
    choices: RECORD_STATUSES,
    hide: true,
    width: 200,
  },
  {
    // The day in force: the coverage's own, or the contract's where it has none.
    id: "effective.starts_on",
    header: "Covered from",
    kind: "date",
    column: "effective_starts_on",
    value: (row) => row.effective_starts_on,
    inherited: (row) => !row.starts_on && Boolean(row.effective_starts_on),
    hint: (row) =>
      !row.starts_on && row.effective_starts_on
        ? "The contract's: the coverage has no start of its own"
        : "",
    width: 140,
  },
  {
    id: "effective.ends_on",
    header: "Covered until",
    kind: "date",
    column: "effective_ends_on",
    value: (row) => row.effective_ends_on,
    inherited: (row) => !row.ends_on && Boolean(row.effective_ends_on),
    hint: (row) =>
      !row.ends_on && row.effective_ends_on
        ? "The contract's: the coverage has no end of its own, and follows a renewal"
        : "",
    width: 140,
  },
  {
    id: "in_force",
    header: "In force today",
    kind: "boolean",
    value: (row) => (row.in_force ? "Yes" : "No"),
    width: 140,
  },
  {
    // hirdir ended it on the day its item left service; cleared once the vendor is told.
    id: "left_service",
    header: "Left service",
    kind: "boolean",
    value: (row) => (row.left_service ? "Ended: it left service" : ""),
    hint: (row) => (row.left_service ? LEFT_SERVICE_NOTE : ""),
    choices: [
      { value: "true", label: "Ended because the item left: the vendor is still to be told" },
      { value: "false", label: "Not so" },
    ],
    width: 180,
  },
  {
    id: "starts_on",
    header: "Its own start",
    kind: "date",
    value: (row) => row.starts_on,
    hide: true,
  },
  {
    id: "ends_on",
    header: "Its own end",
    kind: "date",
    value: (row) => row.ends_on,
    hide: true,
  },
  {
    id: "updated_at",
    header: "Changed",
    kind: "timestamp",
    column: null,
    value: (row) => formatTime(row.updated_at),
    hide: true,
  },
  { id: "hid", header: "HID", kind: "reference", value: (row) => row.hid, mono: true, hide: true },
];

interface ContractCoverageProps {
  contract: Contract;
  mayEdit: boolean;
  /** The coverage changed: the contract is read again, for its counts. */
  onChanged: (text: string) => void;
}

/**
 * The items a contract covers, as a grid: sorted, filtered and paged by the server, and
 * exported like any other. Items are added several at a time, and the coverage of the
 * rows selected is ended with a date.
 */
export function ContractCoverage({ contract, mayEdit, onChanged }: ContractCoverageProps) {
  const [reloads, setReloads] = useState(0);
  const [adding, setAdding] = useState(false);
  const [ending, setEnding] = useState<Coverage[] | null>(null);
  const [settling, setSettling] = useState<{ what: Settle; rows: Coverage[] } | null>(null);
  const [done, setDone] = useState("");
  const within = useMemo(
    () => ({ filter: { field: "contract_hid", op: "eq" as const, value: contract.hid } }),
    [contract.hid],
  );
  const day = today();
  const open = mayEdit && contract.record_status !== "retired";

  function changed(text: string) {
    setAdding(false);
    setEnding(null);
    setSettling(null);
    setReloads((count) => count + 1);
    setDone("");
    onChanged(text);
  }

  return (
    <section aria-labelledby="contract-coverage">
      <h2 id="contract-coverage">Items it covers</h2>
      <p>
        Each item under the contract, with its days. A day shown lighter is the contract&apos;s own:
        such a coverage follows the contract when it is renewed. Filter{" "}
        <span className="mono">In force today</span> to what it covers now. A coverage is ended on
        the day its item is retired, released or archived, and is marked Left service until the
        vendor has been told.
      </p>
      <Notice text={done} />
      {open && settling && (
        <SettleCoverage
          key={`${settling.what} ${settling.rows.map((one) => `${one.hid} ${one.row_version}`).join(" ")}`}
          what={settling.what}
          coverages={settling.rows}
          onDone={changed}
          onClose={() => setSettling(null)}
          onReload={() => setReloads((count) => count + 1)}
        />
      )}
      {open && adding && (
        <AddCoverage
          contract={contract}
          onCancel={() => setAdding(false)}
          onAdded={(count) =>
            changed(
              `${plural(count, "item was", "items were")} put under ${contract.number}. Nothing was written to ${count === 1 ? "it" : "any of them"}.`,
            )
          }
        />
      )}
      {open && ending && (
        <EndCoverage
          key={ending.map((one) => `${one.hid} ${one.row_version}`).join(" ")}
          coverages={ending}
          onEnded={changed}
          onClose={() => setEnding(null)}
          onReload={() => setReloads((count) => count + 1)}
        />
      )}
      <DataGrid<Coverage>
        id="contract-coverage"
        noun={["coverage", "coverages"]}
        entity="contract_coverage"
        columns={COVERAGE_COLUMNS}
        within={within}
        reloadKey={reloads}
        load={(request, signal) =>
          api.request("get", "/api/v1/contracts/{hid}/coverage", {
            path: { hid: contract.hid },
            query: {
              ...(request.filter ? { filter: JSON.stringify(request.filter) } : {}),
              ...(request.sort.length > 0 ? { sort: request.sort } : {}),
              limit: request.limit,
              offset: request.offset,
            },
            signal,
          })
        }
        rowId={(row) => row.hid}
        rowLink={(row) => `/items/${encodeURIComponent(row.item_hid)}`}
        dimmed={(row) => !row.in_force}
        {...(open
          ? {
              actions: [
                {
                  label: "End coverage",
                  rowsOnly: true,
                  run: (_chosen, _view, rows) => {
                    const still = rows.filter((row) => endable(row, day));
                    setAdding(false);
                    setSettling(null);
                    if (still.length === 0) {
                      setEnding(null);
                      setDone("The coverage selected has ended already.");
                    } else {
                      setDone("");
                      setEnding(still);
                    }
                  },
                },
                {
                  label: "Vendor told",
                  rowsOnly: true,
                  run: (_chosen, _view, rows) => {
                    const left = rows.filter((row) => row.left_service);
                    setAdding(false);
                    setEnding(null);
                    if (left.length === 0) {
                      setSettling(null);
                      setDone("None of the coverage selected is marked as ended because it left.");
                    } else {
                      setDone("");
                      setSettling({ what: "told", rows: left });
                    }
                  },
                },
                {
                  label: "Remove coverage",
                  rowsOnly: true,
                  run: (_chosen, _view, rows) => {
                    setAdding(false);
                    setEnding(null);
                    setDone("");
                    setSettling({ what: "remove", rows });
                  },
                },
              ],
            }
          : {})}
      >
        {open && !adding && (
          <button
            type="button"
            className="primary"
            onClick={() => {
              setEnding(null);
              setAdding(true);
            }}
          >
            Add items
          </button>
        )}
      </DataGrid>
    </section>
  );
}

/** What is done with the coverage selected: the vendor was told, or it was a mistake. */
type Settle = "told" | "remove";

interface SettleCoverageProps {
  what: Settle;
  /** The coverages, as they were read: each goes with its own version. */
  coverages: readonly Coverage[];
  onDone: (text: string) => void;
  onClose: () => void;
  onReload: () => void;
}

/**
 * Say that the vendor has been told that the items of the coverage selected left
 * service, which clears the mark; or remove the coverage selected, which was a mistake.
 * Each coverage is one change of its own: the first that is refused stops the rest.
 */
function SettleCoverage({ what, coverages, onDone, onClose, onReload }: SettleCoverageProps) {
  const [settled, setSettled] = useState(0);
  const action = useAction();
  const remove = what === "remove";
  const count = coverages.length;

  async function run() {
    let made = 0;
    setSettled(0);
    const result = await action.run(async () => {
      for (const coverage of coverages) {
        const path = { hid: coverage.contract_hid, coverage_hid: coverage.hid };
        if (remove) {
          await api.request("delete", "/api/v1/contracts/{hid}/coverage/{coverage_hid}", { path });
        } else {
          await api.request("patch", "/api/v1/contracts/{hid}/coverage/{coverage_hid}", {
            path,
            body: { row_version: coverage.row_version, left_service: false },
          });
        }
        made += 1;
        setSettled(made);
      }
    });
    if (!result.ok) return;
    onDone(
      remove
        ? `${plural(made, "coverage was", "coverages were")} removed. The audit trail holds what ${made === 1 ? "it was" : "they were"}.`
        : `The vendor has been told of ${plural(made, "item")} that left service.`,
    );
  }

  return (
    <section className="panel" aria-labelledby="settle-coverage" data-testid="settle-coverage">
      <h3 id="settle-coverage">
        {remove
          ? `Remove ${plural(count, "coverage")}`
          : `The vendor has been told of ${plural(count, "item")}`}
      </h3>
      <p className="hint">{remove ? REMOVE_NOTE : LEFT_SERVICE_NOTE}</p>
      <ul className="plain-list">
        {coverages.map((coverage) => (
          <li key={coverage.hid}>
            {itemName(coverage.item)}
            <span className="muted">
              {" "}
              · {coverage.effective_starts_on ?? "from the beginning"} to{" "}
              {coverage.effective_ends_on ?? "further notice"}
            </span>
          </li>
        ))}
      </ul>
      <Problem
        error={action.error}
        onReload={() => {
          onReload();
          onClose();
        }}
      />
      {action.error && settled > 0 && (
        <p className="warning">
          {plural(settled, "coverage was", "coverages were")} done before this one was refused.
        </p>
      )}
      <p className="actions">
        <button
          type="button"
          className={remove ? "danger" : "primary"}
          disabled={action.busy}
          onClick={run}
        >
          {remove
            ? `Remove ${count === 1 ? "the coverage" : `${count} coverages`}`
            : "The vendor has been told"}
        </button>
        <button
          type="button"
          disabled={action.busy}
          onClick={() => {
            if (settled > 0) onReload();
            onClose();
          }}
        >
          Cancel
        </button>
      </p>
    </section>
  );
}

interface AddCoverageProps {
  contract: Contract;
  onCancel: () => void;
  onAdded: (count: number) => void;
}

/** Put several items under the contract at once: found one by one, sent together. */
function AddCoverage({ contract, onCancel, onAdded }: AddCoverageProps) {
  const [pending, setPending] = useState<Array<{ hid: string; name: string }>>([]);
  const [starts, setStarts] = useState("");
  const [ends, setEnds] = useState("");
  const action = useAction();
  const refused = fieldErrors(action.error, ["starts_on", "ends_on"]).shown;
  // The server names an item it refuses by its place in the request.
  const labels: Record<string, string> = { items: "The items" };
  for (const [place, item] of pending.entries()) {
    labels[`items.${place}.item_hid`] = item.name;
    labels[`items.${place}`] = item.name;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const result = await action.run(() =>
      api.request("post", "/api/v1/contracts/{hid}/coverage", {
        path: { hid: contract.hid },
        body: coverBody(
          pending.map((item) => item.hid),
          starts,
          ends,
        ),
      }),
    );
    if (result.ok) onAdded(result.value.length);
  }

  return (
    <section className="panel" aria-labelledby="add-coverage" data-testid="add-coverage">
      <h3 id="add-coverage">Add items to {contractLabel(contract)}</h3>
      <p className="hint">
        Find each item and add it to the list, then put them all under the contract in one request:
        all of them, or none. Many items at once are covered from the item grid: select the rows
        there, or all that match a filter, and choose Cover with a contract.
      </p>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={["starts_on", "ends_on"]} labels={labels} />
        <ItemPicker
          label="Add an item"
          taken={pending.map((item) => item.hid)}
          disabled={action.busy}
          onPick={(item) => setPending((was) => [...was, { hid: item.hid, name: itemName(item) }])}
        />
        {pending.length > 0 ? (
          <ul className="plain-list" data-testid="coverage-pending">
            {pending.map((item) => (
              <li key={item.hid}>
                {item.name}{" "}
                <button
                  type="button"
                  disabled={action.busy}
                  aria-label={`Take ${item.name} off the list`}
                  onClick={() => setPending((was) => was.filter((one) => one.hid !== item.hid))}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No item is on the list yet.</p>
        )}
        <div className="fields">
          <Dates
            starts={starts}
            ends={ends}
            onStarts={setStarts}
            onEnds={setEnds}
            errors={refused}
            disabled={action.busy}
          />
        </div>
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || pending.length === 0}>
            Cover {plural(pending.length, "item")}
          </button>
          <button type="button" onClick={onCancel} disabled={action.busy}>
            Cancel
          </button>
        </p>
      </form>
    </section>
  );
}
