// 0.9.6 (P-214): what the form of a contract's renewal says under its button: how many
// coverages follow into the new term, how many of the items it covers are marked not to
// be renewed, and how many coverages begin with the new term or end on a day of their
// own. Every number is the server's, a count of a list by a filter; nothing is worked
// out here.

import { Link } from "react-router";
import { api } from "../api";
import {
  type Contract,
  flaggedFilter,
  flaggedItemsPath,
  flaggedWords,
  renewScopeFilters,
} from "../lib/contracts";
import type { FilterNode } from "../lib/filter";
import { plural, today } from "../lib/format";
import { useLoad } from "../lib/hooks";
import { Problem } from "./Problem";

interface Counts {
  follow: number;
  begin: number;
  ownEnd: number;
  flagged: number;
}

/** How many of the items it covers today are marked not to be renewed, by the server. */
async function countFlagged(contractHid: string, signal: AbortSignal): Promise<number> {
  const page = await api.request("get", "/api/v1/items", {
    query: { filter: JSON.stringify(flaggedFilter(contractHid)), limit: 1 },
    signal,
  });
  return page.total;
}

/**
 * A link to the items it covers, further down this page. The page's own address with the
 * section's id, as the section links of an item (P-189): a bare `#…` is read against the
 * document's base, and would leave the page, and what was typed in the form.
 */
function CoverageLink() {
  const here = `${window.location.pathname}${window.location.search}`;
  return <a href={`${here}#contract-coverage`}>The items it covers</a>;
}

/** The contract's own last day in force, or blank for a term that names none. */
function lastDay(contract: Contract): string {
  const value = contract.effective.ends_on.value;
  return typeof value === "string" ? value : "";
}

/** What is said of the items marked not to be renewed, with a link to them. */
function Flagged({ contract, flagged, end }: { contract: Contract; flagged: number; end: string }) {
  const words = flaggedWords(flagged, end);
  if (words.link === null) return words.text;
  return (
    <>
      <Link to={flaggedItemsPath(contract.hid)}>{words.link}</Link>
      {words.text}
    </>
  );
}

interface RenewScopeProps {
  contract: Contract;
  /**
   * How many times the coverage was changed on the page: a change of coverage does not
   * move the contract's version, and the counts are read again with it.
   */
  turn?: number;
}

export function RenewScope({ contract, turn = 0 }: RenewScopeProps) {
  const end = lastDay(contract);
  const day = today();
  const found = useLoad<Counts | null>(
    `renew-scope ${contract.hid} ${contract.row_version} ${end} ${turn}`,
    async (signal) => {
      // A term that names no end: what is marked is counted all the same (P-214).
      if (end === "") {
        return {
          follow: 0,
          begin: 0,
          ownEnd: 0,
          flagged: await countFlagged(contract.hid, signal),
        };
      }
      const filters = renewScopeFilters(end, day);
      const coverages = async (filter: FilterNode) =>
        (
          await api.request("get", "/api/v1/contracts/{hid}/coverage", {
            path: { hid: contract.hid },
            query: { filter: JSON.stringify(filter), limit: 1 },
            signal,
          })
        ).total;
      const [follow, begin, ownEnd, flagged] = await Promise.all([
        coverages(filters.follow),
        coverages(filters.begin),
        coverages(filters.ownEnd),
        countFlagged(contract.hid, signal),
      ]);
      return { follow, begin, ownEnd, flagged };
    },
  );
  const counts = found.data;
  if (end === "") {
    const flagged = counts?.flagged ?? null;
    return (
      <div className="renew-scope" aria-live="polite">
        <Problem error={found.error} />
        <p className="hint" data-testid="renew-no-end">
          The present term names no end: <strong>{plural(contract.items_in_scope, "item")}</strong>{" "}
          in scope {contract.items_in_scope === 1 ? "follows" : "follow"}
          {flagged !== null && flagged > 0 ? ", but for those marked not to be renewed." : "."}{" "}
          <CoverageLink />
        </p>
        {flagged !== null && (
          <p data-testid="renew-flagged" data-count={flagged}>
            <Flagged contract={contract} flagged={flagged} end={end} />
          </p>
        )}
      </div>
    );
  }
  return (
    <div className="renew-scope" aria-live="polite">
      <Problem error={found.error} />
      {found.loading && !counts && (
        <p role="status" className="muted loading-late">
          Counting what follows…
        </p>
      )}
      {counts && (
        <ul aria-label="What the renewal carries">
          <li data-testid="renew-follow" data-count={counts.follow}>
            <strong>{plural(counts.follow, "coverage")}</strong>{" "}
            {counts.follow === 1 ? "has" : "have"} the contract&apos;s period and{" "}
            {counts.follow === 1 ? "follows" : "follow"} into the new term
            {counts.flagged > 0 ? ", but for those of the items marked not to be renewed." : "."}
          </li>
          <li data-testid="renew-flagged" data-count={counts.flagged}>
            <Flagged contract={contract} flagged={counts.flagged} end={end} />
          </li>
          <li data-testid="renew-begin" data-count={counts.begin}>
            <strong>{plural(counts.begin, "coverage")}</strong>{" "}
            {counts.begin === 1 ? "begins" : "begin"} after {end}, with the new term.
          </li>
          {counts.ownEnd > 0 && (
            <li data-testid="renew-own-end" data-count={counts.ownEnd}>
              {plural(counts.ownEnd, "coverage")} {counts.ownEnd === 1 ? "ends" : "end"} on a day of{" "}
              {counts.ownEnd === 1 ? "its" : "their"} own by {end}, and{" "}
              {counts.ownEnd === 1 ? "does" : "do"} not follow.
            </li>
          )}
        </ul>
      )}
      <p>
        <CoverageLink />, with the days of each.
      </p>
    </div>
  );
}
