import { describe, expect, it } from "vitest";
import { actorLabel, actorWords, deletedRecords, isDeleted } from "./audit";

const GROUP = "01a1f0e8-0000-7000-8000-000000000001";
const ITEM = "01a1f0e8-0000-7000-8000-000000000002";

describe("the records the audit trail on show says were deleted", () => {
  const events = [
    { action: "delete", record_type: "device_group", record_hid: GROUP },
    { action: "update", record_type: "device_group", record_hid: GROUP },
    { action: "create", record_type: "device_group", record_hid: GROUP },
    { action: "create", record_type: "item", record_hid: ITEM },
    { action: "sign_in", record_type: "user", record_hid: null },
  ];
  const gone = deletedRecords(events);

  it("are those of an event of the action delete, and every event of them", () => {
    for (const event of events.slice(0, 3)) expect(isDeleted(gone, event)).toBe(true);
  });

  it("are not a record that no event held deletes, nor an event that names none", () => {
    for (const event of events.slice(3)) expect(isDeleted(gone, event)).toBe(false);
  });

  it("are told apart by their kind as well as their HID", () => {
    expect(isDeleted(gone, { action: "create", record_type: "item", record_hid: GROUP })).toBe(
      false,
    );
  });
});

describe("who acted, as the Audit page offers them (P-296)", () => {
  it("still offers a retired account, marked", () => {
    expect(actorLabel({ username: "klee", record_status: "retired" })).toBe("klee (retired)");
    expect(actorLabel({ username: "klee", record_status: "active" })).toBe("klee");
    expect(actorLabel({ username: "sokafor" })).toBe("sokafor");
  });

  it("marks an agent with the person answerable for it (P-316)", () => {
    const sam = { username: "sam" };
    expect(actorLabel({ username: "agent-reconcile", kind: "agent", answerable: sam })).toBe(
      "agent-reconcile (agent, for sam)",
    );
    expect(
      actorLabel({
        username: "agent-reconcile",
        kind: "agent",
        answerable: sam,
        record_status: "retired",
      }),
    ).toBe("agent-reconcile (agent, for sam, retired)");
    expect(actorLabel({ username: "svc-sync", kind: "service", answerable: null })).toBe(
      "svc-sync",
    );
  });
});

describe("who made a change, as a history writes it (P-316)", () => {
  const event = { actor_hid: "U1", actor_name: "agent-reconcile", for_hid: "U2" };
  it("writes an agent's change with the person it was for", () => {
    expect(actorWords({ ...event, actor_kind: "agent", for_name: "sam" })).toBe(
      "agent-reconcile for sam",
    );
  });

  it("writes anybody else's by the username alone, and the system's as nobody", () => {
    expect(actorWords({ ...event, actor_name: "klee", actor_kind: "person", for_name: null })).toBe(
      "klee",
    );
    // An agent's event of before 0.9.17 has no person: the username alone.
    expect(actorWords({ ...event, actor_kind: "agent", for_name: null })).toBe("agent-reconcile");
    expect(actorWords({ actor_hid: null, actor_name: null, actor_kind: null })).toBeNull();
  });
});
