// The browser scenario of release 0.4.0, as release 0.4.1 has it, for a controller
// domain: what a person does in S22.
//
//   S22  A controller domain: a cluster of two controllers and forty access points.
//        Forty-two components, the cluster one managed node, each access point lists its
//        controllers.
//
// And what 0.4.1 added: a cluster has a health, and says how it is managed.
//
// On the way: the files of the catalog, the items and the members of a group on the
// Import page.
//
// The scenarios of an item and what is in it are in minor-items.spec.ts, and those of a
// stack and of its addresses in stack.spec.ts. The three were one file, and are three so
// that they run side by side: each loads the catalog and the items it needs, under names
// of its own.
//
// The environment that names the server and the Admin is described in support.ts, with
// what a spec file does to be run beside the others: this one signs in as an Admin of its
// own, and every summary and grid it counts in is filtered down to what it made. Every
// name and serial number below is made up, with the mark of this file and a random part,
// so that the scenarios can be run again on the same server. The scenarios run in order:
// the second uses what the first loads.

import { expect } from "@playwright/test";
import {
  importFile,
  main,
  memberRow,
  openGroup,
  openItem,
  pick,
  region,
  summary,
} from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = mark("wireless");
const upper = suffix.toUpperCase();
const vendor = `Example Networks ${suffix}`;
const controllerPid = `EN-WLC-9800-${suffix}`;
const accessPointPid = `EN-AP-9130-${suffix}`;

// S22: a controller domain.
const wirelessPrefix = `site2-wl-${suffix}`;
const controllers = [`${wirelessPrefix}-wlc-01`, `${wirelessPrefix}-wlc-02`];
const controllerSerials = [`ENW${upper}01`, `ENW${upper}02`];
const accessPoints = Array.from(
  { length: 40 },
  (_, place) => `${wirelessPrefix}-ap-${String(place + 1).padStart(3, "0")}`,
);
const accessPointSerials = accessPoints.map(
  (_, place) => `ENA${upper}${String(place + 1).padStart(3, "0")}`,
);
const domain = `site2-wlan-${suffix}`;
const cluster = `site2-wlc-cluster-${suffix}`;

test("the catalog and the items of the controller domain are loaded from files", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  await importFile(
    page,
    "catalog_entries",
    `catalog-entries-${suffix}.csv`,
    ["vendor", "pid", "model_name", "type", "est_value", "support_weight", "annual_support_cost"],
    [
      [vendor, controllerPid, "Example 9800 controller", "wireless-controller", "30000.00", "", ""],
      [vendor, accessPointPid, "Example 9130 access point", "access-point", "900.00", "", ""],
    ],
  );
  // Two controllers and forty access points.
  await importFile(
    page,
    "items",
    `items-${suffix}-wireless.csv`,
    ["vendor", "pid", "serial_number", "hostname"],
    [
      ...controllers.map((host, place) => [
        vendor,
        controllerPid,
        controllerSerials[place] ?? "",
        host,
      ]),
      ...accessPoints.map((host, place) => [
        vendor,
        accessPointPid,
        accessPointSerials[place] ?? "",
        host,
      ]),
    ],
  );
  await expectClean(page, seen);
});

