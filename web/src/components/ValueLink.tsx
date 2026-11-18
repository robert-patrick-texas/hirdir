// 0.9.7: a value of a table that names another record is a link to its page (P-232).

import type { ReactNode } from "react";
import { Link } from "react-router";
import { kindPath } from "../lib/preview";

/**
 * The name of a record, as a link to its page in the style of the text around it: by
 * the kind the audit trail names it by and its HID. A record with no page, or none, is
 * its name alone. `admin` opens the pages only an Admin may open, on a page for an Admin.
 */
export function ValueLink({
  kind,
  hid,
  admin = false,
  children,
}: {
  kind: string;
  hid: string | null | undefined;
  admin?: boolean;
  children?: ReactNode;
}) {
  const path = kindPath(kind, hid, admin);
  if (path === null) return <>{children}</>;
  return (
    <Link className="value-link" to={path}>
      {children}
    </Link>
  );
}
