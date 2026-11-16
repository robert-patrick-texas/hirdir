// The browser scenarios of reference files on the catalog, release 0.9.0 (P-158 to P-163):
//
//   S52  An administration guide is uploaded to a catalog entry, and an item of that model
//        lists it, as its model's, and downloads it from there; no request of the page goes
//        to another origin.
//
// On the way: the guide put on a second model, and a new edition of it that says first it
// replaces the file on both and then does, on both at once; Admin › Files, which lists
// every reference, narrowed by its title, with the records each is on and its download;
// the kinds of reference among the lists of Admin › Choices; and the setting
// `reference_file_types`, a list of extensions to which an Admin adds one, which the
// server refuses where it is a program's, and which is returned to its default.
//
// The file keeps the rules of support.ts: it signs in as an Admin of its own, and its
// mark is in every name it gives a record and in the title of every reference. It
// changes `reference_file_types`, which references.spec.ts reads when it uploads: it only
// adds to the list, which lets more through and refuses nothing references.spec.ts
// sends, and returns it to its default, so it runs beside the others, as settings.spec.ts
// does with the limit it raises.

import { expect, type Page } from "@playwright/test";
import {
  choose,
  chosen,
  downloaded,
  file,
  filesOf,
  from,
  make,
  pdf,
  row,
  session,
} from "./referenceSteps";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = mark("reference-guides");
const vendor = `Example Networks ${suffix}`;
const first = `EN-9300-24P-${suffix}`;
const second = `EN-9300-48P-${suffix}`;
const host = `site9-sw-guides-${suffix}`;

const GUIDE = pdf(`en9300-admin-${suffix}.pdf`, "Example 9300 administration guide, 2026");
const GUIDE_TITLE = `en9300-admin-${suffix}`;
const EDITION = pdf(`en9300-admin-2027-${suffix}.pdf`, "Example 9300 administration guide, 2027");

const ids: Record<string, string> = {};

async function openEntry(page: Page, hid: string, pid: string) {
  await page.goto(`./catalog/${encodeURIComponent(hid)}`);
  await expect(page.getByRole("heading", { level: 1, name: `${vendor} ${pid}` })).toBeVisible();
  await expect(filesOf(page).getByRole("region", { name: "Its own", exact: true })).toBeVisible();
}

async function openChanges(page: Page, title: string) {
  await row(filesOf(page), title)
    .getByRole("button", { name: `Change ${title}` })
    .click();
  const panel = page.getByRole("region", { name: `Change ${title}`, exact: true });
  await expect(panel).toBeVisible();
  return panel;
}

