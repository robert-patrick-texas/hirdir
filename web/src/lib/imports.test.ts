import { describe, expect, it } from "vitest";
import {
  ENTITIES,
  entityLabel,
  fileIdentity,
  fileType,
  guessEntity,
  isEntity,
  modeLabel,
  previewQuery,
  readsFromSystem,
} from "./imports";

describe("entities", () => {
  it("are listed in the order they are loaded", () => {
    expect(ENTITIES.map((entity) => entity.value)).toEqual([
      // 0.9.18: the lists of countries and states, before the places whose addresses take them.
      "countries",
      "states",
      "tags",
      "vendors",
      "catalog_entries",
      // A place may name an operator, and an operator a contact: both come before the places.
      "contacts",
      // 0.8.0: a vendor names its account team and its support desk among the contacts.
      "vendor_contacts",
      "operators",
      "regions",
      "sites",
      "locations",
      "contact_assignments",
      "owners",
      "owner_members",
      "networks",
      // An item may name the purchase line it arrived on, and a contract its agreement.
      "external_systems",
      "agreements",
      "contracts",
      // The contacts of an agreement or a contract name the record and the contact.
      "contract_contacts",
      "purchase_requests",
      "purchase_lines",
      "items",
      "device_groups",
      "device_group_members",
      // After the members of groups: what a file of members shows as handed over is not
      // handed over a second time.
      "item_replacements",
      "addresses",
      "contract_coverage",
      "registrations",
      "capacity_lines",
      // 0.8.0: the circuits come last, their devices after the items and the groups.
      "circuit_groups",
      "circuits",
      "circuit_carriers",
      "circuit_costs",
      "circuit_contacts",
      "circuit_devices",
    ]);
  });

  it("know the seven kinds of record that came with circuits, and guess each from its file", () => {
    const labels: Record<string, [label: string, file: string]> = {
      vendor_contacts: ["Contacts of vendors", "vendor-contacts.csv"],
      circuit_groups: ["Circuit groups", "circuit-groups.csv"],
      circuits: ["Circuits", "circuits.json"],
      circuit_carriers: ["Carriers of circuits", "circuit-carriers.csv"],
      circuit_costs: ["Cost lines of circuits", "circuit-costs.csv"],
      circuit_contacts: ["Contacts of circuits", "circuit-contacts.json"],
      circuit_devices: ["Devices of circuits", "circuit-devices.csv"],
    };
    for (const [entity, [label, file]] of Object.entries(labels)) {
      expect(isEntity(entity), entity).toBe(true);
      expect(entityLabel(entity)).toBe(label);
      // Neither the vendors nor the contacts, nor the circuits, though the name holds them.
      expect(guessEntity(file), file).toBe(entity);
    }
  });

  it("know the nine kinds of record that came with contracts, purchases and capacity", () => {
    const labels: Record<string, string> = {
      external_systems: "External systems",
      agreements: "Support agreements",
      contracts: "Contracts",
      purchase_requests: "Purchase requests",
      purchase_lines: "Lines of purchase requests",
      item_replacements: "Replacements of items",
      contract_coverage: "Coverage of items under contracts",
      registrations: "Registrations with external systems",
      capacity_lines: "Capacity lines",
    };
    for (const [entity, label] of Object.entries(labels)) {
      expect(isEntity(entity), entity).toBe(true);
      expect(entityLabel(entity)).toBe(label);
    }
  });

  it("guesses each of the nine from the name of its example file, and none for another", () => {
    // A name that holds the name of another kind is still read as its own.
    expect(guessEntity("contracts.csv")).toBe("contracts");
    expect(guessEntity("contract-coverage.csv")).toBe("contract_coverage");
    expect(guessEntity("purchase-requests.json")).toBe("purchase_requests");
    expect(guessEntity("purchase-lines.csv")).toBe("purchase_lines");
    expect(guessEntity("item-replacements.csv")).toBe("item_replacements");
    expect(guessEntity("items.csv")).toBe("items");
    expect(guessEntity("external-systems.csv")).toBe("external_systems");
    expect(guessEntity("registrations.csv")).toBe("registrations");
    expect(guessEntity("capacity-lines.csv")).toBe("capacity_lines");
    expect(guessEntity("agreements.csv")).toBe("agreements");
  });

  it("know the contacts of agreements and contracts, and guess them from their file", () => {
    expect(isEntity("contract_contacts")).toBe(true);
    expect(entityLabel("contract_contacts")).toBe("Contacts of agreements and contracts");
    // Neither the contracts nor the contacts, though the name holds both words.
    expect(guessEntity("contract-contacts.csv")).toBe("contract_contacts");
    expect(guessEntity("contacts.csv")).toBe("contacts");
  });

  it("are known by name, and one this build does not know is shown as sent", () => {
    expect(isEntity("catalog_entries")).toBe(true);
    expect(isEntity("discoveries")).toBe(false);
    expect(entityLabel("catalog_entries")).toBe("Catalog entries");
    expect(entityLabel("discoveries")).toBe("discoveries");
    expect(isEntity("device_group_members")).toBe(true);
    expect(entityLabel("device_group_members")).toBe("Members of device groups");
    expect(entityLabel("addresses")).toBe("Addresses");
  });

  it("know the six kinds of record that came with places and people", () => {
    for (const entity of [
      "regions",
      "sites",
      "locations",
      "contacts",
      "contact_assignments",
      "owner_members",
    ]) {
      expect(isEntity(entity), entity).toBe(true);
    }
    expect(entityLabel("contact_assignments")).toBe("Contacts of places");
    expect(entityLabel("owner_members")).toBe("People of owners");
    expect(isEntity("operators")).toBe(true);
    expect(entityLabel("operators")).toBe("Operators");
  });
});

