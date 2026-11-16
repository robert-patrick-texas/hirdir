// 0.8.0: the long reports that are kept, and the check of them (P-142, P-157). The
// coverage report, the renewal worklist, the summary of the renewal alert and the capacity
// report are worked out ahead and given to every session alike while nothing has changed
// them. They are kept in the server's memory, which `hirdir admin` cannot see: an Admin
// checks them here, which works each out anew and says whether any had differed.

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
        balance are worked out each night and when the server starts, and kept: everyone is given
        the same answer while nothing has changed it, and any audited change has them worked out
        again. The check works each kept answer out anew from the records, compares it with what was
        kept, and keeps the new one. None should differ: one that did is a defect to report.
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
    >
      <p className={differed.length === 0 ? "alert alert-ok" : "alert alert-error"}>
        {plural(found.checked, "kept report")} checked at <Time at={found.checked_at} />.{" "}
        {differed.length === 0
          ? "None differed."
          : `${differed.length} differed from the answer worked out anew: a defect to report, with the report and the request each was of.`}
      </p>
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
          The reports that are kept, each with its request, when it was worked out and how many
          times it has been given since
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
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
