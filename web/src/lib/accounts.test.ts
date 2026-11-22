import { describe, expect, it } from "vitest";
import {
  type Holder,
  leavesNoRole,
  noRoleWords,
  remaining,
  type Source,
  tokenWaits,
} from "./accounts";

const OWN: Source = { role: "viewer", grantHid: "R1", groupHid: null };
const TEAM: Source = { role: "inventory", grantHid: "R2", groupHid: "G1" };
const TEAM_TOO: Source = { role: "viewer", grantHid: "R3", groupHid: "G1" };
const DESK: Source = { role: "viewer", grantHid: "R4", groupHid: "G2" };

describe("a token made for an account that holds no role (P-314)", () => {
  it("says it is refused until the account holds one, and how one is given", () => {
    expect(tokenWaits("svc-sync")).toBe(
      "svc-sync holds no role, so this token is refused until it holds one: grant it a role under Roles, or put it in a group that grants one. The token works from then on.",
    );
  });
});

describe("what a change leaves of the roles of an account (P-314)", () => {
  it("takes away the grant revoked, the account's own or a group's", () => {
    expect(remaining([OWN, TEAM], { kind: "revoke", grantHid: "R1" })).toEqual([TEAM]);
    expect(remaining([OWN, TEAM], { kind: "revoke", grantHid: "R2" })).toEqual([OWN]);
  });

  it("takes away every role of the group left, and no other", () => {
    expect(remaining([TEAM, TEAM_TOO, DESK], { kind: "leave", groupHid: "G1" })).toEqual([DESK]);
    // A grant of its own is no group's.
    expect(remaining([OWN], { kind: "leave", groupHid: "G1" })).toEqual([OWN]);
  });

  it("leaves no role only where the last goes, from an account that held one", () => {
    expect(leavesNoRole([TEAM, TEAM_TOO], { kind: "leave", groupHid: "G1" })).toBe(true);
    expect(leavesNoRole([TEAM, TEAM_TOO], { kind: "revoke", grantHid: "R2" })).toBe(false);
    expect(leavesNoRole([OWN, TEAM], { kind: "leave", groupHid: "G1" })).toBe(false);
    expect(leavesNoRole([], { kind: "leave", groupHid: "G1" })).toBe(false);
  });
});

describe("what a confirmation says of whom a change leaves with no role (P-314)", () => {
  const klee: Holder = { username: "klee", kind: "person", sources: [TEAM] };
  const sroe: Holder = { username: "sroe", kind: "person", sources: [TEAM, TEAM_TOO] };
  const jdoe: Holder = { username: "jdoe", kind: "person", sources: [OWN, TEAM] };
  const sync: Holder = { username: "svc-sync", kind: "service", sources: [TEAM] };
  const agent: Holder = { username: "agent-reconcile", kind: "agent", sources: [TEAM] };

  it("names the one account, in the owner's words", () => {
    expect(noRoleWords([klee], { kind: "leave", groupHid: "G1" })).toBe(
      "klee will hold no role and be signed out.",
    );
  });

  it("names each member so left, and nobody who keeps a role", () => {
    expect(noRoleWords([klee, sroe, jdoe], { kind: "leave", groupHid: "G1" })).toBe(
      "klee and sroe will each hold no role and be signed out.",
    );
    expect(noRoleWords([klee, sroe, jdoe], { kind: "revoke", grantHid: "R2" })).toBe(
      "klee will hold no role and be signed out.",
    );
  });

  it("says of a service account and of an agent that their tokens are refused", () => {
    expect(noRoleWords([sync], { kind: "revoke", grantHid: "R2" })).toBe(
      "svc-sync will hold no role, and its tokens will be refused.",
    );
    expect(noRoleWords([klee, sync, agent], { kind: "leave", groupHid: "G1" })).toBe(
      "klee will hold no role and be signed out. svc-sync and agent-reconcile will each hold no role, and their tokens will be refused.",
    );
  });

  it("says nothing where everybody keeps a role", () => {
    expect(noRoleWords([jdoe, sroe], { kind: "revoke", grantHid: "R2" })).toBeNull();
    expect(noRoleWords([], { kind: "revoke", grantHid: "R2" })).toBeNull();
  });
});
