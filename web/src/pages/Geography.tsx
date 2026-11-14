import { type FormEvent, Fragment, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { CheckField, TextField } from "../components/Field";
import { NewPlace, PlaceDetail } from "../components/PlaceParts";
import { Problem } from "../components/Problem";
import { itemsPath, parseShort } from "../lib/filter";
import { useLoad, useReloadOn, useTitle } from "../lib/hooks";
import { useChoices } from "../lib/lists";
import { choiceLabel, optionLabel, RECORD_STATUSES } from "../lib/options";
import {
  countRows,
  drawnDepth,
  isLevel,
  LOCATION_KIND_LIST,
  levelLabel,
  placePath,
  type TreeNode,
  type TreeView,
  treeQuery,
  treeRows,
} from "../lib/places";
import { allows } from "../lib/roles";
import { countText } from "../lib/summary";

type Choice = Schemas["ChoiceOut"];

function viewOf(params: URLSearchParams): TreeView {
  return {
    filter: params.get("filter") ?? "",
    includeArchived: params.get("archived") === "1",
    includeDrafts: params.get("drafts") === "1",
  };
}

function paramsOf(view: TreeView): Record<string, string> {
  return {
    ...(view.filter.trim() ? { filter: view.filter.trim() } : {}),
    ...(view.includeArchived ? { archived: "1" } : {}),
    ...(view.includeDrafts ? { drafts: "1" } : {}),
  };
}

/**
 * Geography: the regions, the sites in them and the locations within each site, as one
 * tree, each place with the items and the components at or beneath it; and one place,
 * when it is chosen, with what it has in force.
 *
 * The regions and sites are fetched at once and the inside of a site when it is opened,
 * so the page does not wait for every rack of every site. The view the counts are of,
 * a filter of the item list and the two switches, is in the address of the page.
 */
export function Geography() {
  useTitle("Geography");
  const { level, hid = "" } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const view = viewOf(params);
  const search = params.toString() ? `?${params.toString()}` : "";
  const mayEdit = allows(user.role, "inventory");
  // Counts the changes that the tree shows, so that it is read again after each.
  const [turn, setTurn] = useState(0);
  const [adding, setAdding] = useState(false);
  // The sites whose inside is on show.
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set());
  const chosen = isLevel(level) && hid !== "" ? { level, hid } : null;

  function openSite(site: string, open = true) {
    setOpened((was) => {
      if (was.has(site) === open) return was;
      const next = new Set(was);
      if (open) next.add(site);
      else next.delete(site);
      return next;
    });
  }

  return (
    <div className="geography">
      <h1>Geography</h1>
      <p>
        Where things are: regions, the sites in them, and the locations within a site. Each place
        shows the items and the components at or beneath it, and a place that is chosen shows what
        it has in force: its contacts and where deliveries go, each with the level it came from.
      </p>
      <ViewForm key={view.filter} view={view} onShow={(next) => setParams(paramsOf(next))} />
      {adding && (
        <NewPlace
          level="region"
          onCancel={() => setAdding(false)}
          onCreated={(made) => {
            setAdding(false);
            setTurn((count) => count + 1);
            navigate({ pathname: placePath("region", made.hid), search });
          }}
        />
      )}
      <div className="geography-columns">
        <section aria-labelledby="tree" className="geography-tree">
          <h2 id="tree">Regions, sites and locations</h2>
          {mayEdit && !adding && (
            <p className="actions">
              <button type="button" className="primary" onClick={() => setAdding(true)}>
                New region
              </button>
            </p>
          )}
          <PlaceTree
            view={view}
            turn={turn}
            search={search}
            chosen={chosen?.hid ?? ""}
            opened={opened}
            onOpen={openSite}
          />
        </section>
        <div className="geography-place">
          {chosen ? (
            <PlaceDetail
              key={`${chosen.level} ${chosen.hid}`}
              level={chosen.level}
              hid={chosen.hid}
              search={search}
              mayEdit={mayEdit}
              onTreeChanged={() => setTurn((count) => count + 1)}
              onSite={openSite}
              onCreated={(madeLevel, made) =>
                navigate({ pathname: placePath(madeLevel, made.hid), search })
              }
            />
          ) : (
            <p className="muted" data-testid="no-place">
              Choose a place in the tree to see its path, its own fields and what it has in force.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

/** The view the counts of the tree are of: a filter of the item list, and its switches. */
function ViewForm({ view, onShow }: { view: TreeView; onShow: (view: TreeView) => void }) {
  const [draft, setDraft] = useState(view.filter);
  const [filterError, setFilterError] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    const typed = draft.trim();
    // The short form is read here as the server reads it. A filter tree as JSON is the
    // server's to judge.
    const parsed = typed.startsWith("{") ? null : parseShort(typed);
    if (parsed && !parsed.ok) {
      setFilterError(parsed.error);
      return;
    }
    setFilterError("");
    onShow({ ...view, filter: typed });
  }

  return (
    <form onSubmit={submit} className="stack" noValidate>
      <div className="inline">
        <TextField
          label="Count the items that match"
          name="filter"
          type="search"
          value={draft}
          onChange={setDraft}
          autoComplete="off"
          hint="A filter of the item list: field:op:value, as in tags:has:refresh-2030. Blank counts every item."
          error={filterError || undefined}
        />
        <button type="submit">Apply</button>
        <button
          type="button"
          disabled={!view.filter && !draft}
          onClick={() => {
            setDraft("");
            setFilterError("");
            onShow({ ...view, filter: "" });
          }}
        >
          Clear
        </button>
      </div>
      <div className="inline">
        <CheckField
          label="Include archived"
          name="include_archived"
          checked={view.includeArchived}
          onChange={(on) => onShow({ ...view, includeArchived: on })}
          hint="Retired places, and retired and archived items"
        />
        <CheckField
          label="Include drafts"
          name="include_drafts"
          checked={view.includeDrafts}
          onChange={(on) => onShow({ ...view, includeDrafts: on })}
          hint="Draft places and draft items"
        />
      </div>
    </form>
  );
}

interface PlaceTreeProps {
  view: TreeView;
  turn: number;
  search: string;
  /** The HID of the place that is chosen, or blank. */
  chosen: string;
  opened: ReadonlySet<string>;
  onOpen: (site: string, open: boolean) => void;
}

/** The tree: regions and sites at once, and the inside of each site that is opened. */
function PlaceTree({ view, turn, search, chosen, opened, onOpen }: PlaceTreeProps) {
  const query = treeQuery(view, { locations: false });
  const tree = useLoad(`tree ${JSON.stringify(query)}`, (signal) =>
    api.request("get", "/api/v1/geography/tree", { query, signal }),
  );
  // After a change the tree is counted again, and stays on show meanwhile.
  useReloadOn(turn, tree.reload);
  const choices = useChoices();
  // The regions whose inside is not on show. Every region starts open.
  const [closed, setClosed] = useState<ReadonlySet<string>>(new Set());
  const data = tree.data;
  const rows = data ? treeRows(data.roots, closed) : [];
  const short = view.filter.trim();
  // The items that are nowhere, in the grid: only a filter in the short form can be added to.
  const nowhere = short.startsWith("{") ? null : itemsPath(`${short} location:empty:true`.trim());

  function toggleRegion(hid: string) {
    setClosed((was) => {
      const next = new Set(was);
      if (!next.delete(hid)) next.add(hid);
      return next;
    });
  }

  return (
    <>
      {/* A filter the server refused is named in the refusal, as its field. */}
      <Problem error={tree.error} />
      <Problem error={choices.error} />
      {tree.loading && !data && (
        <p role="status" className="muted loading-late">
          Counting…
        </p>
      )}
      {data && (
        <div className="scroll">
          <table data-testid="geography-tree" className="tree">
            <caption className="visually-hidden">
              Regions, sites and locations, each with the items and components at or beneath it
            </caption>
            <thead>
              <tr>
                <th scope="col">Place</th>
                <th scope="col">Kind</th>
                <th scope="col" className="number">
                  Items
                </th>
                <th scope="col" className="number">
                  Components
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ node, depth, open, hasChildren }) => {
                const site = node.level === "site";
                const shown = site ? opened.has(node.hid) : open;
                return (
                  <Fragment key={node.hid}>
                    <PlaceRow
                      node={node}
                      depth={depth}
                      search={search}
                      chosen={chosen}
                      choices={choices.data}
                      toggle={
                        site || hasChildren
                          ? {
                              open: shown,
                              flip: () =>
                                site ? onOpen(node.hid, !shown) : toggleRegion(node.hid),
                            }
                          : null
                      }
                    />
                    {site && shown && (
                      <SiteInside
                        site={node}
                        depth={depth + 1}
                        view={view}
                        turn={turn}
                        search={search}
                        chosen={chosen}
                        choices={choices.data}
                      />
                    )}
                  </Fragment>
                );
              })}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={4} className="muted">
                    There is no region yet.
                  </td>
                </tr>
              )}
            </tbody>
            <tfoot>
              {countRows(data).map((row, place) => {
                const cell = place === 0 ? "tree-count tree-count-first" : "tree-count";
                return (
                  <tr key={row.key} data-row={row.key}>
                    <th scope="row" colSpan={2} className={cell}>
                      {row.key === "unplaced" && nowhere && row.count.items > 0 ? (
                        <Link to={nowhere}>{row.label}</Link>
                      ) : (
                        row.label
                      )}
                    </th>
                    <td className={`number ${cell}`} data-count="items">
                      {countText(row.count.items)}
                    </td>
                    <td className={`number ${cell}`} data-count="components">
                      {countText(row.count.component_count)}
                    </td>
                  </tr>
                );
              })}
            </tfoot>
          </table>
        </div>
      )}
      <p className="hint">
        Items counts every item whose location in force is at or beneath the place, major and minor:
        a minor item is where the item it is in is, unless it has a location of its own. Components
        are the items that count, as the summary counts them. The places at the top, the items that
        are nowhere and those in places the view leaves out come to the items in view.
      </p>
    </>
  );
}

