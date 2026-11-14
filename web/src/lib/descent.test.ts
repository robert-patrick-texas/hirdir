import { describe, expect, it } from "vitest";
import {
  aboveGroup,
  aboveItem,
  descentHint,
  inheritedHint,
  isFromAbove,
  knownAbove,
  locationHint,
  membersWithOwn,
  membersWithOwnPath,
  membersWithOwnText,
  ownerSource,
  type PlaceInForce,
  placeSource,
} from "./descent";

const ROOM_HID = "0193a1f4-6c2e-7b41-9d0a-5e3f8c1a7b22";
const ITEM = "0193a1f4-0000-7000-8000-000000000001";
const GROUP = "0193a1f4-0000-7000-8000-000000000002";
const ROOM = "Americas > Central > Site-2 > Building 1 > Room 102";

const own: PlaceInForce = {
  value: ROOM_HID,
  label: ROOM,
  site: "Site-2",
  site_hid: ROOM_HID,
  region: "Central",
  region_hid: ROOM_HID,
  source: "own",
  source_hid: ITEM,
  source_label: null,
};
const fromItem: PlaceInForce = {
  ...own,
  source: "parent_item",
  source_hid: ITEM,
  source_label: "site2-sw-access-01",
};
const fromGroup: PlaceInForce = {
  ...own,
  source: "device_group",
  source_hid: GROUP,
  source_label: "Stack 4",
};
const nowhere: PlaceInForce = {
  value: null,
  label: null,
  site: null,
  site_hid: null,
  region: null,
  region_hid: null,
  source: "none",
  source_hid: null,
  source_label: null,
};

describe("a location from above", () => {
  it("is one that came from the item or the group above, and not the record's own or none", () => {
    expect(isFromAbove(own)).toBe(false);
    expect(isFromAbove(fromItem)).toBe(true);
    expect(isFromAbove(fromGroup)).toBe(true);
    expect(isFromAbove(nowhere)).toBe(false);
    expect(isFromAbove(null)).toBe(false);
    expect(isFromAbove(undefined)).toBe(false);
  });

  it("names the record it came from, with the way to it", () => {
    expect(placeSource(fromItem)).toEqual({
      text: "the item site2-sw-access-01",
      path: `/items/${ITEM}`,
    });
    expect(placeSource(fromGroup)).toEqual({ text: "the group Stack 4", path: `/groups/${GROUP}` });
    expect(placeSource(own)).toBeNull();
    expect(placeSource(nowhere)).toBeNull();
  });
});

describe("the hint of a location in force", () => {
  it("says the whole path of a location the record has itself", () => {
    expect(locationHint(own)).toBe(ROOM);
  });

  it("says which item or group it came from when it is inherited", () => {
    expect(locationHint(fromItem)).toBe(`${ROOM} · Inherited from the item site2-sw-access-01`);
    expect(locationHint(fromGroup)).toBe(`${ROOM} · Inherited from the group Stack 4`);
  });

  it("says that it is inherited even when the server sent no name with it", () => {
    expect(locationHint({ ...fromGroup, source_label: null })).toBe(
      `${ROOM} · Inherited from the group`,
    );
    expect(locationHint({ ...fromGroup, source_hid: null, source_label: null })).toBe(
      `${ROOM} · Inherited`,
    );
  });

  it("says nothing of a record that is nowhere", () => {
    expect(locationHint(nowhere)).toBe("");
    expect(locationHint(null)).toBe("");
  });
});

describe("what stands above a record", () => {
  it("is the item a minor item is in, or a group of a member, or nothing", () => {
    expect(aboveItem({ parent_item_hid: ITEM, groups: [] })).toBe("the item it is in");
    expect(aboveItem({ parent_item_hid: ITEM, groups: [{}] })).toBe("the item it is in");
    expect(aboveItem({ parent_item_hid: null, groups: [{}] })).toBe("its group");
    expect(aboveItem({ parent_item_hid: null, groups: [] })).toBe("");
  });

  it("is the group a group is nested in", () => {
    expect(aboveGroup({ parent_group_hid: GROUP })).toBe("the group it is in");
    expect(aboveGroup({ parent_group_hid: null })).toBe("");
  });
});

