import { describe, expect, it } from "vitest";
import {
  agentsOfGroupLead,
  bringBackRoleHint,
  cappedWords,
  type Holder,
  kindName,
  kindWord,
  leavesNoRole,
  leftWithNone,
  noRoleWords,
  remaining,
  rolesFor,
  type Source,
  sourceWords,
  tokenRefused,
  tokenWaits,
} from "./accounts";

const TEAM_GROUP = { hid: "G1", name: "Network team" };
const OWN: Source = { hid: "R1", role: "viewer", group: null };
const TEAM: Source = { hid: "R2", role: "inventory", group: TEAM_GROUP };
const TEAM_TOO: Source = { hid: "R3", role: "viewer", group: TEAM_GROUP };
const DESK: Source = { hid: "R4", role: "viewer", group: { hid: "G2", name: "Help desk" } };

describe("the kind of an account (P-316)", () => {
  it("is written in a word on the list, and named on the page", () => {
    expect(["person", "service", "agent"].map(kindWord)).toEqual(["Person", "Service", "Agent"]);
    expect(["person", "service", "agent"].map(kindName)).toEqual([
      "Person",
      "Service account",
      "Agent",
    ]);
  });

  it("offers an agent every role but Admin", () => {
    expect(rolesFor("agent")).toEqual(["viewer", "inventory"]);
    expect(rolesFor("person")).toEqual(["viewer", "inventory", "admin"]);
    expect(rolesFor("service")).toEqual(["viewer", "inventory", "admin"]);
  });
});

describe("a token made for an account that holds no role (P-314)", () => {
  const sam = { hid: "U9", username: "sam", name: "Sam Roe", record_status: "active" as const };
  const base = {
    username: "agent-reconcile",
    kind: "agent" as const,
    role: "inventory",
    role_in_force: "inventory",
    role_capped_by: null,
    answerable: sam,
  };

  it("says it is refused until the account holds one, and how one is given", () => {
    expect(tokenWaits("svc-sync")).toBe(
      "svc-sync holds no role, so this token is refused until it holds one: grant it a role under Roles, or put it in a group that grants one. The token works from then on.",
    );
    expect(
      tokenRefused({
        ...base,
        kind: "service",
        username: "svc-sync",
        role: null,
        answerable: null,
      }),
    ).toBe(tokenWaits("svc-sync"));
    expect(tokenRefused({ ...base, role: null, role_in_force: null })).toBe(
      tokenWaits("agent-reconcile"),
    );
  });

  it("says of an agent's that it is refused while its person cannot answer for it", () => {
    expect(tokenRefused({ ...base, role_in_force: null, role_capped_by: "person_disabled" })).toBe(
      "This token is refused while sam is disabled: agent-reconcile answers for nothing more than its person does. It works once sam can answer for it.",
    );
    // Held lower, it works.
    expect(
      tokenRefused({ ...base, role_in_force: "viewer", role_capped_by: "person_role" }),
    ).toBeNull();
    expect(tokenRefused(base)).toBeNull();
  });
});

describe("the role an agent is held to (P-316)", () => {
  const sam = { hid: "U9", username: "sam", name: "Sam Roe", record_status: "active" as const };
  const agent = {
    username: "agent-reconcile",
    kind: "agent" as const,
    role: "inventory",
    role_in_force: "viewer",
    role_capped_by: "person_role" as const,
    answerable: sam,
  };

  it("says why it is held lower than it holds", () => {
    expect(cappedWords(agent)).toBe("held to View-only by sam's role");
    expect(cappedWords({ ...agent, role_in_force: null, role_capped_by: "person_no_role" })).toBe(
      "its tokens are refused while sam holds no role",
    );
    expect(cappedWords({ ...agent, role_in_force: null, role_capped_by: "person_retired" })).toBe(
      "its tokens are refused while sam is retired",
    );
  });

  it("says that an agent that holds Admin all the same is held lower, being never Admin", () => {
    expect(
      cappedWords({
        ...agent,
        role: "admin",
        role_in_force: "inventory",
        role_capped_by: "never_admin",
      }),
    ).toBe("held to Inventory: an agent is never Admin");
  });

  it("says nothing where nothing holds it lower, nor of a person", () => {
    expect(cappedWords({ ...agent, role_in_force: "inventory", role_capped_by: null })).toBeNull();
    expect(cappedWords({ ...agent, kind: "person", role_capped_by: null })).toBeNull();
  });
});