describe("modeLabel", () => {
  it("names the modes of a file and the one a bulk edit has", () => {
    expect(modeLabel("upsert")).toBe("Create and update");
    expect(modeLabel("create")).toBe("Create only");
    expect(modeLabel("update")).toBe("Update only");
  });
});

describe("fileType", () => {
  it("goes by the end of the name first", () => {
    expect(fileType({ name: "items.csv", type: "" })).toBe("text/csv");
    expect(fileType({ name: "ITEMS.CSV", type: "application/vnd.ms-excel" })).toBe("text/csv");
    expect(fileType({ name: "items.json", type: "text/plain" })).toBe("application/json");
  });

  it("goes by the browser's type when the name says nothing", () => {
    expect(fileType({ name: "export", type: "text/csv;charset=utf-8" })).toBe("text/csv");
    expect(fileType({ name: "export", type: "application/json" })).toBe("application/json");
  });

  it("knows no other format", () => {
    expect(fileType({ name: "items.xlsx", type: "application/vnd.ms-excel" })).toBeNull();
    expect(fileType({ name: "notes", type: "" })).toBeNull();
  });
});

describe("guessEntity", () => {
  it("reads the kind of record from a file's name", () => {
    expect(guessEntity("items.csv")).toBe("items");
    expect(guessEntity("catalog-entries.csv")).toBe("catalog_entries");
    expect(guessEntity("Catalog Entries (2).json")).toBe("catalog_entries");
    expect(guessEntity("hirdir-vendors-20261113T163125-0500.csv")).toBe("vendors");
    expect(guessEntity("networks.csv")).toBe("networks");
    expect(guessEntity("addresses.json")).toBe("addresses");
  });

  it("tells a file of groups from a file of their members", () => {
    expect(guessEntity("device_groups.csv")).toBe("device_groups");
    expect(guessEntity("device-group-members.csv")).toBe("device_group_members");
    expect(guessEntity("hirdir-device_group_members.json")).toBe("device_group_members");
  });

  it("tells places and people apart by the name of their file", () => {
    expect(guessEntity("regions.csv")).toBe("regions");
    expect(guessEntity("sites.csv")).toBe("sites");
    expect(guessEntity("locations.json")).toBe("locations");
    expect(guessEntity("contacts.csv")).toBe("contacts");
    expect(guessEntity("contact-assignments.csv")).toBe("contact_assignments");
    expect(guessEntity("owners.csv")).toBe("owners");
    expect(guessEntity("owner_members.csv")).toBe("owner_members");
    expect(guessEntity("operators.csv")).toBe("operators");
    // A file of items named after a site is a file of items.
    expect(guessEntity("items-site2.csv")).toBe("items");
  });

  it("knows the lists of countries and states by the names of their files (P-321)", () => {
    expect(guessEntity("countries.csv")).toBe("countries");
    expect(guessEntity("states.json")).toBe("states");
    expect(guessEntity("hirdir-states-20261122T101500-0500.csv")).toBe("states");
    expect(entityLabel("countries")).toBe("Countries");
    expect(entityLabel("states")).toBe("States");
    // A file of sites in a state is a file of sites.
    expect(guessEntity("sites-states-west.csv")).toBe("sites");
  });

  it("takes the kind that stands first in a name that holds more than one", () => {
    expect(guessEntity("contacts-operators-team.csv")).toBe("contacts");
    expect(guessEntity("items-operators-3fa9c1.csv")).toBe("items");
    expect(guessEntity("operators-items.csv")).toBe("operators");
    // Of two that start at the same place, the longer is meant.
    expect(guessEntity("device_group_members-of-device_groups.csv")).toBe("device_group_members");
  });

  it("guesses nothing from a name that says nothing", () => {
    expect(guessEntity("refresh-2030.csv")).toBe("");
  });

  it("passes over the name of the product at the start of an exported file's name", () => {
    const exported = "Sites-Tool-vendors-20261116T091500-0500.csv";
    // Without the product, its name is read as a kind of record like any other word.
    expect(guessEntity(exported)).toBe("sites");
    expect(guessEntity(exported, "Sites Tool")).toBe("vendors");
    expect(guessEntity("Sites-Tool-catalog_entries.json", "Sites Tool")).toBe("catalog_entries");
    // Saved twice by the browser, the name is the same at its start.
    expect(guessEntity("Sites-Tool-vendors-20261116T091500-0500 (1).csv", "Sites Tool")).toBe(
      "vendors",
    );
    expect(
      guessEntity("Ben-Ada-s-Net-2-items-20261116T091500-0500.csv", "Ben & Ada's: Net/2"),
    ).toBe("items");
    expect(
      guessEntity("Example-Inventory-owner_members-20261116T091500-0500.csv", "Example Inventory"),
    ).toBe("owner_members");
    // A name whose letters lost their accents in the file's name.
    expect(guessEntity("Reseau-Sites-contracts-20261116T091500-0500.csv", "Réseau Sites")).toBe(
      "contracts",
    );
  });

  it("still passes over hirdir, which named every export before, whatever the product", () => {
    expect(guessEntity("hirdir-vendors-20261113T163125-0500.csv", "Sites Tool")).toBe("vendors");
    expect(guessEntity("hirdir-sites-20261113T163125-0500.csv", "Sites Tool")).toBe("sites");
  });

  it("reads a file of the site's own naming as before", () => {
    expect(guessEntity("sites.csv", "Sites Tool")).toBe("sites");
    expect(guessEntity("Sites Tool.csv", "Sites Tool")).toBe("sites");
    // A product named after a kind of record: what follows its name is meant, where it
    // names one, and otherwise the name as a whole.
    expect(guessEntity("Items-owners-20261116T091500-0500.csv", "Items")).toBe("owners");
    expect(guessEntity("items-site2.csv", "Items")).toBe("items");
    expect(guessEntity("items.csv", "Items")).toBe("items");
  });
});

