// 0.9.7: the records a past import made (P-234), from `GET /imports/{hid}/created`: the
// row of the file, the kind, the name as a link, and what each is now. For an import of
// items or of device groups the rows are ticked, and the rows ticked are retired by the
// Inventory role (P-228) or deleted by an Admin (P-227), as from their lists. The vendors
// and the catalog entries it made only because a row named them are listed after.

import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api } from "../api";
import { useAuth } from "../auth";
import { useLoad } from "../lib/hooks";
import { kindWord } from "../lib/problems";
import {
  type CreatedRecord,
  createdPath,
  type MadeForARow,
  removalKindOf,
  stateLabel,
  tickable,
  tooManyText,
} from "../lib/removal";
import { allows } from "../lib/roles";
import { withCount } from "../lib/selection";
import { Pager } from "./Pager";
import { Problem } from "./Problem";
import { useTickedRemoval } from "./Removal";

const PAGE = 100;

interface ImportCreatedProps {
  hid: string;
  /** What the import was of: `items`, `device_groups`. */
  entity: string;
  /** Changes when the import has been worked again, as when an apply has ended. */
  turn: number;
}

function Named({
  record,
}: {
  record: Pick<CreatedRecord, "record_type" | "record_hid" | "state" | "label">;
}) {
  const to = createdPath(record);
  return to ? <Link to={to}>{record.label}</Link> : <span>{record.label}</span>;
}

/** What a past import made, and what is now done with what should never have been. */
export function ImportCreated({ hid, entity, turn }: ImportCreatedProps) {
  const { user } = useAuth();
  const kind = removalKindOf(entity);
  const removal = useTickedRemoval(kind ?? "item");
  const mayRetire = kind !== null && allows(user.role, "inventory");
  const mayDelete = kind !== null && allows(user.role, "admin");
  const [offset, setOffset] = useState(0);
  const [ticked, setTicked] = useState<ReadonlySet<string>>(new Set());
  const made = useLoad(`import created ${hid} ${offset} ${turn} ${removal.turn}`, (signal) =>
    api.request("get", "/api/v1/imports/{hid}/created", {
      path: { hid },
      query: { limit: PAGE, offset },
      signal,
    }),
  );
  // Once a Retire or a Delete is done, those it refused stay ticked, and only they.
  useEffect(() => {
    if (removal.turn > 0) setTicked(new Set(removal.keep));
  }, [removal.turn, removal.keep]);

  const rows = made.data?.items ?? [];
  const also: MadeForARow[] = made.data?.also ?? [];
  const onShow = rows.filter((row) => tickable(row, kind));
  const tickedOnShow = onShow.filter((row) => ticked.has(row.record_hid));
  const every = onShow.length > 0 && tickedOnShow.length === onShow.length;
  const mayTick = mayRetire || mayDelete;
  const chosen = { ticked: ticked.size, allMatching: false, total: null };
  // Ticks are kept across pages: more than one request takes are said so first.
  const tooMany = tooManyText(ticked.size);

  function tick(recordHid: string, on: boolean) {
    setTicked((was) => {
      const next = new Set(was);
      if (on) next.add(recordHid);
      else next.delete(recordHid);
      return next;
    });
  }

  function tickEvery(on: boolean) {
    setTicked((was) => {
      const next = new Set(was);
      for (const row of onShow) {
        if (on) next.add(row.record_hid);
        else next.delete(row.record_hid);
      }
      return next;
    });
  }

  return (
    <section aria-labelledby="import-created" data-testid="import-created">
      <h2 id="import-created">What it made</h2>
      <Problem error={made.error} />
      {removal.shown}
      {made.loading && !made.data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {made.data && (
        <>
          {mayTick && (
            <p className="actions">
              {mayRetire && (
                <button
                  type="button"
                  disabled={ticked.size === 0 || tooMany !== null}
                  onClick={() => removal.ask("retire", [...ticked])}
                >
                  {withCount("Retire", chosen)}
                </button>
              )}
              {mayDelete && (
                <button
                  type="button"
                  disabled={ticked.size === 0 || tooMany !== null}
                  onClick={() => removal.ask("delete", [...ticked])}
                >
                  {withCount("Delete", chosen)}
                </button>
              )}
              {ticked.size > 0 && (
                <button type="button" onClick={() => setTicked(new Set())}>
                  Clear selection
                </button>
              )}
            </p>
          )}
          {mayTick && tooMany !== null && (
            <p className="hint" data-testid="import-created-too-many">
              {tooMany}
            </p>
          )}
          <div className="scroll">
            <table data-testid="import-created-rows">
              <caption className="visually-hidden">
                The records the import made, by the row of the file
              </caption>
              <thead>
                <tr>
                  {mayTick && (
                    <th scope="col" className="tick">
                      <input
                        type="checkbox"
                        aria-label="Every row of this page"
                        checked={every}
                        disabled={onShow.length === 0}
                        ref={(box) => {
                          if (box) box.indeterminate = tickedOnShow.length > 0 && !every;
                        }}
                        onChange={(event) => tickEvery(event.target.checked)}
                      />
                    </th>
                  )}
                  <th scope="col" className="number">
                    Row
                  </th>
                  <th scope="col">Kind</th>
                  <th scope="col">Name</th>
                  <th scope="col">Now</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={`${row.row} ${row.record_hid}`}
                    data-hid={row.record_hid}
                    data-state={row.state}
                  >
                    {mayTick && (
                      <td className="tick">
                        {tickable(row, kind) && (
                          <input
                            type="checkbox"
                            aria-label={`Tick row ${row.row}`}
                            checked={ticked.has(row.record_hid)}
                            onChange={(event) => tick(row.record_hid, event.target.checked)}
                          />
                        )}
                      </td>
                    )}
                    <td className="number">{row.row}</td>
                    <td>{kindWord(row.record_type)}</td>
                    <td>
                      <Named record={row} />
                    </td>
                    <td>{stateLabel(row.state)}</td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={mayTick ? 5 : 4} className="muted">
                      The import made no record.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pager
            total={made.data.total}
            limit={PAGE}
            offset={offset}
            noun="records"
            onChange={setOffset}
          />
          {also.length > 0 && (
            <div data-testid="import-created-also">
              <h3>Made for a row that named them</h3>
              <ul>
                {also.map((record) => (
                  <li key={record.record_hid}>
                    {kindWord(record.record_type)} <Named record={record} />
                    {record.state !== "active" && <> · {stateLabel(record.state)}</>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}
