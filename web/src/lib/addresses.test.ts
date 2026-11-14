import { describe, expect, it } from "vitest";
import {
  type AddressRef,
  addressList,
  addressRoleLabel,
  addressText,
  familyLabel,
  holderKind,
  holderPath,
  managementText,
  mayBePrimary,
  networkLabels,
  networkText,
  newAddress,
  primaryAddress,
  primaryAddresses,
  primaryText,
  typedFamily,
} from "./addresses";

const ITEM = "0193a1f4-0000-7000-8000-000000000001";
const GROUP = "0193a1f4-0000-7000-8000-000000000002";
const RED = "0193a1f4-0000-7000-8000-00000000000a";

function ref(address: string, network: string | null, more: Partial<AddressRef> = {}): AddressRef {
  return {
    hid: `a-${address}`,
    address,
    network,
    network_hid: network ? RED : null,
    role: "management",
    is_primary: false,
    family: address.includes(":") ? 6 : 4,
    ...more,
  };
}

const ADDRESSES = [
  ref("192.0.2.10", "Red", { is_primary: true }),
  ref("192.0.2.11", "Red", { role: "secondary" }),
  ref("2001:db8::10", null, { role: "loopback" }),
  ref("198.51.100.7", "Black", { role: "virtual" }),
];

describe("addresses as words", () => {
  it("writes an address with the network it is under", () => {
    expect(addressText(ref("192.0.2.10", "Red"))).toBe("192.0.2.10 (Red)");
    expect(addressText(ref("2001:db8::10", null))).toBe("2001:db8::10");
  });

  it("lists every address of a record in the server's order", () => {
    expect(addressList(ADDRESSES)).toBe(
      "192.0.2.10 (Red), 192.0.2.11 (Red), 2001:db8::10, 198.51.100.7 (Black)",
    );
    expect(addressList([])).toBe("");
    expect(addressList(undefined)).toBe("");
  });

  it("finds the primary management address of each family, or none", () => {
    expect(primaryAddress(ADDRESSES, 4)?.address).toBe("192.0.2.10");
    expect(primaryAddress(ADDRESSES, 6)).toBeNull();
    expect(primaryAddress(ADDRESSES.slice(1), 4)).toBeNull();
    expect(primaryAddress(null, 4)).toBeNull();
    const both = [
      ref("2001:db8::10", null, { is_primary: true }),
      ref("192.0.2.11", "Red"),
      ref("192.0.2.10", "Red", { is_primary: true }),
    ];
    expect(primaryAddress(both, 6)?.address).toBe("2001:db8::10");
    expect(primaryAddress(both, 4)?.address).toBe("192.0.2.10");
    // IPv4 first, whatever order the record lists them in.
    expect(primaryAddresses(both).map((address) => address.address)).toEqual([
      "192.0.2.10",
      "2001:db8::10",
    ]);
    expect(managementText(both)).toBe("192.0.2.10, 2001:db8::10");
    expect(managementText(ADDRESSES)).toBe("192.0.2.10");
    expect(managementText([ref("2001:db8::10", null, { is_primary: true })])).toBe("2001:db8::10");
    expect(managementText(ADDRESSES.slice(1))).toBe("");
    expect(managementText(null)).toBe("");
    expect(primaryAddresses(undefined)).toEqual([]);
  });

  it("says which family an address is the primary of", () => {
    expect(familyLabel(4)).toBe("IPv4");
    expect(familyLabel(6)).toBe("IPv6");
    expect(primaryText(ref("192.0.2.10", null, { is_primary: true }))).toBe("Primary IPv4");
    expect(primaryText(ref("2001:db8::10", null, { is_primary: true }))).toBe("Primary IPv6");
    expect(primaryText(ref("192.0.2.11", null))).toBe("");
  });

  it("takes an address with a colon in it for IPv6 while it is typed", () => {
    expect(typedFamily("192.0.2.10")).toBe(4);
    expect(typedFamily("2001:DB8::1")).toBe(6);
    expect(typedFamily("")).toBe(4);
  });

  it("names each network once", () => {
    expect(networkLabels(ADDRESSES)).toEqual(["Red", "Black"]);
    expect(networkLabels([ref("203.0.113.5", null)])).toEqual([]);
  });

  it("says so when an address is under no network", () => {
    expect(networkText("Red")).toBe("Red");
    expect(networkText(null)).toBe("No network");
  });

  it("names a role, and shows one it does not know as sent", () => {
    expect(addressRoleLabel("management")).toBe("Management");
    expect(addressRoleLabel("anycast")).toBe("anycast");
  });

  it("lets only a management address be primary", () => {
    expect(mayBePrimary("management")).toBe(true);
    expect(mayBePrimary("loopback")).toBe(false);
  });
});

describe("the holders of an address", () => {
  it("links an item and a group to their own pages", () => {
    expect(holderPath({ item_hid: ITEM, group_hid: null })).toBe(`/items/${ITEM}`);
    expect(holderPath({ item_hid: null, group_hid: GROUP })).toBe(`/groups/${GROUP}`);
    expect(holderPath({ item_hid: null, group_hid: null })).toBeNull();
  });

  it("says which of the two a holder is", () => {
    expect(holderKind({ item_hid: ITEM, group_hid: null })).toBe("Item");
    expect(holderKind({ item_hid: null, group_hid: GROUP })).toBe("Group");
  });
});

describe("newAddress", () => {
  it("sends the address as typed, for the item or the group it is given", () => {
    expect(
      newAddress(
        { item_hid: ITEM },
        { address: " 192.0.2.10 ", network_hid: RED, role: "management", is_primary: true },
      ),
    ).toEqual({
      item_hid: ITEM,
      address: "192.0.2.10",
      network_hid: RED,
      role: "management",
      is_primary: true,
    });
    expect(
      newAddress(
        { group_hid: GROUP },
        { address: "2001:DB8::1", network_hid: "", role: "loopback", is_primary: false },
      ),
    ).toEqual({ group_hid: GROUP, address: "2001:DB8::1", role: "loopback" });
  });

  it("does not mark as primary an address that is not a management address", () => {
    const body = newAddress(
      { item_hid: ITEM },
      { address: "198.51.100.7", network_hid: "", role: "virtual", is_primary: true },
    );
    expect(body).toEqual({ item_hid: ITEM, address: "198.51.100.7", role: "virtual" });
  });

  it("takes a role it does not know as the default one", () => {
    const body = newAddress(
      { item_hid: ITEM },
      { address: "203.0.113.9", network_hid: "", role: "", is_primary: false },
    );
    expect(body.role).toBe("management");
  });
});