test("S22: a controller domain, a cluster of controllers and forty access points", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // The domain, with nobody in it yet.
  await main(page).getByRole("link", { name: "Groups" }).click();
  await page.getByRole("button", { name: "New group" }).click();
  let form = region(page, "New group");
  await form.getByLabel("Name (required)").fill(domain);
  await form.getByLabel("Type").selectOption("controller_domain");
  await form.getByRole("button", { name: "Create group" }).click();
  await expect(page.getByRole("heading", { level: 1, name: domain })).toBeVisible();
  await expect(page.getByTestId("member-count")).toHaveText("0 current members");
  await expect(page.getByRole("region", { name: "Health", exact: true })).toHaveCount(0);

  // The cluster of the two controllers, nested in the domain.
  await main(page).getByRole("link", { name: "Groups" }).click();
  await page.getByRole("button", { name: "New group" }).click();
  form = region(page, "New group");
  await form.getByLabel("Name (required)").fill(cluster);
  await form.getByLabel("Type").selectOption("cluster");
  // A cluster says how it is managed, and the form explains the three ways. Left as it
  // is, the cluster is one managed node.
  const managed = form.getByLabel("Managed as");
  await expect(managed.locator("option")).toHaveCount(4);
  await expect(managed.locator('option[value="one"]')).toContainText("One managed node");
  await expect(managed.locator('option[value="members"]')).toContainText("One for each member");
  await expect(managed.locator('option[value="members_and_cluster"]')).toContainText(
    "Its members and a node of its own",
  );
  const explained = form.getByTestId("managed-as-help");
  await expect(explained.getByRole("term")).toHaveText([
    "One managed node",
    "One for each member",
    "Its members and a node of its own",
  ]);
  await expect(explained).toContainText("a pair of wireless LAN controllers in HA");
  await expect(explained).toContainText("a pair of firewalls in HA");
  await expect(explained).toContainText("one more managed node than it has members");
  await form.getByLabel("In group").selectOption({ label: domain });
  for (const host of controllers) {
    await pick(form, "Find an item to add", `${wirelessPrefix}-wlc`, host);
  }
  await form.getByLabel(`Role of ${controllers[0]}`).selectOption("active");
  await form.getByLabel(`Role of ${controllers[1]}`).selectOption("standby");
  await form.getByRole("button", { name: "Create group" }).click();
  await expect(page.getByRole("heading", { level: 1, name: cluster })).toBeVisible();
  await expect(page.getByTestId("member-count")).toHaveText("2 current members");
  await expect(memberRow(page, controllers[1] ?? "")).toHaveAttribute("data-role", "standby");
  await expect(page.getByTestId("managed-as")).toHaveAttribute("data-managed-as", "one");
  await expect(page.getByTestId("managed-as")).toHaveText("One managed node");
  // A cluster has a health, as a stack has. A controller domain has none.
  await expect(region(page, "Health").getByTestId("health")).toHaveAttribute(
    "data-health",
    "unknown",
  );

  // Forty access points join the domain as its endpoints, from a file of members.
  await importFile(
    page,
    "device_group_members",
    `device-group-members-${suffix}.csv`,
    ["group", "item", "role"],
    accessPointSerials.map((serial) => [domain, serial, "endpoint"]),
  );

  // The domain: forty members, and the cluster within it.
  await openGroup(page, domain);
  await expect(page.getByTestId("member-count")).toHaveText("40 current members");
  await expect(page.getByTestId("members").locator("tbody tr")).toHaveCount(40);
  await expect(
    page.getByTestId("nested-groups").getByRole("link", { name: cluster }),
  ).toBeVisible();

  // Each access point lists its controllers: the members of the cluster in its domain,
  // each with the cluster it is in.
  for (const host of [accessPoints[0] ?? "", accessPoints[39] ?? ""]) {
    await openItem(page, host);
    const listed = page.getByTestId("controllers").getByRole("listitem");
    await expect(listed).toHaveCount(2);
    await expect(listed.nth(0)).toContainText(controllers[0] ?? "");
    await expect(listed.nth(1)).toContainText(controllers[1] ?? "");
    for (const place of [0, 1]) {
      await expect(listed.nth(place)).toHaveAttribute("data-cluster", cluster);
      await expect(listed.nth(place).getByRole("link", { name: cluster })).toBeVisible();
    }
    await expect(page.getByTestId("memberships").locator("tbody tr").first()).toContainText(
      "Endpoint",
    );
  }

  // Forty-two components. The cluster is one managed node, and each access point is one.
  await summary(page, `hostname:prefix:${wirelessPrefix}`);
  await expect(page.getByTestId("total-components")).toHaveText("42");
  await expect(page.getByTestId("total-nodes")).toHaveText("41");
  // By type, as the catalog has them, with the labels of the list.
  await page.getByLabel("By", { exact: true }).selectOption("type");
  const rows = page.getByTestId("summary-rows").locator("tbody tr");
  await expect(rows).toHaveCount(2);
  const points = page.getByTestId("summary-rows").locator('tr[data-key="access-point"]');
  await expect(points.locator("td").nth(1)).toHaveText("40");
  await expect(points.locator("td").nth(2)).toHaveText("40");
  const wlcs = page.getByTestId("summary-rows").locator('tr[data-key="wireless-controller"]');
  await expect(wlcs.locator("td").nth(1)).toHaveText("2");
  await expect(wlcs.locator("td").nth(2)).toHaveText("1");
  // The summary can be come back to: what it is by and its filter are in the address.
  await page.reload();
  await expect(page.getByLabel("By", { exact: true })).toHaveValue("type");
  await expect(page.getByLabel("Filter", { exact: true })).toHaveValue(
    `hostname:prefix:${wirelessPrefix}`,
  );
  await expect(page.getByTestId("total-components")).toHaveText("42");

  // How the cluster is managed decides how many managed nodes it is. Each member managed
  // at its own address: one for each, forty-two in all. Components do not change.
  for (const [way, text, nodes] of [
    ["members", "One managed node for each member", "42"],
    [
      "members_and_cluster",
      "One managed node for each member, and one more for the cluster itself",
      "43",
    ],
    ["one", "One managed node", "41"],
  ] as const) {
    await openGroup(page, cluster);
    await region(page, "Details").getByLabel("Managed as").selectOption(way);
    await region(page, "Details").getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("The group was saved.")).toBeVisible();
    await expect(page.getByTestId("managed-as")).toHaveAttribute("data-managed-as", way);
    await expect(page.getByTestId("managed-as")).toHaveText(text);
    await summary(page, `hostname:prefix:${wirelessPrefix}`);
    await expect(page.getByTestId("total-nodes")).toHaveText(nodes);
    await expect(page.getByTestId("total-components")).toHaveText("42");
  }

  // The grid of items, by the group an item is in.
  await page.goto(`./items?filter=${encodeURIComponent(`group.name:eq:${domain}`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("40 items");

  await expectClean(page, seen);
});
