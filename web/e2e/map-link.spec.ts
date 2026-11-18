// 0.9.7, the coordinates of a place open a map (P-229): where the place's answer has
// `map_url`, the coordinates on its page are a link to it, in a new tab with nothing of
// the app's; where the place has no coordinates, there is no link. The setting
// `map_link` is not changed here, since every file reads it: Google Maps, its default.
//
// The file keeps the rules of support.ts: an Admin of its own, and its mark in the name
// of every place, which are made through the API. The coordinates are invented.

import { expect, type Page } from "@playwright/test";
import { make, session } from "./referenceSteps";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = mark("map-link");
const regionName = `Example Region ${suffix}`;
const siteName = `Site-M ${suffix}`;

async function openPlace(page: Page, level: string, hid: string, path: string) {
  await page.goto(`./geography/${level}/${encodeURIComponent(hid)}`);
  await expect(page.getByTestId("place-path")).toHaveText(path);
}

test("a site and a location with coordinates link to their map, and one with none does not", async ({
  page,
  account,
  request,
}) => {
  const headers = await session(request, account);
  const region = await make(request, headers, "/regions", { name: regionName });
  const site = await make(request, headers, "/sites", {
    name: siteName,
    region_hid: region.hid,
    latitude: "41.878100",
    longitude: "-87.629800",
  });
  const room = await make(request, headers, "/locations", {
    name: "Room 1",
    site_hid: site.hid,
    latitude: "41.878200",
    longitude: "-87.629900",
  });
  const hall = await make(request, headers, "/locations", { name: "Hall 2", site_hid: site.hid });
  const seen = await watch(page.context());
  await signIn(page, account);

  await openPlace(page, "site", site.hid, `${regionName} > ${siteName}`);
  const map = page.getByTestId("place-facts").getByTestId("place-map");
  await expect(map).toHaveText("41.878100, -87.629800");
  await expect(map).toHaveAttribute(
    "href",
    "https://www.google.com/maps/search/?api=1&query=41.878100,-87.629800",
  );
  await expect(map).toHaveAttribute("target", "_blank");
  await expect(map).toHaveAttribute("rel", "noopener noreferrer");

  await openPlace(page, "location", room.hid, `${regionName} > ${siteName} > Room 1`);
  await expect(page.getByTestId("place-facts").getByTestId("place-map")).toHaveAttribute(
    "href",
    "https://www.google.com/maps/search/?api=1&query=41.878200,-87.629900",
  );

  // No coordinates: no link, and no numbers.
  await openPlace(page, "location", hall.hid, `${regionName} > ${siteName} > Hall 2`);
  await expect(page.getByTestId("place-facts")).toBeVisible();
  await expect(page.getByTestId("place-map")).toHaveCount(0);
  await expectClean(page, seen);
});
