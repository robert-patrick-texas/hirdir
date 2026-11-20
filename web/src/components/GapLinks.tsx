// 0.9.13: the gaps of a list of people, one press away (P-280): Show, with a link to the
// whole list and one to each gap, the users with no contact or the contacts behind no
// operator. Each is an address, so that a link to a gap can be sent to a colleague; the
// one on show is marked, as the page is in a menu, and in words for a screen reader.

import { useCallback, useState } from "react";
import { Link } from "react-router";
import type { FilterNode } from "../lib/filter";
import type { ListRequest } from "../lib/gridQuery";
import { gapShown } from "../lib/onboarding";

export interface GapLink {
  text: string;
  /** The address of the list narrowed so, as a path of the app with its query. */
  to: string;
  current: boolean;
}

interface GapLinksProps {
  label: string;
  links: readonly GapLink[];
  /** A link was pressed: a grid starts again on its gap, as the address is the same. */
  onPress?: () => void;
}

export function GapLinks({ label, links, onPress }: GapLinksProps) {
  return (
    <nav className="gap-links" aria-label={label} data-testid="gap-links">
      <span className="gap-links-label" aria-hidden="true">
        Show
      </span>
      <ul>
        {links.map((link) => (
          <li key={link.to}>
            <Link
              to={link.to}
              aria-current={link.current ? "page" : undefined}
              {...(onPress ? { onClick: onPress } : {})}
            >
              {link.text}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** What a page with a grid needs of its gaps: the grid's key, its reads, and which is on show. */
export interface GridGaps {
  /** The key of the grid: a new one on each press of a gap, so the grid starts on it. */
  gridKey: string;
  /** Hear what the grid asks the server for, to know which gap it shows, if any. */
  heard: (request: ListRequest) => void;
  /** Whether a gap, by the short filter it starts the grid with, is the one on show. */
  current: (gap: string) => boolean;
  /** A gap was pressed. */
  pressed: () => void;
}

/**
 * The gaps of a grid whose filter can also be changed in its own box (P-280): a press of
 * a gap starts the grid again on it, even where the address is the same, and a gap is
 * marked as on show only while the grid's filter is that gap's, as the grid last asked
 * the server, or before it has, as the address started it.
 */
export function useGridGaps(startFilter: string | null): GridGaps {
  const [turn, setTurn] = useState(0);
  // What the grid last asked for; undefined until it asks, after each start.
  const [asked, setAsked] = useState<FilterNode | null | undefined>(undefined);
  const heard = useCallback(
    (request: ListRequest) =>
      // The same filter asked again, for the next page of rows, changes nothing on show.
      setAsked((was) =>
        was !== undefined && JSON.stringify(was) === JSON.stringify(request.filter)
          ? was
          : request.filter,
      ),
    [],
  );
  const pressed = useCallback(() => {
    setTurn((count) => count + 1);
    setAsked(undefined);
  }, []);
  return {
    gridKey: `${startFilter ?? ""} ${turn}`,
    heard,
    current: (gap) => gapShown(gap, asked, startFilter),
    pressed,
  };
}