describe("what Bring back says under Role, for each kind (review 7)", () => {
  it("says of an agent what an agent may come back with", () => {
    expect(bringBackRoleHint("person")).toBe(
      "An account with no role cannot sign in: choose the one it is to hold.",
    );
    expect(bringBackRoleHint("service")).toBe(
      "A service account may come back with none; its tokens are refused until it has one.",
    );
    expect(bringBackRoleHint("agent")).toBe(
      "An agent may come back with none; its tokens are refused until it has one. It is never Admin, and holds no more than the role of its person.",
    );
  });
});

describe("the agents a refusal of Admin to a group names (review 4)", () => {
  it("are said as the group's", () => {
    expect(agentsOfGroupLead(1)).toBe("The agent in the group:");
    expect(agentsOfGroupLead(2)).toBe("The 2 agents in the group:");
  });
});

describe("where a role comes from (P-307)", () => {
  it("is of its own, or through a group, named", () => {
    expect(sourceWords(OWN)).toBe("of its own");
    expect(sourceWords(TEAM)).toBe("through Network team");
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
  const klee: Holder = { username: "klee", kind: "person", grants: [TEAM] };
  const sroe: Holder = { username: "sroe", kind: "person", grants: [TEAM, TEAM_TOO] };
  const rex: Holder = { username: "rex", kind: "person", grants: [OWN, TEAM] };
  const sync: Holder = { username: "svc-sync", kind: "service", grants: [TEAM] };
  const agent: Holder = { username: "agent-reconcile", kind: "agent", grants: [TEAM] };

  it("names the one account, in the owner's words", () => {
    expect(noRoleWords([klee], { kind: "leave", groupHid: "G1" })).toBe(
      "klee will hold no role and be signed out.",
    );
  });

  it("names the agents of a person so left, whose tokens are refused with them (P-316)", () => {
    const active = { hid: "A1", name: "agent-reconcile", record_status: "active" as const };
    const withAgents: Holder = {
      ...sroe,
      agents: [
        { ...active, username: "agent-reconcile" },
        { ...active, hid: "A2", username: "agent-sync" },
        { ...active, hid: "A3", username: "agent-old", record_status: "retired" },
      ],
    };
    expect(noRoleWords([withAgents], { kind: "leave", groupHid: "G1" })).toBe(
      "sroe will hold no role and be signed out, and the tokens of agent-reconcile and agent-sync will be refused.",
    );
    // Of two people, each agent once, an agent left with no role itself among them.
    const kleeToo: Holder = { ...klee, agents: [{ ...active, hid: "A4", username: "agent-tidy" }] };
    const reconcile: Holder = { ...agent, grants: [TEAM] };
    expect(noRoleWords([withAgents, kleeToo, reconcile], { kind: "leave", groupHid: "G1" })).toBe(
      "sroe and klee will each hold no role and be signed out, and the tokens of agent-reconcile, agent-sync and agent-tidy will be refused.",
    );
    // A person who keeps a role says nothing of their agents.
    expect(
      noRoleWords([{ ...rex, agents: [{ ...active, username: "agent-x" }] }], {
        kind: "leave",
        groupHid: "G1",
      }),
    ).toBeNull();
  });

  it("names each member so left, and nobody who keeps a role", () => {
    expect(leftWithNone([klee, sroe, rex], { kind: "leave", groupHid: "G1" })).toEqual([
      klee,
      sroe,
    ]);
    expect(noRoleWords([klee, sroe, rex], { kind: "leave", groupHid: "G1" })).toBe(
      "klee and sroe will each hold no role and be signed out.",
    );
    expect(noRoleWords([klee, sroe, rex], { kind: "revoke", grantHid: "R2" })).toBe(
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
    expect(noRoleWords([rex, sroe], { kind: "revoke", grantHid: "R2" })).toBeNull();
    expect(noRoleWords([], { kind: "revoke", grantHid: "R2" })).toBeNull();
  });
});