test("S52: an administration guide on a model, downloaded from an item of it, from no other origin", async ({
  page,
  account,
  request,
  baseURL,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const maker = await make(request, headers, "/vendors", { name: vendor });
  const one = await make(request, headers, "/catalog-entries", {
    vendor_hid: maker.hid,
    pid: first,
    model_name: "Example 9300 24-port",
  });
  const other = await make(request, headers, "/catalog-entries", {
    vendor_hid: maker.hid,
    pid: second,
    model_name: "Example 9300 48-port",
  });
  const region = await make(request, headers, "/regions", { name: `Guides Region ${suffix}` });
  const site = await make(request, headers, "/sites", {
    name: `Guides Site ${suffix}`,
    region_hid: region.hid,
  });
  const room = await make(request, headers, "/locations", { name: "Room 102", site_hid: site.hid });
  const item = await make(request, headers, "/items", {
    catalog_entry_hid: one.hid,
    hostname: host,
    serial_number: `ENG${suffix.toUpperCase().replace(/-/g, "")}1`,
    location_hid: room.hid,
  });
  Object.assign(ids, { first: one.hid, second: other.hid, item: item.hid });

  const seen = await watch(page.context());
  const origin = new URL(baseURL ?? "").origin;
  const elsewhere: string[] = [];
  page.on("request", (sent) => {
    if (new URL(sent.url()).origin !== origin) elsewhere.push(sent.url());
  });
  await signIn(page, account);

  // The model's links of 0.7.0 are listed first, in the section, and edited as they were.
  await openEntry(page, one.hid, first);
  const section = filesOf(page);
  await expect(section.getByRole("region", { name: "Links", exact: true })).toContainText(
    "This catalog entry has no links.",
  );
  // A file on a catalog entry starts as its administration guide.
  await choose(section, [GUIDE]);
  await expect(chosen(section, GUIDE.name).getByLabel("Kind")).toHaveValue("administration_guide");
  await section.getByRole("button", { name: "Upload 1 file" }).click();
  await expect(section.getByText("1 file was uploaded.")).toBeVisible({ timeout: 20_000 });
  await expect(row(section, GUIDE_TITLE).getByTestId("reference-kind")).toHaveText(
    "Administration guide",
  );

  // The item lists it as its model's, and downloads it from there.
  await page.goto(`./items/${encodeURIComponent(item.hid)}`);
  await expect(page.getByRole("heading", { level: 1, name: host })).toBeVisible();
  const items = filesOf(page);
  await expect(items.getByRole("region", { name: "Its own", exact: true })).toContainText(
    "This item has no files or links of its own.",
  );
  const model = from(items, `${vendor} ${first}`);
  await expect(
    model.getByRole("heading", { name: `Of its model, ${vendor} ${first}` }),
  ).toBeVisible();
  await expect(model).toHaveAttribute("data-source", "catalog");
  await downloaded(page, model, GUIDE_TITLE, GUIDE);

  expect(elsewhere, "requests to another origin").toEqual([]);
  await expectClean(page, seen);
});

test("a new edition says first it replaces the guide on both models, then does, on both", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openEntry(page, ids.first ?? "", first);

  // Put on the second model, found by its PID.
  const panel = await openChanges(page, GUIDE_TITLE);
  await panel.getByLabel("Find a record").fill(second);
  await panel.getByRole("button", { name: `${vendor} ${second}`, exact: true }).click();
  await panel.getByRole("button", { name: "Put it on 1 record" }).click();
  await expect(
    filesOf(page).getByText(`${GUIDE_TITLE} is on 1 more record: 2 records in all.`),
  ).toBeVisible();

  // The new edition, in the panel that stays open, names both before it is put in place.
  const edition = panel.getByRole("region", { name: "New edition", exact: true });
  await expect(edition).toContainText(`A new edition replaces ${GUIDE.name}`);
  await expect(edition).toContainText("on all 2 records it is on, at once");
  await expect(
    edition.getByRole("link", { name: `${vendor} ${first}`, exact: true }),
  ).toBeVisible();
  await expect(
    edition.getByRole("link", { name: `${vendor} ${second}`, exact: true }),
  ).toBeVisible();
  // One of a kind that is never taken is refused before it is sent.
  await edition
    .getByLabel("The new edition")
    .setInputFiles([file(`guide-${suffix}.html`, "<html></html>", "text/html")]);
  await expect(edition.getByTestId("edition-refused")).toContainText("is never taken");
  await expect(
    edition.getByRole("button", { name: "Put the new edition in place" }),
  ).toBeDisabled();
  await edition.getByLabel("The new edition").setInputFiles([EDITION]);
  await edition.getByRole("button", { name: "Put the new edition in place" }).click();
  await expect(
    filesOf(page).getByText(`A new edition of ${GUIDE_TITLE} is in place on 2 records.`),
  ).toBeVisible({ timeout: 20_000 });
  await expect(row(filesOf(page), GUIDE_TITLE)).toContainText(EDITION.name);

  // The second model has the new edition too, and so has the item of the first.
  await openEntry(page, ids.second ?? "", second);
  await downloaded(page, filesOf(page), GUIDE_TITLE, EDITION);
  await page.goto(`./items/${encodeURIComponent(ids.item ?? "")}`);
  await expect(page.getByRole("heading", { level: 1, name: host })).toBeVisible();
  await downloaded(page, from(filesOf(page), `${vendor} ${first}`), GUIDE_TITLE, EDITION);
  await expectClean(page, seen);
});

test("Admin › Files lists every reference, narrowed by title, with its records and its download", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./admin");
  await page
    .getByRole("navigation", { name: "Admin" })
    .getByRole("link", { name: "Files" })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: "Files" })).toBeVisible();
  const narrow = page.getByRole("form", { name: "Narrow the files" });
  await narrow.getByLabel("Title holds").fill(suffix);
  await narrow.getByLabel("Form").selectOption("file");
  await narrow.getByRole("button", { name: "Filter" }).click();
  const table = page.getByTestId("reference-files");
  await expect(table.locator("tbody tr")).toHaveCount(1);
  const guide = row(table, GUIDE_TITLE);
  await expect(guide).toContainText("Administration guide");
  await expect(guide).toContainText("File");
  await expect(guide).toContainText(EDITION.name);
  await expect(guide).toContainText(`${EDITION.buffer.length} bytes`);
  await guide.getByText("2 records").click();
  await expect(guide.getByRole("link", { name: `${vendor} ${first}`, exact: true })).toBeVisible();
  await guide.getByRole("link", { name: `${vendor} ${second}`, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: `${vendor} ${second}` })).toBeVisible();
  await page.goBack();
  await expect(row(page.getByTestId("reference-files"), GUIDE_TITLE)).toBeVisible();
  await downloaded(page, page.getByTestId("reference-files"), GUIDE_TITLE, EDITION);
  // Links are not files.
  await page
    .getByRole("form", { name: "Narrow the files" })
    .getByLabel("Form")
    .selectOption("link");
  await page
    .getByRole("form", { name: "Narrow the files" })
    .getByRole("button", { name: "Filter" })
    .click();
  await expect(page.getByTestId("reference-files")).toContainText("No reference matches.");
  await expectClean(page, seen);
});

