// The browser scenarios of reference files on places, release 0.9.0 (P-158 to P-163):
//
//   S51  A photograph and a floor plan are uploaded to a location, and both are listed
//        with their titles and kinds; the photograph opens in the viewer within the page,
//        from an address of the page's own that is let go when it closes; the plan is
//        downloaded byte for byte. Signed in as View-only, both are listed and
//        downloadable, and nothing can be added or changed.
//
// On the way: a floor plan on a floor is listed on a rack beneath it, under the floor's
// path, and not on the building above it; of three files chosen at once, a program is
// refused in the page and a picture that is a web page by the server, each saying why,
// and the third is uploaded; a file dropped on the section, put on two more records,
// taken off one of them and then erased, after saying that the backups keep a copy, from
// every record it was on; and a link, which opens in a new tab with nothing of hirdir's,
// taken off the last record it is on and so erased.
//
// The file keeps the rules of support.ts: it signs in as an Admin of its own, makes a
// View-only account of its own, and its mark is in every name it gives a record and in
// the title of every reference. The places are made through the API.

import { expect, type Page } from "@playwright/test";
import {
  choose,
  chosen,
  downloaded,
  file,
  filesOf,
  from,
  make,
  openPlace,
  pdf,
  png,
  row,
  session,
} from "./referenceSteps";
import { createAccount, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = mark("references");
const regionName = `Reference Region ${suffix}`;
const siteName = `Reference Site ${suffix}`;
const sitePath = `${regionName} > ${siteName}`;
const buildingPath = `${sitePath} > Building 1`;
const floorPath = `${buildingPath} > Floor 2`;
const rackPath = `${floorPath} > Rack 4`;

const PHOTO = png(`floor-2-${suffix}.png`, 40);
const PHOTO_TITLE = `Floor 2 from the stairs ${suffix}`;
const PLAN = pdf(`b1-floor-2-${suffix}.pdf`, "Building 1, second floor");
const PLAN_TITLE = `b1-floor-2-${suffix}`;

const ids: Record<string, string> = {};

/** The page, with the `blob:` addresses it has let go. */
interface Watched {
  revoked: string[];
}

/** The reference whose changes are open, by its title. */
function changes(page: Page, title: string) {
  return page.getByRole("region", { name: `Change ${title}`, exact: true });
}

async function openChanges(page: Page, title: string) {
  await row(filesOf(page), title)
    .getByRole("button", { name: `Change ${title}` })
    .click();
  await expect(changes(page, title)).toBeVisible();
  return changes(page, title);
}

test("S51: a photograph and a floor plan on a location, viewed and downloaded", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const region = await make(request, headers, "/regions", { name: regionName });
  const site = await make(request, headers, "/sites", { name: siteName, region_hid: region.hid });
  const building = await make(request, headers, "/locations", {
    name: "Building 1",
    site_hid: site.hid,
  });
  const floor = await make(request, headers, "/locations", {
    name: "Floor 2",
    site_hid: site.hid,
    parent_location_hid: building.hid,
  });
  const rack = await make(request, headers, "/locations", {
    name: "Rack 4",
    site_hid: site.hid,
    parent_location_hid: floor.hid,
  });
  Object.assign(ids, {
    site: site.hid,
    building: building.hid,
    floor: floor.hid,
    rack: rack.hid,
  });

  const seen = await watch(page.context());
  await signIn(page, account);
  await openPlace(page, "location", floor.hid, floorPath);
  const section = filesOf(page);
  const own = section.getByRole("region", { name: "Its own", exact: true });
  await expect(own).toContainText("This location has no files or links of its own.");

  // Two at once: each starts titled by its name, and the picture as a photograph.
  await choose(section, [PHOTO, PLAN]);
  const photo = chosen(section, PHOTO.name);
  const plan = chosen(section, PLAN.name);
  await expect(photo.getByLabel("Title")).toHaveValue(`floor-2-${suffix}`);
  await expect(photo.getByLabel("Kind")).toHaveValue("photograph");
  await expect(plan.getByLabel("Title")).toHaveValue(PLAN_TITLE);
  await expect(plan.getByLabel("Kind")).toHaveValue("");
  await photo.getByLabel("Title").fill(PHOTO_TITLE);
  // A kind is required: the plan is not sent until it has one.
  await section.getByRole("button", { name: "Upload 2 files" }).click();
  await expect(plan).toContainText("Choose its kind.");
  await plan.getByLabel("Kind").selectOption({ label: "Floor plan" });
  await section.getByRole("button", { name: "Upload 2 files" }).click();
  await expect(section.getByText("2 files were uploaded.")).toBeVisible({ timeout: 20_000 });

  // Both are listed, each with its title, its kind, its size and who added it.
  await expect(row(own, PHOTO_TITLE).getByTestId("reference-kind")).toHaveText("Photograph");
  await expect(row(own, PLAN_TITLE).getByTestId("reference-kind")).toHaveText("Floor plan");
  await expect(row(own, PLAN_TITLE).getByTestId("reference-size")).toHaveText(
    `${PLAN.buffer.length} bytes`,
  );
  await expect(row(own, PLAN_TITLE)).toContainText(PLAN.name);
  await expect(row(own, PLAN_TITLE)).toContainText(account.username);
  // Only the picture is shown in the page; the plan is downloaded.
  await expect(row(own, PLAN_TITLE).getByRole("button", { name: /^View/ })).toHaveCount(0);

  // The photograph opens in the viewer, from an address of the page's own, and the
  // addresses the page lets go are noted.
  await page.evaluate(() => {
    const watched = window as unknown as Watched;
    watched.revoked = [];
    const letGo = URL.revokeObjectURL.bind(URL);
    URL.revokeObjectURL = (url: string) => {
      watched.revoked.push(url);
      letGo(url);
    };
  });
  await row(own, PHOTO_TITLE)
    .getByRole("button", { name: `View ${PHOTO_TITLE}` })
    .click();
  const viewer = page.getByTestId("picture-viewer");
  await expect(viewer.getByRole("heading", { name: PHOTO_TITLE })).toBeVisible();
  const picture = viewer.getByRole("img", { name: PHOTO_TITLE });
  await expect(picture).toBeVisible();
  const address = (await picture.getAttribute("src")) ?? "";
  expect(address.startsWith("blob:")).toBe(true);
  expect(await picture.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBe(8);
  // Escape closes it, and the address is let go.
  await page.keyboard.press("Escape");
  await expect(viewer).toBeHidden();
  await expect.poll(() => page.evaluate(() => (window as unknown as Watched).revoked)).toContain(address);

  // The plan is downloaded, byte for byte, under its name.
  await downloaded(page, own, PLAN_TITLE, PLAN);
  await expectClean(page, seen);
});

test("a floor plan on a floor is listed on a rack beneath it, under the floor's path", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openPlace(page, "location", ids.rack ?? "", rackPath);
  const section = filesOf(page);
  await expect(section.getByRole("region", { name: "Its own", exact: true })).toContainText(
    "This location has no files or links of its own.",
  );
  const floor = from(section, floorPath);
  await expect(floor.getByRole("heading", { name: floorPath })).toBeVisible();
  await expect(floor.getByRole("link", { name: floorPath })).toHaveAttribute(
    "href",
    new RegExp(`/geography/location/${ids.floor}$`),
  );
  await expect(row(floor, PLAN_TITLE).getByTestId("reference-kind")).toHaveText("Floor plan");
  await expect(row(floor, PHOTO_TITLE)).toBeVisible();
  // It is what the floor has: taken off here, it would be taken off the floor.
  await expect(
    row(floor, PLAN_TITLE).getByRole("button", { name: `Change ${PLAN_TITLE}` }),
  ).toBeVisible();
  await downloaded(page, floor, PLAN_TITLE, PLAN);

  // The building above the floor lists nothing of it.
  await openPlace(page, "location", ids.building ?? "", buildingPath);
  await expect(row(filesOf(page), PLAN_TITLE)).toHaveCount(0);
  await expectClean(page, seen);
});

