// Where a circuit is (P-147): an item and a device group list the circuits they are
// connected to, each with its side, to be read; a place lists the circuits that have a
// side there, or within it. Each leads to the circuit, where its devices are changed.

import { Link } from "react-router";
import { api } from "../api";
import {
  type Circuit,
  type Connection,
  circuitPath,
  circuitsWithin,
  sideLabel,
  sidesWithin,
} from "../lib/circuits";
import { filterText } from "../lib/filter";
import { plural } from "../lib/format";
import { useLoad } from "../lib/hooks";
import { optionLabel, RECORD_STATUSES } from "../lib/options";
import { useSorting } from "../lib/useSorting";
import { Problem } from "./Problem";
import { SortTh } from "./SortTh";

function Dash() {
  return <span className="muted">—</span>;
}

function Status({ status }: { status: string }) {
  return status === "active" ? (
    "Active"
  ) : (
    <span className="badge">{optionLabel(RECORD_STATUSES, status)}</span>
  );
}

/** The circuits an item or a device group is connected to, each with its side. */
export function ConnectedCircuits(props: { circuits: readonly Connection[]; whose: string }) {
  const { circuits, whose } = props;
  const sorting = useSorting(circuits, {
    name: (circuit) => circuit.name,
    id: (circuit) => circuit.enterprise_circuit_id,
    side: (circuit) => sideLabel(circuit.side),
    status: (circuit) => circuit.record_status,
  });
  return (
    <section aria-labelledby="connected-circuits" data-testid="connected-circuits">
      <h2 id="connected-circuits">Circuits</h2>
      <p className="hint">
        The circuits {whose} is connected to, each with the side it is on. A connection is made and
        removed on the page of the circuit.
      </p>
      {circuits.length === 0 ? (
        <p className="muted">It is connected to no circuit.</p>
      ) : (
        <div className="scroll">
          <table>
            <caption className="visually-hidden">The circuits {whose} is connected to</caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="name">
                  Circuit
                </SortTh>
                <SortTh sort={sorting} column="id">
                  Enterprise ID
                </SortTh>
                <SortTh sort={sorting} column="side">
                  Side
                </SortTh>
                <SortTh sort={sorting} column="status">
                  Status
                </SortTh>
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((circuit) => (
                <tr
                  key={circuit.link_hid}
                  data-circuit={circuit.name}
                  data-side={circuit.side}
                  className={circuit.record_status === "active" ? undefined : "row-dim"}
                >
                  <th scope="row">
                    <Link to={circuitPath(circuit.hid)}>{circuit.name}</Link>
                  </th>
                  <td className="mono">{circuit.enterprise_circuit_id || <Dash />}</td>
                  <td data-testid="circuit-side">{sideLabel(circuit.side)}</td>
                  <td>
                    <Status status={circuit.record_status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// The most circuits a place lists by itself; the grid of circuits has the rest.
const MOST = 200;

/**
 * The circuits that have a side at a place or within it, drafts and retired ones among
 * them and marked so, as the list of circuits finds them by `location:within:`. A place
 * that has more than the page lists leads to the grid of circuits for the rest.
 */
export function CircuitsHere(props: { place: { hid: string; path: string; name: string } }) {
  const { place } = props;
  const found = useLoad(`circuits within ${place.hid}`, (signal) =>
    api.request("post", "/api/v1/circuits/query", {
      body: {
        filter: circuitsWithin(place.hid) as unknown as Record<string, unknown>,
        sort: ["name"],
        limit: MOST,
        offset: 0,
        include_archived: true,
        include_drafts: true,
        fields: ["name", "enterprise_circuit_id", "speed", "a_side", "z_side", "record_status"],
      },
      signal,
    }),
  );
  const circuits: Circuit[] = found.data?.items ?? [];
  const whole = found.data ? found.data.total <= found.data.items.length : true;
  const sorting = useSorting(
    circuits,
    {
      name: (circuit) => circuit.name,
      id: (circuit) => circuit.enterprise_circuit_id,
      speed: (circuit) => circuit.speed,
      sides: (circuit) => sidesWithin(circuit, place.path).join(" "),
      status: (circuit) => circuit.record_status,
    },
    { enabled: whole },
  );
  const grid = `/circuits?${new URLSearchParams({
    filter: filterText(circuitsWithin(place.hid)),
    archived: "1",
    drafts: "1",
  }).toString()}`;
  return (
    <section aria-labelledby="circuits-here" data-testid="circuits-here">
      <h3 id="circuits-here">Circuits</h3>
      <p className="hint">
        The circuits that have a side at {place.name} or within it.{" "}
        <Link to={grid}>In the grid of circuits</Link>
      </p>
      <Problem error={found.error} />
      {found.loading && !found.data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {found.data && circuits.length === 0 && <p className="muted">No circuit has a side here.</p>}
      {found.data && !whole && (
        <p className="hint">
          The first {plural(circuits.length, "circuit")} of {found.data.total}, by name: the grid of
          circuits has them all.
        </p>
      )}
      {circuits.length > 0 && (
        <div className="scroll">
          <table>
            <caption className="visually-hidden">The circuits with a side at {place.name}</caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="name">
                  Circuit
                </SortTh>
                <SortTh sort={sorting} column="id">
                  Enterprise ID
                </SortTh>
                <SortTh sort={sorting} column="speed">
                  Speed
                </SortTh>
                <SortTh sort={sorting} column="sides">
                  Side here
                </SortTh>
                <SortTh sort={sorting} column="status">
                  Status
                </SortTh>
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((circuit) => (
                <tr
                  key={circuit.hid}
                  data-circuit={circuit.name}
                  className={circuit.record_status === "active" ? undefined : "row-dim"}
                >
                  <th scope="row">
                    <Link to={circuitPath(circuit.hid)}>{circuit.name}</Link>
                  </th>
                  <td className="mono">{circuit.enterprise_circuit_id || <Dash />}</td>
                  <td>{circuit.speed || <Dash />}</td>
                  <td data-testid="circuit-sides">
                    {sidesWithin(circuit, place.path).map(sideLabel).join(", ") || <Dash />}
                  </td>
                  <td>
                    <Status status={circuit.record_status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
