// 0.9.14: a username refused because a retired account has it (P-296). A retired account
// keeps its username, since the audit trail is read by it; the form says so under the
// username and links to that account, where it is renamed or brought back.

import { Link } from "react-router";
import type { ApiError } from "../api/client";
import { retiredAccount } from "../lib/linked";

export function RetiredHasIt({ error }: { error: ApiError | null }) {
  const account = retiredAccount(error);
  if (!account) return null;
  return (
    <p className="hint" data-testid="retired-has-it">
      The retired account{" "}
      <Link to={`/admin/users/${encodeURIComponent(account.hid)}`}>{account.label}</Link> has this
      username. Open it to give it another username, which frees this one, or to bring it back.
    </p>
  );
}