test("S51, View-only: both are listed and downloadable, and nothing is added or changed", async ({
  browser,
  request,
}) => {
  test.setTimeout(120_000);
  const viewer = await createAccount(request, `e2e-${suffix}-viewer`, "viewer");
  const context = await browser.newContext();
  const page = await context.newPage();
  const seen = await watch(context);
  await signIn(page, viewer);
  await openPlace(page, "location", ids.floor ?? "", floorPath);
  const section = filesOf(page);
  await expect(row(section, PHOTO_TITLE)).toBeVisible();
  await expect(row(section, PLAN_TITLE)).toBeVisible();
  await expect(section.getByRole("region", { name: "Add files" })).toHaveCount(0);
  await expect(section.getByLabel("Choose files")).toHaveCount(0);
  await expect(section.getByRole("button", { name: "Add a link" })).toHaveCount(0);
  await expect(section.getByRole("button", { name: /^Change/ })).toHaveCount(0);
  await downloaded(page, section, PLAN_TITLE, PLAN);
  await row(section, PHOTO_TITLE)
    .getByRole("button", { name: `View ${PHOTO_TITLE}` })
    .click();
  await expect(
    page.getByTestId("picture-viewer").getByRole("img", { name: PHOTO_TITLE }),
  ).toBeVisible();
  await page.getByTestId("picture-viewer").getByRole("button", { name: "Close" }).click();
  await expect(page.getByTestId("picture-viewer")).toBeHidden();
  await expectClean(page, seen);
  await context.close();
});

