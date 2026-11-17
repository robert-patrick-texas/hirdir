import { Link } from "react-router";
import { api } from "../api";
import { useAuth } from "../auth";
import { ConfirmButton } from "../components/ConfirmButton";
import { Problem } from "../components/Problem";
import { HeadlineTotals } from "../components/Totals";
import { type ItemsView, itemsViewPath } from "../lib/filter";
import { plural } from "../lib/format";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { useSettings } from "../lib/lists";
import { assignmentPath, OPEN, UNASSIGNED, unassignedComponents } from "../lib/operators";
import { useSite } from "../lib/product";
import { allows, roleLabel } from "../lib/roles";
import { healthHrefOf, settingList } from "../lib/summary";

/**
 * What nobody of the team is assigned to look after, and what is under a label with
 * nobody behind it: the components of the blank row of the summary by operator, and
 * those of the view of open labels.
 */
function Assigned() {
  const byOperator = useLoad("home-by-operator", (signal) =>
    api.request("get", "/api/v1/reports/summary", { query: { by: "operator" }, signal }),
  );
  const unassigned = unassignedComponents(byOperator.data?.rows);
  const open = useLoad("home-open", (signal) =>
    api.request("get", "/api/v1/reports/summary", { query: { filter: OPEN }, signal }),
  );
  const waiting = open.data?.totals.component_count ?? 0;
  return (
    <>
      <Problem error={byOperator.error} />
      {byOperator.loading && !byOperator.data && (
        <p role="status" className="muted loading-late">
          Counting what nobody is assigned to…
        </p>
      )}
      {byOperator.data && (
        <p data-testid="unassigned" data-count={unassigned}>
          {unassigned > 0 ? (
            <>
              <Link to={assignmentPath(UNASSIGNED)}>
                {plural(unassigned, "component has", "components have")} no operator
              </Link>
              : nobody of the team is assigned to look after {unassigned === 1 ? "it" : "them"}.
            </>
          ) : (
            <span className="muted">Every component has an operator.</span>
          )}
          {open.data &&
            (waiting > 0 ? (
              <span data-testid="open-assignments" data-count={waiting}>
                {" "}
                <Link to={assignmentPath(OPEN)}>
                  {plural(waiting, "component is", "components are")} under an open label
                </Link>
                : an operator that nobody is behind for now.
              </span>
            ) : (
              <span className="muted" data-testid="open-assignments" data-count={0}>
                {" "}
                No label is open.
              </span>
            ))}
        </p>
      )}
      <Problem error={open.error} />
    </>
  );
}

/**
 * The headline of the summary, for the inventory as a list shows it by default: the
 * components beside the managed nodes, the support weight, and the components by health.
 * The server counts them. No money is shown here: that is in the management report.
 */
function Headline() {
  // 0.9.5: the totals from the plain summary, which is asked for first and alone, so
  // that it shows when its own answer comes (P-195). What nobody is assigned to, from the
  // summary by operator, is asked for after it, for the one sentence that needs it.
  const summary = useLoad("home-summary", (signal) =>
    api.request("get", "/api/v1/reports/summary", { signal }),
  );
  const settings = useSettings();
  return (
    <section aria-labelledby="headline">
      <h2 id="headline">The inventory in numbers</h2>
      <Problem error={summary.error} />
      {summary.loading && !summary.data && (
        <p role="status" className="muted loading-late">
          Counting…
        </p>
      )}
      {summary.data && (
        <HeadlineTotals
          totals={summary.data.totals}
          countKinds={settingList(settings.data, "count_kinds")}
          healthHref={healthHrefOf({ filter: null }, settings.data)}
        />
      )}
      {!summary.loading && <Assigned />}
      <p>
        <Link to="/reports/scoreboard" data-testid="scoreboard-link">
          The scoreboard
        </Link>
        : who looks after how much, and where, by operator and by site.
      </p>
      <p>
        <Link to="/reports">The summary</Link>, by vendor, owner, state, health and more, for any
        filter of the items. Drafts, retired records and archived items are left out here. Estimated
        value and annual support cost are in the{" "}
        <Link to="/reports/management">management report</Link>.
      </p>
    </section>
  );
}

interface AttentionProps {
  testId: string;
  /** What the report says of the list: how many, and the filter that lists them. */
  section: (ItemsView & { count: number }) | undefined;
  /** The link, for one and for many: "item in service has no cover". */
  one: string;
  many: string;
  /** What follows the link. */
  after: string;
  /** What to say when there is none. */
  none: string;
}

/** One count that wants attention, as a link to the items it counts. */
function Attention({ testId, section, one, many, after, none }: AttentionProps) {
  if (!section) return null;
  return (
    <li data-testid={testId} data-count={section.count}>
      {section.count > 0 ? (
        <>
          <Link to={itemsViewPath(section)}>{plural(section.count, one, many)}</Link>
          {after}
        </>
      ) : (
        <span className="muted">{none}</span>
      )}
    </li>
  );
}

/**
 * What wants attention of cover and of the end of support, as the two reports count it
 * for the inventory as a list shows it: each a link to its list in the grid of items.
 */
