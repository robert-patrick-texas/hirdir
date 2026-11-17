// The rank and the bars of a table of a report (P-178, P-180): a Rank column first, and
// beside each count a bar as long as the count is to the largest of its column. The bar
// is a box of the stylesheet in the accent of the theme, for the eye alone: the number is
// always written beside it, and a screen reader reads the number once and the bar not
// at all. Its length is set on the element, which the content security policy allows,
// as it allows an operator's colour; no script is written into the page.

import type { CSSProperties } from "react";
import { Link } from "react-router";
import type { Ranking } from "../lib/rank";

/**
 * The header of the Rank column. What the rank is by is said beneath the table and kept in
 * `data-rank-by`, and not in the name of the header, which would then share the name of
 * the header of that column.
 */
export function RankHead<T>({ ranking }: { ranking: Ranking<T> }) {
  return (
    <th scope="col" className="number rank" data-rank-by={ranking.column}>
      Rank
    </th>
  );
}

/** The rank of a row: blank for the blank row, which has none. */
export function RankCell<T>({ ranking, row }: { ranking: Ranking<T>; row: T }) {
  const rank = ranking.rank(row);
  return (
    <td className="number rank" data-measure="rank">
      {rank === null ? "" : rank}
    </td>
  );
}

interface BarProps {
  /** How long the bar is, from 0 to 1 of the longest the column draws. */
  share: number;
  /** The number, as it is written. */
  text: string;
  /** How many characters the longest number of the column has, so that the bars line up. */
  figure: number;
  /** A class for the number, where a page looks for it. */
  figureClass?: string;
  /** Where the number leads, where it is a link: the list of what it counts. */
  href?: string | null | undefined;
}

/** A number with a bar beside it. Nothing of the bar is read: the number says it. */
export function Bar({ share, text, figure, figureClass, href }: BarProps) {
  const length = Math.max(0, Math.min(1, share));
  const fill: CSSProperties = { inlineSize: `${(length * 100).toFixed(2)}%` };
  return (
    <span className="counted">
      <span className="bar" aria-hidden="true">
        <span className={length > 0 ? "bar-fill bar-some" : "bar-fill"} style={fill} />
      </span>
      <span
        className={figureClass ? `figure ${figureClass}` : "figure"}
        style={{ minInlineSize: `${figure}ch` }}
      >
        {href && text ? <Link to={href}>{text}</Link> : text}
      </span>
    </span>
  );
}

/** A count of a row in a column of a ranked table, with its bar, and a link where given. */
export function Counted<T>({
  ranking,
  column,
  row,
  href,
}: {
  ranking: Ranking<T>;
  column: string;
  row: T;
  href?: string | null | undefined;
}) {
  return (
    <Bar
      share={ranking.share(column, row)}
      text={ranking.text(column, row)}
      figure={ranking.figure(column)}
      href={href}
    />
  );
}

/**
 * What the rank of a table is by, beneath it: the column of counts it is sorted by, or
 * the one named for it while it is sorted by none of them.
 */
export function RankNote<T>({
  ranking,
  fallback,
  blank,
}: {
  ranking: Ranking<T>;
  /** What the column the rank is by at first is called. */
  fallback: string;
  /** What the blank row is called, where the table has one. */
  blank?: string;
}) {
  return (
    <p className="hint" data-testid="rank-note" data-rank-by={ranking.column}>
      Ranked by {ranking.label}, 1 for the most: the rank follows the column of counts the table is
      sorted by, and is by {fallback} while it is sorted by none of them. Two of one count share a
      rank{blank ? `, and the row “${blank}” has none` : ""}. Each bar is as long as its count is to
      the largest of its column.
    </p>
  );
}