test("of three files chosen at once, a program and a web page are refused with why, the third uploaded", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openPlace(page, "location", ids.rack ?? "", rackPath);
  const section = filesOf(page);
  const program = file(`setup-${suffix}.exe`, "MZ\x90\x00\x03\x00\x00\x00");
  const disguised = file(
    `rack-4-front-${suffix}.png`,
    "<!doctype html><html><script>alert(1)</script></html>",
    "image/png",
  );
  const back = png(`rack-4-back-${suffix}.png`, 120);
  await choose(section, [program, disguised, back]);
  // The program is refused in the page: it is never sent.
  await expect(chosen(section, program.name)).toHaveAttribute("data-state", "refused");
  await expect(chosen(section, program.name).getByTestId("file-refused")).toContainText(
    "is never taken: it is a web page, a script or a program",
  );
  await section.getByRole("button", { name: "Upload 2 files" }).click();
  await expect(
    section.getByText("1 file was uploaded; 1 file was refused, and says why."),
  ).toBeVisible({ timeout: 20_000 });
  // The web page called a picture is refused by the server, which says why.
  await expect(chosen(section, disguised.name)).toHaveAttribute("data-state", "failed");
  await expect(chosen(section, disguised.name).getByTestId("file-refused")).toContainText(
    "its content is a web page, which is never taken",
  );
  // The third is uploaded, and is a photograph of the rack's own.
  const own = section.getByRole("region", { name: "Its own", exact: true });
  await expect(row(own, `rack-4-back-${suffix}`).getByTestId("reference-kind")).toHaveText(
    "Photograph",
  );
  await expect(row(own, `rack-4-front-${suffix}`)).toHaveCount(0);
  // What was refused is cleared once read.
  await chosen(section, program.name)
    .getByRole("button", { name: `Leave out ${program.name}` })
    .click();
  await expect(chosen(section, program.name)).toHaveCount(0);
  await expectClean(page, seen, ["422 POST"]);
});

