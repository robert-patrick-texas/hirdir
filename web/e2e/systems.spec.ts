// The browser scenario of external systems in release 0.6.0:
//
//   S33  A stack is registered with a monitoring system and with an SDN controller:
//        both registrations are on the stack, and not on its members, each of which
//        says what its stack is registered with.
//
// On the way: a registration that ends is given the status Removed and stays on record,
// and registered again it is the same registration; one that was a mistake is removed
// outright; a system lists what is registered with it, and the grids of groups and of
// items find a record by a system, a member by a system that knows its stack.
//
// It keeps to the rules of support.ts: an account and names of its own, systems of its
// own, and every grid filtered down to this file's records before anything is counted.

import { expect, type Locator, type Page } from "@playwright/test";
import { importFile, main, openGroup, openItem, region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const random = mark("x").slice(2);
const suffix = mark("systems", random);
const upper = random.toUpperCase();

const vendor = `Example Networks ${suffix}`;
const pid = `EN-9300-48P-${suffix}`;
const stack = `site9-stack-${suffix}`;
const members = [1, 2].map((place) => `site9-stk-${suffix}-0${place}`) as [string, string];
const monitoring = `NetWatch ${suffix}`;
const controller = `Fabric Controller ${suffix}`;

/** The row of one system in the table of what a record is registered with. */
function registration(page: Page, system: string): Locator {
  return page.getByTestId("registrations").locator(`tr[data-system="${system}"]`);
}

async function newSystem(page: Page, name: string, kind: string) {
  await page.goto("./systems");
  await expect(page.getByRole("heading", { level: 1, name: "External systems" })).toBeVisible();
  await page.getByRole("button", { name: "New system" }).click();
  const form = region(page, "New external system");
  await form.getByLabel("Name (required)").fill(name);
  await form.getByLabel("Kind").selectOption({ label: kind });
  await form.getByRole("button", { name: "Create system" }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  await expect(page.getByTestId("system-registrations")).toContainText("0 records");
}

async function register(page: Page, system: string, key: string, whose = stack) {
  await page.getByRole("button", { name: "Register with a system" }).click();
  const form = page.getByTestId("register");
  await form.getByLabel("External system (required)").selectOption({ label: system });
  await form.getByLabel("Its key there").fill(key);
  await form.getByLabel("The system confirmed it just now").check();
  await form.getByRole("button", { name: "Register", exact: true }).click();
  await expect(page.getByText(`${whose} is registered with ${system}.`)).toBeVisible();
}

test("S33: a stack registered with two systems: on the stack, not on its members", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // Two switches and the stack they are in.
  await importFile(page, "vendors", `vendors-${suffix}.csv`, ["name"], [[vendor]]);
  await importFile(
    page,
    "catalog_entries",
    `catalog-entries-${suffix}.csv`,
    ["vendor", "pid", "model_name", "type"],
    [[vendor, pid, "Example 9300 48-port", "switch"]],
  );
  await importFile(
    page,
    "items",
    `items-${suffix}.csv`,
    ["vendor", "pid", "serial_number", "hostname", "lifecycle_state"],
    members.map((host, place) => [vendor, pid, `ENR${upper}0${place + 1}`, host, "Prod"]),
  );
  await importFile(
    page,
    "device_groups",
    `device-groups-${suffix}.csv`,
    ["name", "type", "hostname"],
    [[stack, "stack", stack]],
  );
  await importFile(
    page,
    "device_group_members",
    `device-group-members-${suffix}.csv`,
    ["group", "item", "role", "position"],
    [
      [stack, members[0], "master", "1"],
      [stack, members[1], "member", "2"],
    ],
  );

  // The two systems: a monitoring tool and an SDN controller.
  await main(page).getByRole("link", { name: "External systems" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "External systems" })).toBeVisible();
  await newSystem(page, monitoring, "Monitoring");
  await newSystem(page, controller, "SDN controller");

  // The stack is registered with both, from its own page, as one device.
  await openGroup(page, stack);
  const registered = region(page, "Registered with");
  await expect(registered.getByTestId("no-registrations")).toBeVisible();
  await register(page, monitoring, "node-17");
  await register(page, controller, "fabric-3/stack-1");
  await expect(page.getByTestId("registrations").locator("tbody tr")).toHaveCount(2);
  await expect(registration(page, monitoring)).toHaveAttribute("data-status", "registered");
  await expect(registration(page, monitoring)).toContainText("node-17");
  await expect(registration(page, monitoring)).toContainText("Monitoring");
  await expect(registration(page, controller)).toContainText("SDN controller");
  // Each was confirmed as it was made: the moment is shown.
  await expect(registration(page, monitoring).locator("time")).toBeVisible();
  // A record is registered with one system once: neither is offered again.
  await page.getByRole("button", { name: "Register with a system" }).click();
  const offered = page.getByTestId("register").getByLabel("External system (required)");
  await expect(offered.getByRole("option", { name: monitoring })).toHaveCount(0);
  await expect(offered.getByRole("option", { name: controller })).toHaveCount(0);
  await page.getByTestId("register").getByRole("button", { name: "Cancel" }).click();

  // Neither registration is on a member of the stack: a member has none of its own,
  // and says what its stack is registered with, to be read there.
  for (const member of members) {
    await openItem(page, member);
    const own = region(page, "Registered with");
    await expect(own.getByTestId("no-registrations")).toHaveText(
      `${member} has no registration of its own.`,
    );
    await expect(page.getByTestId("registrations")).toHaveCount(0);
    const through = page.getByTestId("group-registrations").locator("tbody tr");
    await expect(through).toHaveCount(2);
    for (const [system, key] of [
      [monitoring, "node-17"],
      [controller, "fabric-3/stack-1"],
    ] as const) {
      const row = page.getByTestId("group-registrations").locator(`tr[data-system="${system}"]`);
      await expect(row).toHaveAttribute("data-group", stack);
      await expect(row).toHaveAttribute("data-status", "registered");
      await expect(row.getByRole("link", { name: stack, exact: true })).toBeVisible();
      await expect(row).toContainText(key);
    }
    // They are the stack's to change: the member's page offers nothing to do to them.
    await expect(
      page.getByTestId("group-registrations").locator("tbody").getByRole("button"),
    ).toHaveCount(0);
  }

  // A member registered by itself was a mistake: the stack is what the system knows.
  // The registration is removed outright, and the member has none of its own again.
  await register(page, monitoring, "node-17-2", members[1]);
  await expect(registration(page, monitoring)).toHaveAttribute("data-status", "registered");
  await registration(page, monitoring)
    .getByRole("button", { name: `Change the registration with ${monitoring}` })
    .click();
  await page
    .getByTestId("change-registration")
    .getByRole("button", { name: "Remove as a mistake" })
    .click();
  await page.getByRole("button", { name: "Remove the registration", exact: true }).click();
  await expect(
    page.getByText(
      `The registration of ${members[1]} with ${monitoring} was removed. The audit trail holds what it was.`,
    ),
  ).toBeVisible();
  await expect(region(page, "Registered with").getByTestId("no-registrations")).toBeVisible();
  await expect(page.getByTestId("registrations")).toHaveCount(0);
  await expect(page.getByTestId("group-registrations").locator("tbody tr")).toHaveCount(2);

  // The grid of groups finds the stack by a system it is registered with. The grid of
  // items finds its two members by it: what knows the stack knows them.
  const bySystem = `registration.system:eq:${monitoring}`;
  await page.goto(`./groups?filter=${encodeURIComponent(bySystem)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("1 group");
  const groups = page.getByTestId("grid-device-groups");
  await expect(groups.getByRole("link", { name: stack, exact: true })).toBeVisible();
  await page.goto(`./items?filter=${encodeURIComponent(bySystem)}&minor=1`);
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  for (const member of members) {
    await expect(
      page.getByTestId("grid-items").getByRole("link", { name: member, exact: true }),
    ).toBeVisible();
  }

  // The system lists what is registered with it: the stack, as a device group.
  await page.goto(`./systems?filter=${encodeURIComponent(`name:eq:${monitoring}`)}`);
  const systems = page.getByTestId("grid-external-systems");
  await expect(systems.locator('[row-id] [col-id="registrations"]')).toHaveText("1");
  await systems.getByRole("link", { name: monitoring, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: monitoring })).toBeVisible();
  await expect(page.getByTestId("system-registrations")).toContainText("1 record");
  await expect(page.getByTestId("grid-total")).toHaveText("1 registration");
  const ofSystem = page.getByTestId("grid-system-registrations").locator("[row-id]");
  await expect(ofSystem.getByRole("link", { name: stack, exact: true })).toBeVisible();
  await expect(ofSystem.locator('[col-id="group.name"]')).toHaveText(stack);
  await expect(ofSystem.locator('[col-id="external_id"]')).toHaveText("node-17");
  await expect(ofSystem.locator('[col-id="status"]')).toHaveText("Registered");

  // A registration that was true and ends is given the status Removed: the row stays,
  // and the system counts it no longer.
  await openGroup(page, stack);
  await registration(page, controller)
    .getByRole("button", { name: `Remove the registration with ${controller}` })
    .click();
  await expect(
    page.getByText(
      `The registration of ${stack} with ${controller} has the status Removed. It stays on record.`,
    ),
  ).toBeVisible();
  await expect(page.getByTestId("registrations").locator("tbody tr")).toHaveCount(2);
  await expect(registration(page, controller)).toHaveAttribute("data-status", "removed");
  await page.goto(`./groups?filter=${encodeURIComponent(`registration.system:eq:${controller}`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("No groups");

  // Registered again, it is the same registration: its key is as it was.
  await openGroup(page, stack);
  await registration(page, controller)
    .getByRole("button", { name: `Register with ${controller} again` })
    .click();
  await expect(registration(page, controller)).toHaveAttribute("data-status", "registered");
  await expect(registration(page, controller)).toContainText("fabric-3/stack-1");
  await expect(page.getByTestId("registrations").locator("tbody tr")).toHaveCount(2);

  await expectClean(page, seen);
});