describe("previewQuery", () => {
  it("puts the entity, the mode and the name beside the file, and leaves a blank out", () => {
    expect(previewQuery("items", "create", "items.csv")).toEqual({
      entity: "items",
      mode: "create",
      file_name: "items.csv",
    });
    expect(previewQuery("", "", "refresh.json")).toEqual({ file_name: "refresh.json" });
    expect(previewQuery("tags", "", " ")).toEqual({ entity: "tags" });
  });

  it("puts the system a file of items was read from beside it, and complete only with it (P-248)", () => {
    const from = { system: "0193a1f4-0301", complete: true };
    expect(previewQuery("items", "", "vcenter.csv", from)).toEqual({
      entity: "items",
      file_name: "vcenter.csv",
      system: "0193a1f4-0301",
      complete: true,
    });
    expect(previewQuery("items", "", "vcenter.csv", { system: "", complete: true })).toEqual({
      entity: "items",
      file_name: "vcenter.csv",
    });
    // A file of other records is read from no system.
    expect(previewQuery("sites", "", "sites.csv", from)).toEqual({
      entity: "sites",
      file_name: "sites.csv",
    });
    expect(readsFromSystem("")).toBe(true);
    expect(readsFromSystem("vendors")).toBe(false);
  });

  it("keeps a name within what the server takes, and its ending with it", () => {
    const name = `${"a".repeat(300)}.csv`;
    const sent = previewQuery("items", "", name).file_name ?? "";
    expect(sent).toHaveLength(255);
    expect(sent.endsWith(".csv")).toBe(true);
  });
});

describe("fileIdentity", () => {
  it("is the same for the same file sent the same way, and no other", () => {
    const file = { name: "items.csv", size: 1200, lastModified: 1794000000000 };
    expect(fileIdentity(file, "items", "")).toBe(fileIdentity({ ...file }, "items", ""));
    expect(fileIdentity(file, "items", "create")).not.toBe(fileIdentity(file, "items", ""));
    expect(fileIdentity({ ...file, lastModified: 1794000000001 }, "items", "")).not.toBe(
      fileIdentity(file, "items", ""),
    );
    // 0.9.8: read from another system, or as everything it reports, it is another preview.
    const from = { system: "0193a1f4-0301", complete: false };
    expect(fileIdentity(file, "items", "", from)).not.toBe(fileIdentity(file, "items", ""));
    expect(fileIdentity(file, "items", "", { ...from, complete: true })).not.toBe(
      fileIdentity(file, "items", "", from),
    );
  });
});
