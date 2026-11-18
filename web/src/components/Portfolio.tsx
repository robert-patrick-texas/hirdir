// The portfolio of a vendor: everything from one vendor in one place, as the server
// counts it. The totals, the four kinds, the models with their dates and their cover,
// the vendor's items as a grid, which is the item list with the filter the portfolio
// gives, its own filter box narrowing within them, and is exported like any other: the
// working list for a renewal; then the agreements, the contracts and the capacity lines.

import { useMemo } from "react";
import { useSearchParams } from "react-router";
import { api } from "../api";
import { viewFilter } from "../lib/filter";
import { useLoad } from "../lib/hooks";
import { useChoices, useMoney } from "../lib/lists";
import { CheckField } from "./Field";
import { ItemsGrid } from "./ItemsGrid";
import { PortfolioCounts } from "./PortfolioTables";
import { Problem } from "./Problem";

/** The portfolio of one vendor, for the view the two switches choose. */
export function VendorPortfolio({ vendor }: { vendor: { hid: string; name: string } }) {
  const [params, setParams] = useSearchParams();
  const includeArchived = params.get("archived") === "1";
  const includeDrafts = params.get("drafts") === "1";
  const portfolio = useLoad(
    `portfolio ${vendor.hid} ${includeArchived} ${includeDrafts}`,
    (signal) =>
      api.request("get", "/api/v1/vendors/{hid}/portfolio", {
        path: { hid: vendor.hid },
        query: {
          ...(includeArchived ? { include_archived: true } : {}),
          ...(includeDrafts ? { include_drafts: true } : {}),
        },
        signal,
      }),
  );
  const money = useMoney();
  const choices = useChoices();
  const data = portfolio.data;
  const within = useMemo(
    () => ({ filter: viewFilter(data?.filter), includeArchived, includeDrafts }),
    [data?.filter, includeArchived, includeDrafts],
  );

  function show(next: { archived?: boolean; drafts?: boolean }) {
    const archived = next.archived ?? includeArchived;
    const drafts = next.drafts ?? includeDrafts;
    setParams({ ...(archived ? { archived: "1" } : {}), ...(drafts ? { drafts: "1" } : {}) });
  }

  return (
    <section aria-labelledby="portfolio" data-testid="portfolio">
      <h2 id="portfolio">Portfolio{data ? `, as of ${data.as_of}` : ""}</h2>
      <p>
        Everything {vendor.name} makes or provides, in one place: the working list for planning a
        renewal. Covered and not covered count the major items that a contract covers today.
      </p>
      <div className="inline">
        <CheckField
          label="Include archived"
          name="include_archived"
          checked={includeArchived}
          onChange={(on) => show({ archived: on })}
        />
        <CheckField
          label="Include drafts"
          name="include_drafts"
          checked={includeDrafts}
          onChange={(on) => show({ drafts: on })}
        />
      </div>
      <Problem error={portfolio.error} />
      {portfolio.loading && !data && (
        <p role="status" className="muted loading-late">
          Counting…
        </p>
      )}
      {data && (
        <PortfolioCounts portfolio={data} money={money} choices={choices.data}>
          {/* 0.9.6: the items come before the agreements and the contracts (P-211). */}
          <section aria-labelledby="portfolio-items-heading">
            <h3 id="portfolio-items-heading">Its items</h3>
            <p className="hint">
              The item list, for the models of {vendor.name}. What is typed in its filter narrows
              within them, as <span className="mono">effective.ldos:lt:2027-12-31</span> for those
              that lose support before then, with the contracts that cover each. Export CSV or
              Export JSON writes these rows with the columns on show: add Covered until, Contracts
              and the money columns under Columns for a renewal list.
            </p>
            <ItemsGrid
              id="vendor-items"
              within={within}
              shown={["covered", "covered_until", "contract.number"]}
              filterBox
            />
          </section>
        </PortfolioCounts>
      )}
    </section>
  );
}
