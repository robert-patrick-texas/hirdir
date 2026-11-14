import { describe, expect, it } from "vitest";
import {
  EXTERNAL_GROUP,
  externalNote,
  mayRemove,
  memberRoleLabel,
  membersInOrder,
  type OwnerMember,
  ownerOption,
  ownerOptions,
} from "./owners";

const ENGINEERING = "0193a1f4-0000-7000-8000-0000000000b1";
const FACILITIES = "0193a1f4-0000-7000-8000-0000000000b2";
const RETIRED = "0193a1f4-0000-7000-8000-0000000000b3";

const OWNERS = [
  { hid: ENGINEERING, label: "Network Engineering", is_external: false },
  { hid: FACILITIES, label: "Campus Facilities", is_external: true },
];

function member(
  hid: string,
  name: string,
  role: OwnerMember["role"],
  priority: number,
): OwnerMember {
  return {
    hid,
    owner_hid: FACILITIES,
    contact_hid: `k-${hid}`,
    contact: {
      hid: `k-${hid}`,
      name,
      organization: null,
      email: null,
      phone: null,
      record_status: "active",
    },
    role,
    priority,
    row_version: 1,
    created_at: "2026-01-31T19:05:09Z",
    updated_at: "2026-01-31T19:05:09Z",
  };
}

describe("owners in a form", () => {
  const reason = "Runs the building systems";

  it("offers each by its label, those outside the team under a heading of their own", () => {
    const options = ownerOptions(OWNERS);
    expect(options.map((option) => [option.value, option.label, option.group])).toEqual([
      [ENGINEERING, "Network Engineering", undefined],
      [FACILITIES, "Campus Facilities", EXTERNAL_GROUP],
    ]);
    // An owner of the team has nothing more to say of itself.
    expect(options[0]).toEqual({ value: ENGINEERING, label: "Network Engineering" });
  });

  it("says of an owner outside the team, once it is chosen, that it is one, and its reason", () => {
    const option = ownerOption({
      hid: FACILITIES,
      label: "Campus Facilities",
      is_external: true,
      exception_reason: reason,
    });
    expect(option.note).toBe(externalNote(reason));
    expect(option.note).toContain("marked as an exception");
    expect(option.note).toContain("Its reason: Runs the building systems.");
    expect(option.note).toContain("changed on the owner's page");
  });

  it("says so also where the reason is not known, and ends a reason with one full stop", () => {
    expect(externalNote(null)).not.toContain("Its reason");
    expect(externalNote("  ")).not.toContain("Its reason");
    expect(externalNote("In the plant room.")).toContain("Its reason: In the plant room. The");
  });

  it("offers an owner as another record names it, also one the list no longer brings", () => {
    // The owner an item has is offered as the item names it, with the reason the item shows.
    const retired = ownerOption({
      hid: RETIRED,
      label: "Old Facilities",
      is_external: true,
      exception_reason: reason,
    });
    expect(retired).toEqual({
      value: RETIRED,
      label: "Old Facilities",
      group: EXTERNAL_GROUP,
      note: externalNote(reason),
    });
    expect(
      ownerOption({ hid: ENGINEERING, label: "Network Engineering", is_external: false }),
    ).toEqual({ value: ENGINEERING, label: "Network Engineering" });
  });
});

describe("the people of an owner", () => {
  const dana = member("m-1", "Dana Whitfield", "alternate", 2);
  const priya = member("m-2", "Priya Raman", "primary", 3);
  const lee = member("m-3", "Lee Okafor", "alternate", 1);

  it("lists the primary first, then the alternates by priority", () => {
    expect(membersInOrder([dana, priya, lee]).map((one) => one.contact.name)).toEqual([
      "Priya Raman",
      "Lee Okafor",
      "Dana Whitfield",
    ]);
  });

  it("does not offer to remove the primary while others remain", () => {
    expect(mayRemove(priya, [dana, priya, lee])).toBe(false);
    expect(mayRemove(dana, [dana, priya, lee])).toBe(true);
    expect(mayRemove(priya, [priya])).toBe(true);
  });

  it("names the two roles", () => {
    expect(memberRoleLabel("primary")).toBe("Primary");
    expect(memberRoleLabel("alternate")).toBe("Alternate");
    expect(memberRoleLabel("deputy")).toBe("deputy");
  });
});