test("the kinds of reference are a list of Admin › Choices", async ({ page, account }) => {
  test.setTimeout(60_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./admin/choices");
  await expect(page.getByRole("heading", { level: 1, name: "Choices" })).toBeVisible();
  await page.getByLabel("List", { exact: true }).selectOption({ label: "Reference kind" });
  await expect(page).toHaveURL(/list=reference_kind/);
  for (const value of [
    "photograph",
    "floor_plan",
    "administration_guide",
    "letter_of_authorization",
  ]) {
    await expect(page.getByRole("rowheader", { name: value, exact: true })).toBeVisible();
  }
  await expectClean(page, seen);
});

test("reference_file_types is a list an Admin adds to, never a program's, and returns to its default", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  const key = "reference_file_types";
  await page.goto("./admin/settings");
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  // The extensions never taken are among the fixed values.
  await expect(page.getByTestId("fixed-refused_file_types")).toContainText("exe");
  await expect(page.getByTestId("fixed-refused_file_types")).toContainText("svg");

  const settingRow = page.getByTestId("settings").locator(`tr[data-setting="${key}"]`);
  await settingRow.getByRole("button", { name: `Change ${key}` }).click();
  let form = page.getByTestId("setting-form");
  const list = form.getByRole("list", { name: "The extensions it takes" });
  await expect(list).toContainText("pdf");
  await form.getByLabel("Add an extension").fill(".KMZ");
  await form.getByLabel("Add an extension").press("Enter");
  await expect(list.getByText("kmz", { exact: true })).toBeVisible();
  await form.getByRole("button", { name: "Set" }).click();
  await expect(page.getByTestId(`value-${key}`)).toContainText("kmz");
  await expect(page.getByTestId(`standing-${key}`)).toHaveText("Set here");

  // A file of the kind added is taken now: kept, and downloaded as any other.
  await page.goto(`./catalog/${encodeURIComponent(ids.first ?? "")}`);
  const section = filesOf(page);
  const kmz = file(
    `site-survey-${suffix}.kmz`,
    Buffer.from([0x50, 0x4b, 0x03, 0x04, 0x14, 0, 0, 0]),
  );
  await choose(section, [kmz]);
  await chosen(section, kmz.name).getByLabel("Kind").selectOption({ label: "Map" });
  await section.getByRole("button", { name: "Upload 1 file" }).click();
  await expect(section.getByText("1 file was uploaded.")).toBeVisible({ timeout: 20_000 });
  await downloaded(page, section, `site-survey-${suffix}`, kmz);

  // A program's extension is refused by the server, which says what it takes.
  await page.goto("./admin/settings");
  await page
    .getByTestId("settings")
    .locator(`tr[data-setting="${key}"]`)
    .getByRole("button", { name: `Change ${key}` })
    .click();
  form = page.getByTestId("setting-form");
  await form.getByLabel("Add an extension").fill("exe");
  await form.getByRole("button", { name: "Add", exact: true }).click();
  await form.getByRole("button", { name: "Set" }).click();
  await expect(form.getByTestId("extensions-refused")).toContainText(
    "none of a web page, a script or a program",
  );
  await form.getByRole("button", { name: "Remove exe" }).click();
  await expect(
    form.getByRole("list", { name: "The extensions it takes" }).getByText("exe", { exact: true }),
  ).toHaveCount(0);

  // And back to its default.
  await form.getByRole("button", { name: "Return to its default" }).click();
  await expect(page.getByTestId(`standing-${key}`)).toHaveText("At its default");
  await expect(page.getByTestId(`value-${key}`)).not.toContainText("kmz");
  await expectClean(page, seen, ["422 PUT"]);
});
