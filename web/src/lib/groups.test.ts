import { describe, expect, it } from "vitest";
import {
  buildMembers,
  defaultRole,
  groupTypeLabel,
  isGroupType,
  membershipText,
  nextPosition,
  ownerDisputed,
  type PendingMember,
  roleLabel,
  roleOptions,
  rolesOf,
  stackProblem,
} from "./groups";

const ONE = "0193a1f4-0000-7000-8000-000000000001";
const TWO = "0193a1f4-0000-7000-8000-000000000002";

function pending(item_hid: string, role: string, position = ""): PendingMember {
  return { item_hid, name: `site2-sw-${item_hid.slice(-1)}`, role, position };
}

describe("types and roles", () => {
  it("names the four types, and shows one it does not know as sent", () => {
    expect(groupTypeLabel("controller_domain")).toBe("Controller domain");
    expect(groupTypeLabel("fabric")).toBe("fabric");
    expect(isGroupType("stack")).toBe(true);
    expect(isGroupType("fabric")).toBe(false);
  });

  it("offers each type its own roles, the usual one first", () => {
    expect([...rolesOf("stack")]).toEqual(["member", "master"]);
    expect([...rolesOf("cluster")]).toEqual(["member", "active", "standby"]);
    expect([...rolesOf("controller_domain")]).toEqual(["endpoint", "controller"]);
    expect([...rolesOf("custom")]).toEqual(["member"]);
    expect(defaultRole("controller_domain")).toBe("endpoint");
    expect(defaultRole("stack")).toBe("member");
    expect(roleOptions("stack")).toEqual([
      { value: "member", label: "Member" },
      { value: "master", label: "Master" },
    ]);
  });

  it("writes a role and a membership for people", () => {
    expect(roleLabel("standby")).toBe("Standby");
    expect(roleLabel("witness")).toBe("witness");
    expect(membershipText({ role: "master", position: 1 })).toBe("Master, position 1");
    expect(membershipText({ role: "endpoint", position: null })).toBe("Endpoint");
    expect(membershipText({ role: "member", position: 0 })).toBe("Member, position 0");
  });
});

describe("ownerDisputed", () => {
  it("is true only when a member has another owner in force", () => {
    expect(ownerDisputed({ members_disagree: ["owner_hid"] })).toBe(true);
    expect(ownerDisputed({ members_disagree: [] })).toBe(false);
    expect(ownerDisputed({ members_disagree: ["location_hid"] })).toBe(false);
  });
});

describe("nextPosition", () => {
  it("is one past the highest, and 1 for a group with none", () => {
    expect(nextPosition([1, 2, 3])).toBe(4);
    expect(nextPosition([4, null, 2])).toBe(5);
    expect(nextPosition([])).toBe(1);
    expect(nextPosition([null, undefined])).toBe(1);
  });
});

describe("buildMembers", () => {
  it("sends every item chosen, with its role and its position, in one list", () => {
    const built = buildMembers("stack", [pending(ONE, "master", "1"), pending(TWO, "member", "2")]);
    expect(built.errors).toEqual({});
    expect(built.members).toEqual([
      { item_hid: ONE, role: "master", position: 1 },
      { item_hid: TWO, role: "member", position: 2 },
    ]);
  });

  it("leaves a blank position out, and names the day when one was given", () => {
    const built = buildMembers("controller_domain", [pending(ONE, "endpoint")], "2026-11-02");
    expect(built.members).toEqual([{ item_hid: ONE, role: "endpoint", joined_on: "2026-11-02" }]);
  });

  it("refuses a position that is no whole number, by the item it was typed for", () => {
    const built = buildMembers("stack", [
      pending(ONE, "master", "1"),
      pending(TWO, "member", "two"),
    ]);
    expect(built.members).toEqual([{ item_hid: ONE, role: "master", position: 1 }]);
    expect(built.errors).toEqual({ [TWO]: "A whole number from 0 to 10000, or blank." });
    expect(buildMembers("stack", [pending(ONE, "member", "10001")]).errors[ONE]).toBeDefined();
    expect(buildMembers("stack", [pending(ONE, "member", "-1")]).errors[ONE]).toBeDefined();
  });

  it("refuses a role the type of group does not have", () => {
    const built = buildMembers("cluster", [pending(ONE, "master")]);
    expect(built.members).toEqual([]);
    expect(built.errors).toEqual({ [ONE]: "One of Member, Active, Standby." });
  });
});

describe("stackProblem", () => {
  it("has nothing to say of another type of group, nor of a stack with no member", () => {
    expect(stackProblem("cluster", "active", ["member"])).toBe("");
    expect(stackProblem("stack", "active", [])).toBe("");
  });

  it("lets an active stack stand with one master, alone or with members", () => {
    expect(stackProblem("stack", "active", ["master"])).toBe("");
    expect(stackProblem("stack", "active", ["master", "member"])).toBe("");
    expect(stackProblem("stack", "active", ["member", "member", "master", "member"])).toBe("");
  });

  it("says what an active stack lacks", () => {
    expect(stackProblem("stack", "active", ["member"])).toMatch(/exactly one master/);
    expect(stackProblem("stack", "active", ["member", "member"])).toMatch(/exactly one master/);
  });

  it("lets a draft be built up, and never with two masters", () => {
    expect(stackProblem("stack", "draft", ["member"])).toBe("");
    expect(stackProblem("stack", "draft", ["master", "master"])).toMatch(/would have more/);
    expect(stackProblem("stack", "active", ["master", "master", "member"])).toMatch(
      /would have more/,
    );
  });
});
