// 0.9.13: the gaps of a list of people, one press away (P-280): Show, with a link to the
// whole list and one to each gap, the users with no contact or the contacts behind no
// operator. Each is an address, so that a link to a gap can be sent to a colleague; the
// one on show is marked, in words for a screen reader.

import { Fragment } from "react";
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
      <span className="gap-links-label">Show</span>{" "}
      {links.map((link, index) => (
        <Fragment key={link.to}>
          {index > 0 && <span aria-hidden="true"> · </span>}
          <Link to={link.to} aria-current={link.current ? "page" : undefined}>
            {link.text}
          </Link>
        </Fragment>
      ))}
    </nav>
  );
}