interface PlaceRowProps {
  node: TreeNode;
  depth: number;
  search: string;
  chosen: string;
  choices: readonly Choice[] | undefined;
  /** For a place that may be opened: whether it is, and the way to open or close it. */
  toggle: { open: boolean; flip: () => void } | null;
}

/** One place of the tree: its name as the link to it, and what is at or beneath it. */
function PlaceRow({ node, depth, search, chosen, choices, toggle }: PlaceRowProps) {
  const kind =
    node.level === "location"
      ? choiceLabel(choices, LOCATION_KIND_LIST, node.kind) || levelLabel(node.level)
      : levelLabel(node.level);
  return (
    <tr
      data-level={node.level}
      data-path={node.path}
      data-hid={node.hid}
      className={node.record_status === "active" ? undefined : "dim"}
      aria-current={node.hid === chosen ? "true" : undefined}
    >
      <th scope="row" className={`tree-name tree-depth-${drawnDepth(depth)}`}>
        {toggle ? (
          <button
            type="button"
            className="tree-toggle"
            aria-expanded={toggle.open}
            aria-label={`${toggle.open ? "Close" : "Open"} ${node.name}`}
            onClick={toggle.flip}
          >
            {toggle.open ? "▾" : "▸"}
          </button>
        ) : (
          <span className="tree-toggle tree-leaf" aria-hidden="true" />
        )}
        <Link to={{ pathname: placePath(node.level, node.hid), search }}>{node.name}</Link>
        {node.code && <span className="muted"> {node.code}</span>}
        {node.record_status !== "active" && (
          <span className="badge">{optionLabel(RECORD_STATUSES, node.record_status)}</span>
        )}
      </th>
      <td>{kind}</td>
      <td className="number" data-count="items">
        {countText(node.items)}
      </td>
      <td className="number" data-count="components">
        {countText(node.component_count)}
      </td>
    </tr>
  );
}