test("a file dropped, put on more records, taken off one, then erased from every record", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openPlace(page, "location", ids.rack ?? "", rackPath);
  const section = filesOf(page);
  const wiring = pdf(`rack-4-wiring-${suffix}.pdf`, "Rack 4, the wiring");
  const title = `rack-4-wiring-${suffix}`;

  // Dropped on the section, it is chosen as a file chosen with the button is.
  const dropped = await page.evaluateHandle(
    ({ name, text }) => {
      const transfer = new DataTransfer();
      transfer.items.add(new File([text], name, { type: "application/pdf" }));
      return transfer;
    },
    { name: wiring.name, text: wiring.buffer.toString("latin1") },
  );
  await section.dispatchEvent("dragover", { dataTransfer: dropped });
  await expect(section).toHaveAttribute("data-dragging", "true");
  await section.dispatchEvent("drop", { dataTransfer: dropped });
  await expect(chosen(section, wiring.name)).toBeVisible();
  await chosen(section, wiring.name).getByLabel("Kind").selectOption({ label: "Diagram" });
  await section.getByRole("button", { name: "Upload 1 file" }).click();
  await expect(section.getByText("1 file was uploaded.")).toBeVisible({ timeout: 20_000 });

  // Put on the building and the site, found by searching.
  let panel = await openChanges(page, title);
  const search = panel.getByLabel("Find a record");
  await search.fill(`${siteName} Building 1`);
  await panel.getByRole("button", { name: buildingPath, exact: true }).click();
  await search.fill(siteName);
  await panel.getByRole("button", { name: sitePath, exact: true }).click();
  await expect(panel.getByRole("list", { name: "Records to put it on" })).toContainText(sitePath);
  await panel.getByRole("button", { name: "Put it on 2 records" }).click();
  await expect(section.getByText(`${title} is on 2 more records: 3 records in all.`)).toBeVisible();

  // Taken off the building, which is not the last record it is on: it stays on the others.
  await openPlace(page, "location", ids.building ?? "", buildingPath);
  panel = await openChanges(page, title);
  await expect(panel).toContainText("It stays on the 2 other records it is on.");
  await panel.getByRole("button", { name: "Take off this location" }).click();
  await expect(filesOf(page).getByText(`${title} was taken off this location.`)).toBeVisible();
  await expect(
    row(filesOf(page).getByRole("region", { name: "Its own", exact: true }), title),
  ).toHaveCount(0);
  // Still the site's, which the building lists beneath its own.
  await expect(row(from(filesOf(page), sitePath), title)).toBeVisible();

  // Erased from the rack: it says first what that does, and the backups keep a copy.
  await openPlace(page, "location", ids.rack ?? "", rackPath);
  panel = await openChanges(page, title);
  await panel.getByRole("button", { name: "Erase", exact: true }).click();
  const ask = page.getByRole("dialog", { name: `Erase ${title}?` });
  await expect(ask).toContainText(
    "The file and its content are erased at once, from all 2 records it is on.",
  );
  await expect(ask).toContainText(
    "The backups on the server keep a copy until they rotate out: 14 days, unless the server is set otherwise.",
  );
  await expect(ask.getByRole("link", { name: rackPath, exact: true })).toBeVisible();
  await expect(ask.getByRole("link", { name: sitePath, exact: true })).toBeVisible();
  await ask.getByRole("button", { name: "Erase it" }).click();
  await expect(
    filesOf(page).getByText(`${title} was erased from every record it was on.`),
  ).toBeVisible();
  await expect(row(filesOf(page), title)).toHaveCount(0);
  // Gone from the site as well.
  await openPlace(page, "site", ids.site ?? "", sitePath);
  await expect(row(filesOf(page), title)).toHaveCount(0);
  await expectClean(page, seen);
});

test("a link opens in a new tab, and taken off its last record it is erased, after asking", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openPlace(page, "site", ids.site ?? "", sitePath);
  const section = filesOf(page);
  const title = `Site survey ${suffix}`;
  const address = `https://maps.example.com/${suffix}/site-survey`;
  await section.getByRole("button", { name: "Add a link" }).click();
  const form = section.getByRole("region", { name: "Add a link", exact: true });
  await form.getByLabel("Title").fill(title);
  await form.getByLabel("Kind").selectOption({ label: "Map" });
  await form.getByLabel("Address").fill(address);
  await form.getByRole("button", { name: "Add the link" }).click();
  await expect(section.getByText(`The link ${title} was added.`)).toBeVisible();
  const link = row(section, title).getByRole("link", { name: title });
  await expect(link).toHaveAttribute("href", address);
  await expect(link).toHaveAttribute("target", "_blank");
  await expect(link).toHaveAttribute("rel", "noopener noreferrer");
  await expect(row(section, title)).toContainText(address);
  await expect(row(section, title).getByRole("button", { name: /^Download/ })).toHaveCount(0);

  // Its address is changed. The panel stays open, read again, for the next change.
  const panel = await openChanges(page, title);
  await panel.getByLabel("Address").fill(`${address}-2027`);
  await panel.getByRole("button", { name: "Save" }).click();
  await expect(section.getByText(`${title} was saved.`)).toBeVisible();
  await expect(row(section, title).getByRole("link", { name: title })).toHaveAttribute(
    "href",
    `${address}-2027`,
  );
  await expect(panel.getByLabel("Address")).toHaveValue(`${address}-2027`);

  // The site is the only record it is on: taking it off erases it, which is asked first.
  await panel.getByRole("button", { name: "Take off this site" }).click();
  const ask = page.getByRole("dialog", { name: `Take ${title} off the last record it is on?` });
  await expect(ask).toContainText(
    "This site is the only record it is on: taken off, it is erased.",
  );
  await expect(ask).toContainText("The link is erased at once, from the record it is on.");
  await expect(ask).toContainText("The backups on the server keep a copy until they rotate out");
  await ask.getByRole("button", { name: "Take it off and erase it" }).click();
  await expect(
    section.getByText(`${title} was taken off this site, the last record it was on, and erased.`),
  ).toBeVisible();
  await expect(row(section, title)).toHaveCount(0);
  await expectClean(page, seen);
});
