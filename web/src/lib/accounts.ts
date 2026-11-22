// 0.9.17: what the pages of accounts say of their kind, their roles and their tokens,
// worked out before anything is sent (P-307, P-314, P-316). The server decides; these
// words say beforehand what it does.

import type { Schemas } from "../api/client";
import { ROLES, roleLabel } from "./roles";

/** The kind of an account (P-316): a person's, a service's or an agent's. */
export type Kind = Schemas["UserOut"]["kind"];

export const KINDS: readonly Kind[] = ["person", "service", "agent"];

/** The kind in a word, as the Kind column of the list of users writes it. */
export function kindWord(kind: string): string {
  if (kind === "service") return "Service";
  if (kind === "agent") return "Agent";
  return "Person";
}

/** The kind as the page of an account names it. */
export function kindName(kind: string): string {
  return kind === "service" ? "Service account" : kindWord(kind);
}

/** What New user says of the kind chosen. */
export function kindHint(kind: string): string {
  if (kind === "service") {
    return "For automation that does a fixed job, application to application. It cannot sign in with an access code: it holds tokens. It is no person, and has no contact and no operator.";
  }
  if (kind === "agent") {
    return "For a tool that decides what to change, as a person does. It holds tokens, is answerable to a person, holds no more than their role and is never Admin. It has no contact and no operator.";
  }
  return "Somebody who signs in with an access code.";
}

/** Whether an account holds tokens rather than signing in: a service account or an agent. */
export function holdsTokens(kind: string): boolean {
  return kind === "service" || kind === "agent";
}

/** The roles an account of a kind may be given: every one, and never Admin to an agent. */
export function rolesFor(kind: string): readonly string[] {
  return kind === "agent" ? ROLES.filter((role) => role !== "admin") : ROLES;
}

/**
 * What a token made for an account that holds no role says, where it is shown once
 * (P-314): it is made, and refused until the account holds a role (P-299).
 */
export function tokenWaits(username: string): string {
  return `${username} holds no role, so this token is refused until it holds one: grant it a role under Roles, or put it in a group that grants one. The token works from then on.`;
}

/** An account as far as its role and its person go. */
type Holding = Pick<
  Schemas["UserOut"],
  "username" | "kind" | "role" | "role_in_force" | "role_capped_by" | "answerable"
>;

/** The person an agent is answerable to, by username, or "its person" where it is not known. */
function personOf(user: Pick<Holding, "answerable">): string {
  return user.answerable?.username ?? "its person";
}

/**
 * Why the tokens of an agent are refused for its person (P-316), or null where they
 * are not: the person holds no role, is disabled, or is retired.
 */
export function personRefuses(user: Pick<Holding, "role_capped_by" | "answerable">): string | null {
  const person = personOf(user);
  if (user.role_capped_by === "person_no_role") return `${person} holds no role`;
  if (user.role_capped_by === "person_disabled") return `${person} is disabled`;
  if (user.role_capped_by === "person_retired") return `${person} is retired`;
  return null;
}

/**
 * What a new token of an account says, where it is shown once, or null where the token
 * works (P-314 (3)): it is refused until the account holds a role, or, of an agent,
 * while its person cannot answer for it.
 */
export function tokenRefused(user: Holding): string | null {
  if (!user.role) return tokenWaits(user.username);
  const why = personRefuses(user);
  if (user.kind === "agent" && why !== null) {
    return `This token is refused while ${why}: ${user.username} answers for nothing more than its person does. It works once ${personOf(user)} can answer for it.`;
  }
  return null;
}

/**
 * The role an agent is held to and why, beside the role it holds (P-316 (4)), or null
 * where nothing holds it lower: `held to View-only by sam's role`.
 */
export function cappedWords(user: Holding): string | null {
  if (user.kind !== "agent") return null;
  const capped = user.role_capped_by;
  switch (capped) {
    case null:
      return null;
    case "person_role":
      return `held to ${roleLabel(user.role_in_force)} by ${personOf(user)}'s role`;
    // An agent that holds Admin all the same, as from a database edited by hand.
    case "never_admin":
      return `held to ${roleLabel(user.role_in_force)}: an agent is never Admin`;
    case "person_no_role":
    case "person_disabled":
    case "person_retired":
      return `its tokens are refused while ${personRefuses(user) ?? "its person cannot answer for it"}`;
    default: {
      // Every value the server answers has its words: a new one fails the type check.
      const unknown: never = capped;
      return unknown;
    }
  }
}

/** One role an account holds, and where it comes from: a grant of its own, or a group's. */
export type Source = Schemas["UserGrant"];

/** Where a role comes from, in words: of its own, or through a group, named. */
export function sourceWords(source: Source): string {
  return source.group ? `through ${source.group.name}` : "of its own";
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
      ? source.hid !== change.grantHid
      : source.group?.hid !== change.groupHid,
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
  grants: readonly Source[];
}

function listed(parts: readonly string[]): string {
  if (parts.length <= 1) return parts.join("");
  return `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

/** The accounts a change leaves with no role, of those given. */
export function leftWithNone<T extends Holder>(holders: readonly T[], change: RoleChange): T[] {
  return holders.filter((holder) => leavesNoRole(holder.grants, change));
}

/**
 * What a confirmation says before a change that takes the last role from accounts, or
 * null where it leaves everybody with a role (P-314 (4)): `klee will hold no role and be
 * signed out`; for a group, each so left, named. A person is signed out at once; a
 * service account or an agent, which has no session, has its tokens refused.
 */
export function noRoleWords(holders: readonly Holder[], change: RoleChange): string | null {
  const left = leftWithNone(holders, change);
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