interface SiteInsideProps {
  site: TreeNode;
  depth: number;
  view: TreeView;
  turn: number;
  search: string;
  chosen: string;
  choices: readonly Choice[] | undefined;
}

/**
 * The locations of one site, fetched when the site is opened: the tree asked for again
 * with the site as its root, in the same view.
 */
function SiteInside({ site, depth, view, turn, search, chosen, choices }: SiteInsideProps) {
  const query = treeQuery(view, { root: site.hid });
  const inside = useLoad(`inside ${JSON.stringify(query)}`, (signal) =>
    api.request("get", "/api/v1/geography/tree", { query, signal }),
  );
  useReloadOn(turn, inside.reload);
  const locations = inside.data?.roots[0]?.children ?? [];
  const rows = treeRows(locations, new Set(), depth);
  const note = (text: string, status = false) => (
    <tr data-inside={site.hid}>
      <td
        colSpan={4}
        className={`muted tree-name tree-depth-${drawnDepth(depth)}`}
        {...(status ? { role: "status" } : {})}
      >
        {text}
      </td>
    </tr>
  );
  if (inside.error) {
    return (
      <tr data-inside={site.hid}>
        <td colSpan={4}>
          <Problem error={inside.error} />
        </td>
      </tr>
    );
  }
  if (!inside.data) return note("Loading…", true);
  if (rows.length === 0) return note(`No location is in ${site.name} in this view.`);
  return rows.map((row) => (
    <PlaceRow
      key={row.node.hid}
      node={row.node}
      depth={row.depth}
      search={search}
      chosen={chosen}
      choices={choices}
      toggle={null}
    />
  ));
}