describe("what a form says beneath a location that may come from above", () => {
  it("says that an own value is an override, and how to have the one from above again", () => {
    expect(descentHint("location", "item", ROOM_HID, own, "its group")).toBe(
      "Set here, as the item's own: an override. Clear it and save, and the item is where its group is again.",
    );
    expect(descentHint("planned", "group", ROOM_HID, own, "the group it is in")).toBe(
      "Set here, as the group's own: an override. Clear it and save, and the group has the plan of the group it is in again.",
    );
  });

  it("says that there is none where the record has none and nothing above has one", () => {
    expect(descentHint("location", "item", null, nowhere, "the item it is in")).toBe(
      "None of its own, and none from the item it is in.",
    );
    expect(descentHint("planned", "item", "", nowhere, "its group")).toBe(
      "None of its own, and none from its group.",
    );
  });

  it("adds nothing where the form shows the value from above, above the field", () => {
    expect(descentHint("location", "item", null, fromGroup, "its group")).toBe("");
  });

  it("says nothing for a record with nothing above it", () => {
    expect(descentHint("location", "item", ROOM_HID, own, "")).toBe("");
    expect(descentHint("location", "item", null, nowhere, "")).toBe("");
  });
});

describe("the members of a group that have a place of their own", () => {
  it("are found by the group and by the field of their own that is not empty", () => {
    expect(membersWithOwn(GROUP, "location")).toBe(
      `group.hid:eq:${GROUP} location_hid:empty:false`,
    );
    expect(membersWithOwn(GROUP, "planned")).toBe(
      `group.hid:eq:${GROUP} planned_location_hid:empty:false`,
    );
    expect(membersWithOwnPath(GROUP, "location")).toBe(
      `/items?filter=${encodeURIComponent(`group.hid:eq:${GROUP} location_hid:empty:false`)}&minor=1`,
    );
  });

  it("are counted in words, the number being what is linked", () => {
    expect(membersWithOwnText(0, "location")).toEqual({
      linked: "",
      after: "none of its members has a location of its own",
    });
    expect(membersWithOwnText(0, "planned")).toEqual({
      linked: "",
      after: "none of its members has a plan of its own",
    });
    expect(membersWithOwnText(1, "location")).toEqual({
      linked: "1 of its members",
      after: "has a location of its own, as an override",
    });
    expect(membersWithOwnText(3, "planned")).toEqual({
      linked: "3 of its members",
      after: "have a plan of their own, as an override",
    });
  });
});

describe("an owner from above", () => {
  const OWNER = "0193a1f4-0000-7000-8000-0000000000a1";
  const mine = { value: OWNER, label: "Network Engineering", source: "own", source_hid: ITEM };
  const fromParent = { ...mine, source: "parent_item", source_hid: ITEM };
  const fromStack = { ...mine, source: "device_group", source_hid: GROUP };
  const none = { value: null, label: null, source: "none", source_hid: null };
  const known = [
    { hid: ITEM, name: "site2-sw-access-01" },
    { hid: GROUP, name: "Stack 4" },
  ];

  it("is named from what the page knows of the record: the server sends no name with it", () => {
    expect(ownerSource(fromParent, known)).toEqual({
      text: "the item site2-sw-access-01",
      path: `/items/${ITEM}`,
    });
    expect(ownerSource(fromStack, known)).toEqual({
      text: "the group Stack 4",
      path: `/groups/${GROUP}`,
    });
  });

  it("is linked by its HID all the same when the page does not know the record", () => {
    expect(ownerSource(fromStack, [])).toEqual({
      text: "the group it is in",
      path: `/groups/${GROUP}`,
    });
    expect(ownerSource(fromParent, [])).toEqual({
      text: "the item it is in",
      path: `/items/${ITEM}`,
    });
  });

  it("has no source for an owner of the record's own, and for none", () => {
    expect(ownerSource(mine, known)).toBeNull();
    expect(ownerSource(none, known)).toBeNull();
    expect(ownerSource(null, known)).toBeNull();
  });

  it("is said in the hint of a cell with the record it came from", () => {
    expect(inheritedHint(ownerSource(fromStack, known))).toBe("Inherited from the group Stack 4");
    expect(inheritedHint(ownerSource(mine, known))).toBe("");
  });

  it("knows the records above an item by the names the item has for them", () => {
    expect(
      knownAbove({
        parent: { hid: ITEM, name: "site2-sw-access-01" },
        groups: [{ group_hid: GROUP, name: "Stack 4" }],
      }),
    ).toEqual(known);
    expect(knownAbove({ parent: null, groups: [] })).toEqual([]);
  });

  it("says in a form how to have the owner from above again, by choosing the blank", () => {
    expect(descentHint("owner", "item", OWNER, mine, "its group")).toBe(
      "Set here, as the item's own: an override. Choose the blank and save, and the item has the owner of its group again.",
    );
    expect(descentHint("owner", "group", null, none, "the group it is in")).toBe(
      "None of its own, and none from the group it is in.",
    );
    expect(descentHint("owner", "item", null, fromStack, "its group")).toBe("");
    expect(descentHint("owner", "item", OWNER, mine, "")).toBe("");
  });
});
