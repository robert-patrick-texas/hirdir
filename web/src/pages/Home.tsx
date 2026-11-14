import { Link } from "react-router";
import { api } from "../api";
import { useAuth } from "../auth";
import { ConfirmButton } from "../components/ConfirmButton";
import { Problem } from "../components/Problem";
import { HeadlineTotals } from "../components/Totals";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { useSettings } from "../lib/lists";
import { allows, roleLabel } from "../lib/roles";
import { settingList } from "../lib/summary";

/**
 * The headline of the summary, for the inventory as a list shows it by default: the
 * components beside the managed nodes, the support weight, and the components by health.
 * The server counts them. No money is shown here: that is in the management report.
 */
function Headline() {
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
        />
      )}
      <p>
        <Link to="/reports">The summary</Link>, by vendor, owner, state, health and more, for any
        filter of the items. Drafts, retired records and archived items are left out here. Estimated
        value and annual support cost are in the{" "}
        <Link to="/reports/management">management report</Link>.
      </p>
    </section>
  );
}

/** The first page: the headline totals, where everything is, and the reader's own account. */
export function Home() {
  useTitle("Home");
  const { user, signOut, signOutEverywhere } = useAuth();
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
          <p>Ask an administrator of hirdir to grant you a role, then reload this page.</p>
        </section>
      ) : (
        <>
          <Headline />
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
                <Link to="/vendors">Vendors</Link> and <Link to="/owners">owners</Link>
              </li>
              <li>
                <Link to="/reports">Reports</Link>: the summary, the{" "}
                <Link to="/reports/management">management report</Link>, and the{" "}
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
