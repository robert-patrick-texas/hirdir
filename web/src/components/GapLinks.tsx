// 0.9.13: the gaps of a list of people, one press away (P-280): Show, with a link to the
// whole list and one to each gap, the users with no contact or the contacts behind no
// operator. Each is an address, so that a link to a gap can be sent to a colleague; the
// one on show is marked, as the page is in a menu, and in words for a screen reader.

import { Link } from "react-router";

export interface GapLink {
  text: string;
  /** The address of the list narrowed so, as a path of the app with its query. */
  to: string;
  current: boolean;
}

export function GapLinks({ label, links }: { label: string; links: readonly GapLink[] }) {
  return (
    <nav className="gap-links" aria-label={label} data-testid="gap-links">
      <span className="gap-links-label" aria-hidden="true">
        Show
      </span>
      <ul>
        {links.map((link) => (
          <li key={link.to}>
            <Link to={link.to} aria-current={link.current ? "page" : undefined}>
              {link.text}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
