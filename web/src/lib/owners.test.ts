import { describe, expect, it } from "vitest";
import {
  EXTERNAL_GROUP,
  externalOwners,
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
  it("offers each by its label, those outside the team under a heading of their own", () => {
    expect(ownerOptions(OWNERS)).toEqual([
      { value: ENGINEERING, label: "Network Engineering" },
      { value: FACILITIES, label: "Campus Facilities", group: EXTERNAL_GROUP },
    ]);
  });

  it("knows which of them are outside the team", () => {
    const outside = externalOwners(ownerOptions(OWNERS));
    expect(outside.has(FACILITIES)).toBe(true);
    expect(outside.has(ENGINEERING)).toBe(false);
    expect(outside.has("")).toBe(false);
  });

  it("offers an owner as another record names it, which says whether it is outside", () => {
    // The owner an item has is offered also when the list no longer brings it, as a
    // retired one: the item names it with `is_external`.
    const retired = ownerOption({ hid: RETIRED, label: "Old Facilities", is_external: true });
    expect(retired).toEqual({ value: RETIRED, label: "Old Facilities", group: EXTERNAL_GROUP });
    const outside = externalOwners([...ownerOptions(OWNERS), retired]);
    expect([...outside].sort()).toEqual([FACILITIES, RETIRED]);
    expect(
      ownerOption({ hid: ENGINEERING, label: "Network Engineering", is_external: false }),
    ).toEqual({ value: ENGINEERING, label: "Network Engineering" });
    expect(externalOwners(undefined).size).toBe(0);
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