function Cover() {
  const coverage = useLoad("home-coverage", (signal) =>
    api.request("get", "/api/v1/reports/coverage", { query: { within_days: 90 }, signal }),
  );
  const endOfLife = useLoad("home-end-of-life", (signal) =>
    api.request("get", "/api/v1/reports/end-of-life", { query: { date: "ldos" }, signal }),
  );
  const days = endOfLife.data?.within_days ?? 730;
  return (
    <section aria-labelledby="cover">
      <h2 id="cover">Cover, and the end of support</h2>
      <Problem error={coverage.error} />
      <Problem error={endOfLife.error} />
      {((coverage.loading && !coverage.data) || (endOfLife.loading && !endOfLife.data)) && (
        <p role="status" className="muted loading-late">
          Counting…
        </p>
      )}
      <ul data-testid="home-cover">
        <Attention
          testId="home-uncovered"
          section={coverage.data?.sections.uncovered}
          one="item in service has no cover"
          many="items in service have no cover"
          after=": no contract covers them today."
          none="Every item in service is under a contract."
        />
        <Attention
          testId="home-expiring"
          section={coverage.data?.sections.expiring}
          one="item in service has cover that runs out within 90 days"
          many="items in service have cover that runs out within 90 days"
          after="."
          none="No cover of an item in service runs out within 90 days."
        />
        <Attention
          testId="home-ldos-past"
          section={endOfLife.data?.sections.past}
          one="item is past its last day of support"
          many="items are past their last day of support"
          after="."
          none="No item is past its last day of support."
        />
        <Attention
          testId="home-ldos-approaching"
          section={endOfLife.data?.sections.approaching}
          one="item approaches its last day of support"
          many="items approach their last day of support"
          after={`: it is within ${plural(days, "day")}.`}
          none={`No item approaches its last day of support within ${plural(days, "day")}.`}
        />
      </ul>
      <p>
        <Link to="/reports/coverage">The coverage report</Link> and the{" "}
        <Link to="/reports/end-of-life">end-of-life report</Link> count the same for any filter of
        the items, and by fiscal year.
      </p>
    </section>
  );
}

/** The first page: the headline totals, where everything is, and the reader's own account. */
export function Home() {
  useTitle("Home");
  const { user, signOut, signOutEverywhere } = useAuth();
  const { productName } = useSite();
  const action = useAction();
  const name = user.display_name || user.username;

  return (
    <>
      <h1>Welcome, {name}</h1>
      {user.role === null ? (
        <section aria-labelledby="no-role">
          <h2 id="no-role">You have no role yet</h2>
          <p>
            You are signed in as <strong>{user.username}</strong>, but no role has been granted to
            you, so there is nothing for you to see here yet.
          </p>
          <p>Ask an administrator of {productName} to grant you a role, then reload this page.</p>
        </section>
      ) : (
        <>
          <Headline />
          <Cover />
          <section aria-labelledby="inventory">
            <h2 id="inventory">Inventory</h2>
            <ul>
              <li>
                <Link to="/items">Items</Link>: everything that is tracked, in one grid
              </li>
              <li>
                <Link to="/groups">Groups</Link>: stacks, clusters and controller domains, with
                their members
              </li>
              <li>
                <Link to="/addresses">Addresses</Link> and the <Link to="/networks">networks</Link>{" "}
                they are under
              </li>
              <li>
                <Link to="/catalog">Catalog</Link>: what is true of every item of one model
              </li>
              <li>
                <Link to="/vendors">Vendors</Link>, each with its portfolio, and{" "}
                <Link to="/owners">owners</Link>
              </li>
              <li>
                <Link to="/contracts">Contracts</Link> and the{" "}
                <Link to="/agreements">support agreements</Link> that group them, with the items
                each covers
              </li>
              <li>
                <Link to="/purchases">Purchases</Link>: requests, their lines, and receiving what
                arrived
              </li>
              <li>
                <Link to="/systems">External systems</Link>, and what is registered with each
              </li>
              <li>
                <Link to="/capacity">Capacity</Link>: demand beside supply, and the balance
              </li>
              <li>
                <Link to="/reports">Reports</Link>: the summary, the{" "}
                <Link to="/reports/management">management report</Link>,{" "}
                <Link to="/reports/coverage">coverage</Link>,{" "}
                <Link to="/reports/end-of-life">end of life</Link>,{" "}
                <Link to="/reports/replacements">replacements</Link>, and the{" "}
                <Link to="/reports/duplicates">addresses held more than once</Link>
              </li>
              <li>
                <Link to="/admin/tags">Tags</Link>, <Link to="/admin/choices">choices</Link> and the{" "}
                <Link to="/admin/lifecycle-rules">lifecycle rules</Link>
              </li>
              <li>
                <Link to="/import">Import</Link>: load a CSV or JSON file, with a preview first
              </li>
              <li>
                <Link to="/audit">The audit trail</Link>
              </li>
              {allows(user.role, "admin") && (
                <li>
                  <Link to="/admin/users">Users, groups and roles</Link>, and the{" "}
                  <Link to="/admin/settings">settings</Link>
                </li>
              )}
              <li>
                <Link to="/about">What is running</Link>
              </li>
            </ul>
          </section>
        </>
      )}

      <section aria-labelledby="account">
        <h2 id="account">Your account</h2>
        <dl className="facts">
          <dt>Username</dt>
          <dd>{user.username}</dd>
          <dt>Name</dt>
          <dd>{user.display_name || <span className="muted">—</span>}</dd>
          <dt>Role</dt>
          <dd>{roleLabel(user.role)}</dd>
          <dt>Groups</dt>
          <dd>
            {user.groups.length > 0 ? (
              user.groups.map((group) => group.name).join(", ")
            ) : (
              <span className="muted">—</span>
            )}
          </dd>
        </dl>
        <Problem error={action.error} />
        <p className="actions">
          <button type="button" onClick={signOut}>
            Sign out
          </button>
          <ConfirmButton
            label="Sign out everywhere"
            title="Sign out everywhere?"
            confirmLabel="Sign out everywhere"
            onConfirm={() => action.run(signOutEverywhere)}
          >
            <p>
              This ends every session you have, in every browser and on every machine, this one
              included. You will have to sign in again.
            </p>
          </ConfirmButton>
        </p>
      </section>
    </>
  );
}
