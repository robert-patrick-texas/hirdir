// The grid of circuits, of the whole list or of a part of it: the circuits of a carrier,
// of a group. It is the circuit list with a filter the page gives, so it is sorted,
// filtered and paged by the server as the circuit grid is, and copied and exported like
// it: what the file holds is what the grid shows.

import { type ReactNode, useMemo } from "react";
import { api } from "../api";
import { type Circuit, circuitIsDimmed, circuitPath, GRID_FIELDS } from "../lib/circuits";
import { type ListRequest, queryBody } from "../lib/gridQuery";
import { useChoices } from "../lib/lists";
import { circuitColumns } from "./grid/circuitColumns";
import { broughtForward } from "./grid/columns";
import { DataGrid, type GridAction, type GridWithin } from "./grid/DataGrid";
import { Problem } from "./Problem";

/** Read one page of circuits, with the fields the grid shows. */
export function readCircuits(request: ListRequest, signal: AbortSignal) {
  return api.request("post", "/api/v1/circuits/query", {
    body: { ...queryBody(request), fields: [...GRID_FIELDS] },
    signal,
  });
}

interface CircuitsGridProps {
  /** The name the reader's layout of this grid is remembered under. */
  id: string;
  /** The part of the circuit list the grid is of; left out, the whole list. */
  within?: GridWithin;
  /** Columns the grid is about, shown from the start right after the name. */
  shown?: readonly string[];
  /** Offer the filter box, with this example under it. */
  shortFilter?: string;
  /** The fields words in the filter box are looked for in (P-187). */
  quickFields?: readonly string[];
  /** A filter to start with, as from a link. */
  startFilter?: string | null;
  startSwitches?: { archived?: boolean; drafts?: boolean } | null;
  /** Offer the switches for the circuits a list leaves out. */
  switches?: boolean;
  reloadKey?: number;
  actions?: ReadonlyArray<GridAction<Circuit>>;
  children?: ReactNode;
}

/** The circuit grid, of the circuits a page names. */
export function CircuitsGrid(props: CircuitsGridProps) {
  const { id, within, shown = [], shortFilter, startFilter, startSwitches, switches } = props;
  const { reloadKey, actions, children, quickFields } = props;
  const choices = useChoices();
  const wanted = shown.join(" ");
  const columns = useMemo(
    () => broughtForward(circuitColumns(choices.data), wanted.split(" ")),
    [choices.data, wanted],
  );

  return (
    <>
      <Problem error={choices.error} />
      {choices.loading && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {!choices.loading && (
        <DataGrid<Circuit>
          id={id}
          noun={["circuit", "circuits"]}
          entity="circuits"
          columns={columns}
          {...(within ? { within } : {})}
          {...(reloadKey === undefined ? {} : { reloadKey })}
          {...(actions ? { actions } : {})}
          {...(shortFilter === undefined ? {} : { shortFilter })}
          {...(quickFields === undefined ? {} : { quickFields })}
          {...(startFilter === undefined ? {} : { startFilter })}
          {...(startSwitches === undefined ? {} : { startSwitches })}
          {...(switches
            ? { switches: { archived: "Include archived", drafts: "Include drafts" } }
            : {})}
          load={readCircuits}
          rowId={(circuit) => circuit.hid}
          rowLink={(circuit) => circuitPath(circuit.hid)}
          dimmed={circuitIsDimmed}
        >
          {children}
        </DataGrid>
      )}
    </>
  );
}
