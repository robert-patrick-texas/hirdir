// 0.9.17: what the pages of accounts say of roles and tokens, worked out before anything
// is sent (P-307, P-314, P-316). The server decides; these words say beforehand what it
// does.

/**
 * What a token made for an account that holds no role says, where it is shown once
 * (P-314): it is made, and refused until the account holds a role (P-299).
 */
export function tokenWaits(username: string): string {
  return `${username} holds no role, so this token is refused until it holds one: grant it a role under Roles, or put it in a group that grants one. The token works from then on.`;
}

/** One role an account holds, and where it comes from: a grant of its own, or a group's. */
export interface Source {
  role: string;
  /** The grant it comes from. */
  grantHid: string;
  /** The group whose grant it is, or null for a grant of the account's own. */
  groupHid: string | null;
}

/** A change that may take roles from accounts (P-314). */
export type RoleChange =
  /** A grant revoked: the account's own, or a group's, held by each member. */
  | { kind: "revoke"; grantHid: string }
  /** An account taken out of a group, or every member of a group deleted. */
  | { kind: "leave"; groupHid: string };

/** The roles an account still holds after a change, from where they come. */
export function remaining(sources: readonly Source[], change: RoleChange): Source[] {
  return sources.filter((source) =>
    change.kind === "revoke"
      ? source.grantHid !== change.grantHid
      : source.groupHid !== change.groupHid,
  );
}

/** Whether a change takes the last role of an account that holds one. */
export function leavesNoRole(sources: readonly Source[], change: RoleChange): boolean {
  return sources.length > 0 && remaining(sources, change).length === 0;
}

/** An account a change may leave with no role: what it is called, and what it is. */
export interface Holder {
  username: string;
  /** A person signs in; a service account and an agent hold tokens. */
  kind: string;
  sources: readonly Source[];
}

function listed(parts: readonly string[]): string {
  if (parts.length <= 1) return parts.join("");
  return `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

/**
 * What a confirmation says before a change that takes the last role from accounts, or
 * null where it leaves everybody with a role (P-314 (4)): `klee will hold no role and be
 * signed out`; for a group, each so left, named. A person is signed out at once; a
 * service account or an agent, which has no session, has its tokens refused.
 */
export function noRoleWords(holders: readonly Holder[], change: RoleChange): string | null {
  const left = holders.filter((holder) => leavesNoRole(holder.sources, change));
  if (left.length === 0) return null;
  const people = left.filter((holder) => holder.kind === "person").map((one) => one.username);
  const tokens = left.filter((holder) => holder.kind !== "person").map((one) => one.username);
  const sentences: string[] = [];
  if (people.length > 0) {
    sentences.push(
      `${listed(people)} will ${people.length === 1 ? "" : "each "}hold no role and be signed out`,
    );
  }
  if (tokens.length > 0) {
    const whose =
      tokens.length === 1
        ? `${tokens[0]} will hold no role, and its`
        : `${listed(tokens)} will each hold no role, and their`;
    sentences.push(`${whose} tokens will be refused`);
  }
  return `${sentences.join(". ")}.`;
}
