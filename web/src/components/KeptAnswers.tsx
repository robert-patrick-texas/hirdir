// 0.8.0: the long reports that are kept, and the check of them (P-142, P-157). The
// coverage report, the renewal worklist, the summary of the renewal alert and the capacity
// report are worked out ahead and given to every session alike while nothing has changed
// them. An Admin checks them here, which works each out anew and says whether any had
// differed.
// 0.9.11: the view each page opens with is worked out ahead by the second process and
// kept in the database, where the server finds it; any other view is in the server's
// memory alone (P-275, P-276). The table says which.

import { useState } from "react";
import { api, type Schemas } from "../api";
import { plural } from "../lib/format";
import { useAction, useLoad } from "../lib/hooks";
import { dateValue } from "../lib/sort";
import { useSorting } from "../lib/useSorting";
import { Problem } from "./Problem";
import { SortTh } from "./SortTh";
import { Time } from "./Time";

type Kept = Schemas["KeptAnswer"];
type Checked = Schemas["KeptCheck"];

/** What each kept report is called on its page. */
const REPORTS: Readonly<Record<string, string>> = {
  capacity: "Capacity",
  coverage: "Coverage",
  renewals: "Renewals worklist",
  renewal_alert: "Renewal alert",
};

export function reportLabel(report: string): string {
  return REPORTS[report] ?? report;
}

/** Where a kept report is kept: in the database, worked out ahead, or by the server. */
export function keptWhere(ahead: boolean): string {
  return ahead ? "In the database, worked out ahead" : "In the server's memory";
}

/** Admin → Settings: what is kept, and the button that checks it. */
export function KeptAnswers() {
  const kept = useLoad("kept-answers", (signal) =>
    api.request("get", "/api/v1/kept-answers", { signal }),
  );
  const check = useAction();
  const [found, setFound] = useState<Checked | null>(null);

  async function run() {
    setFound(null);
    const result = await check.run(() => api.request("post", "/api/v1/kept-answers/check", {}));
    if (!result.ok) return;
    setFound(result.value);
    kept.reload();
  }

  return (
    <section aria-labelledby="kept-answers" data-testid="kept-answers">
      <h2 id="kept-answers">Kept reports</h2>
      <p className="hint">
        The coverage report, the renewal worklist, the summary of the renewal alert and the capacity
        balance are worked out ahead by the background work, each night, when it starts and once
        nothing has changed for the time that reports_ahead_after_seconds says, and kept in the
        database: everyone is given the same answer while nothing has changed it. Any other view of
        them, and one that is asked for sooner, the server works out and keeps in its memory. The
        check works each kept answer out anew from the records, compares it with what was kept, and
        keeps the new one. None should differ: one that did is a defect to report.
      </p>
      <Problem error={check.error} />
      <p className="actions">
        <button type="button" className="primary" disabled={check.busy} onClick={run}>
          Check kept reports
        </button>
      </p>
      {check.busy && (
        <p role="status" className="muted loading-late">
          Working each one out anew…
        </p>
      )}
      {found && <CheckFound found={found} />}
      <Problem error={kept.error} />
      {kept.data && <KeptTable kept={kept.data} />}
    </section>
  );
}

/** What the check found: how many it checked, and each that differed. */
function CheckFound({ found }: { found: Checked }) {
  const differed = found.differed;
  return (
    <div
      role="status"
      data-testid="kept-check"
      data-checked={found.checked}
      data-differed={differed.length}
      data-overtaken={found.overtaken}
    >
      <p className={differed.length === 0 ? "alert alert-ok" : "alert alert-error"}>
        {plural(found.checked, "kept report")} checked at <Time at={found.checked_at} />.{" "}
        {differed.length === 0
          ? "None differed."
          : `${differed.length} differed from the answer worked out anew: a defect to report, with the report and the request each was of.`}
      </p>
      {found.overtaken && (
        <p className="alert alert-info" data-testid="kept-overtaken">
          Something was changed while the check worked, so it stopped there: every kept report is
          worked out again after a change, and what was not compared yet is given no more. Check
          again when the inventory is quiet.
        </p>
      )}
      {differed.length > 0 && (
        <ul data-testid="kept-differed">
          {differed.map((one) => (
            <li key={`${one.report} ${one.request}`} data-report={one.report}>
              {reportLabel(one.report)}, kept at <Time at={one.kept_at} />, for the request{" "}
              <span className="mono">{one.request}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** What is kept now, sorted by its headers: the table holds all of it. */
function KeptTable({ kept }: { kept: readonly Kept[] }) {
  const sorting = useSorting(kept, {
    report: (one) => reportLabel(one.report),
    request: (one) => one.request,
    kept_at: (one) => dateValue(one.kept_at),
    uses: (one) => one.uses,
    ahead: (one) => keptWhere(one.ahead),
  });
  if (kept.length === 0) {
    return (
      <p className="muted" data-testid="kept-none">
        Nothing is kept at the moment: each report is worked out when it is next asked for.
      </p>
    );
  }
  return (
    <div className="scroll">
      <table data-testid="kept-list">
        <caption className="visually-hidden">
          The reports that are kept, each with its request, when it was worked out, how many times
          the server has given it since, and where it is kept
        </caption>
        <thead>
          <tr>
            <SortTh sort={sorting} column="report">
              Report
            </SortTh>
            <SortTh sort={sorting} column="request">
              Request
            </SortTh>
            <SortTh sort={sorting} column="kept_at">
              Worked out
            </SortTh>
            <SortTh sort={sorting} column="uses" className="number">
              Given since
            </SortTh>
            <SortTh sort={sorting} column="ahead">
              Kept
            </SortTh>
          </tr>
        </thead>
        <tbody>
          {sorting.rows.map((one) => (
            <tr key={`${one.report} ${one.request}`} data-report={one.report}>
              <th scope="row">{reportLabel(one.report)}</th>
              <td className="mono">{one.request}</td>
              <td className="nowrap">
                <Time at={one.kept_at} />
              </td>
              <td className="number">{one.uses.toLocaleString("en-US")}</td>
              <td data-ahead={one.ahead}>{keptWhere(one.ahead)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
