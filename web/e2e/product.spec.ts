// The browser scenarios of the product name and of whom to ask, of 0.9.2 (P-168, P-169):
//
//   An Admin names the product on the Settings page. The menu bar and the title of the
//   tab say it at once; an export of the grid and the scoreboard's two files are named
//   after it, and the Import page still guesses what the exported file holds; About gives
//   it as the product, and the software as hirdir with its version; the sign-in page says
//   it when the Admin signs out, and again when the page is loaded afresh. Returned to its
//   default, the product is hirdir again.
//   Whom to ask: About says that nobody has been named, and tells an Admin where they are
//   set. The Admin sets the four, each in a text box, and About lists them: the
//   organization, the address to write to, the number to call and the address on the web,
//   which opens in a new tab. help_on_sign_in is Yes or No; turned on, the sign-in page
//   lists them under the form, and turned off, it lists nothing of them, and the page
//   that is served holds nothing of them either.
//
// How this file keeps to rule 5 of support.ts: it changes `product_name`, which the title
// of every page, the heading of the sign-in page and the name of every download read, and
// the five settings of whom to ask, which the sign-in page lists. So it runs in the
// project "the name alone" of playwright.config.ts, by itself, when every other project
// has ended. It notes the six settings as it found them, and puts them back however it
// ends. What it exports and counts is of its own item alone.

import { readFile } from "node:fs/promises";
import {
  type APIRequestContext,
  type Download,
  expect,
  type Locator,
  type Page,
} from "@playwright/test";
import { main as menuBar } from "./structure";
import { type Account, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = mark("product");
const vendor = `Example Networks ${suffix}`;
const pid = `EN-P-24-${suffix}`;
const hostname = `site9-sw-${suffix}`;
const filter = `hostname:eq:${hostname}`;

const PRODUCT = "Example Inventory";
const STEM = "Example-Inventory";
const HELP = {
  help_organization: "Network Tools, Example Corp",
  help_email: "tools@example.net",
  help_phone: "+1 555 0100",
  help_url: "https://help.example.net/network-tools",
} as const;

// The settings this file changes, which it puts back as it found them.
const SETTINGS = ["product_name", ...Object.keys(HELP), "help_on_sign_in"] as const;

type Headers = { Authorization: string };

/** Sign in through the API as the account of the file, for what is done there. */
async function session(request: APIRequestContext, account: Account): Promise<Headers> {
  const answer = await request.post("./api/v1/auth/sign-in", {
    data: { username: account.username, access_code: account.accessCode },
  });
  expect(answer.status(), "the account of the file signs in through the API").toBe(200);
  const { token } = (await answer.json()) as { token: string };
  return { Authorization: `Bearer ${token}` };
}

async function send<T = { hid: string }>(
  request: APIRequestContext,
  headers: Headers,
  method: "post" | "put",
  path: string,
  data: unknown,
  status = method === "post" ? 201 : 200,
): Promise<T> {
  const answer = await request[method](`./api/v1${path}`, { headers, data });
  expect(answer.status(), `${method} ${path}: ${await answer.text()}`).toBe(status);
  return (await answer.json()) as T;
}

async function read<T>(request: APIRequestContext, headers: Headers, path: string): Promise<T> {
  const answer = await request.get(`./api/v1${path}`, { headers });
  expect(answer.status(), `get ${path}`).toBe(200);
  return (await answer.json()) as T;
}

interface Setting {
  key: string;
  value: unknown;
  is_default: boolean;
  row_version: number;
}

async function setting(request: APIRequestContext, headers: Headers, key: string) {
  const all = await read<Setting[]>(request, headers, "/settings");
  const found = all.find((one) => one.key === key);
  if (!found) throw new Error(`there is no setting ${key}`);
  return found;
}

/** Give a setting a value, or its default for null. */
async function put(request: APIRequestContext, headers: Headers, key: string, value: unknown) {
  const { row_version } = await setting(request, headers, key);
  await send(request, headers, "put", `/settings/${key}`, { row_version, value });
}

// The settings as this file found them: null for one at its default.
const found = new Map<string, unknown>();

test.beforeAll(async ({ request, accounts }) => {
  const headers = await session(request, await accounts.of("product"));
  for (const key of SETTINGS) {
    const now = await setting(request, headers, key);
    found.set(key, now.is_default ? null : now.value);
  }
  // One item of its own, for an export and for the scoreboard to hold.
  const maker = await send(request, headers, "post", "/vendors", { name: vendor });
  const model = await send(request, headers, "post", "/catalog-entries", {
    vendor_hid: maker.hid,
    pid,
  });
  await send(request, headers, "post", "/items", { catalog_entry_hid: model.hid, hostname });
});

test.afterAll(async ({ request, accounts }) => {
  const headers = await session(request, await accounts.of("product"));
  for (const key of SETTINGS) {
    const now = await setting(request, headers, key);
    const was = found.get(key) ?? null;
    if ((now.is_default ? null : now.value) !== was) await put(request, headers, key, was);
  }
});

/** The table of the settings, opened from the menu bar and Admin's own row of links. */
async function openSettings(page: Page) {
  await menuBar(page).getByRole("link", { name: "Admin", exact: true }).click();
  await page
    .getByRole("navigation", { name: "Admin" })
    .getByRole("link", { name: "Settings" })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  return page.getByTestId("settings");
}

/** Type a new value of a setting in its form, and set it. */
async function typeSetting(page: Page, key: string, value: string) {
  const table = page.getByTestId("settings");
  await table.getByRole("button", { name: `Change ${key}`, exact: true }).click();
  const form = page.getByTestId("setting-form");
  await expect(form.getByRole("heading", { name: `Change ${key}` })).toBeVisible();
  await form.getByLabel("New value").fill(value);
  await form.getByRole("button", { name: "Set" }).click();
  await expect(page.getByText(`${key} was set to ${value}.`, { exact: true })).toBeVisible();
  await expect(table.getByTestId(`value-${key}`)).toHaveText(value);
}

/** Turn help_on_sign_in on or off, by the choice of two its form offers. */
async function chooseOnSignIn(page: Page, on: boolean) {
  const table = page.getByTestId("settings");
  await table.getByRole("button", { name: "Change help_on_sign_in", exact: true }).click();
  const form = page.getByTestId("setting-form");
  await expect(form).toContainText("The default is No.");
  const shown = on ? "Yes" : "No";
  await form.getByRole("radio", { name: shown, exact: true }).check();
  await form.getByRole("button", { name: "Set" }).click();
  await expect(
    page.getByText(`help_on_sign_in was set to ${shown}.`, { exact: true }),
  ).toBeVisible();
  await expect(table.getByTestId("value-help_on_sign_in")).toHaveText(shown);
}

async function signOut(page: Page) {
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
}

/** What the page that was served carries for the web UI before signing in. */
async function served(page: Page): Promise<{ product_name: string; help: unknown }> {
  const content = await page.locator('meta[name="hirdir-site"]').getAttribute("content");
  return JSON.parse(content ?? "null");
}

/** Save a download where the test keeps its files, and give back what it holds. */
async function saved(download: Download, path: string): Promise<Buffer> {
  await download.saveAs(path);
  return readFile(path);
}

test("an Admin names the product, and the menu bar, the tab, the files and the sign-in page say it", async ({
  page,
  account,
  request,
}, testInfo) => {
  test.setTimeout(120_000);
  const headers = await session(request, account);
  const before = String((await setting(request, headers, "product_name")).value);
  const seen = await watch(page.context());
  await signIn(page, account, before);
  await expect(page.getByTestId("brand")).toHaveText(before);

  // Named on the Settings page: the menu bar and the title say it at once.
  const table = await openSettings(page);
  await expect(table.getByTestId("default-product_name")).toHaveText("hirdir");
  await typeSetting(page, "product_name", PRODUCT);
  await expect(page.getByTestId("brand")).toHaveText(PRODUCT);
  await expect(page).toHaveTitle(`Settings · ${PRODUCT}`);

  // An export of the grid is named after it, by the server, and the Import page still
  // guesses what the file holds from its name.
  await page.goto(`./items?filter=${encodeURIComponent(filter)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  await expect(page).toHaveTitle(`Items · ${PRODUCT}`);
  await expect(page.getByTestId("brand")).toHaveText(PRODUCT);
  let download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const exported = await download;
  const exportName = exported.suggestedFilename();
  expect(exportName).toMatch(new RegExp(`^${STEM}-items-\\d{8}T\\d{6}[+-]\\d{4}\\.csv$`));
  const content = await saved(exported, testInfo.outputPath(exportName));
  expect(content.toString("utf8")).toContain(pid);
  await page.goto("./import");
  await expect(page.getByRole("heading", { level: 1, name: "Import" })).toBeVisible();
  await page
    .getByLabel("File", { exact: true })
    .setInputFiles({ name: exportName, mimeType: "text/csv", buffer: content });
  await expect(page.getByLabel("Records")).toHaveValue("items");

  // The scoreboard's two files, which the page makes itself.
  await page.goto(`./reports/scoreboard?${new URLSearchParams({ filter }).toString()}`);
  await expect(page.getByRole("heading", { level: 1, name: "Scoreboard" })).toBeVisible();
  for (const [which, name] of [
    ["operators", `${STEM}-scoreboard-operators.csv`],
    ["sites", `${STEM}-scoreboard-sites.csv`],
  ] as const) {
    const button = page.getByRole("button", { name: `Export CSV of the ${which}` });
    await expect(button).toBeEnabled();
    download = page.waitForEvent("download");
    await button.click();
    expect((await download).suggestedFilename()).toBe(name);
  }

  // About: the product by its name, and the software that it is.
  const about = await read<{ name: string; version: string }>(request, headers, "/about");
  await menuBar(page).getByRole("link", { name: "About", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "About" })).toBeVisible();
  await expect(page.getByTestId("about-product")).toHaveText(PRODUCT);
  await expect(page.getByTestId("about-software")).toHaveText(`hirdir ${about.version}`);
  expect(about.name).toBe("hirdir");
  await expect(page).toHaveTitle(`About · ${PRODUCT}`);

  // The sign-in page names it once the Admin signs out, and when it is loaded afresh,
  // from what the server writes into the page.
  await signOut(page);
  const heading = page.getByRole("heading", {
    level: 1,
    name: `Sign in to ${PRODUCT}`,
    exact: true,
  });
  await expect(heading).toBeVisible();
  await expect(page).toHaveTitle(`Sign in · ${PRODUCT}`);
  await page.reload();
  await expect(heading).toBeVisible();
  await expect(page).toHaveTitle(`Sign in · ${PRODUCT}`);
  expect(await served(page)).toEqual({ product_name: PRODUCT, help: null });

  // Returned to its default, it is hirdir again, at once.
  await signIn(page, account, PRODUCT);
  await expect(page.getByTestId("brand")).toHaveText(PRODUCT);
  await openSettings(page);
  await table.getByRole("button", { name: "Return product_name to its default" }).click();
  await expect(page.getByText("product_name is at its default again: hirdir.")).toBeVisible();
  await expect(page.getByTestId("brand")).toHaveText("hirdir");
  await expect(page).toHaveTitle("Settings · hirdir");
  await expectClean(page, seen);
});

test("whom to ask is on About once it is set, and on the sign-in page only where an Admin turns that on", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  const headers = await session(request, account);
  // From nobody named, and the product at its default.
  for (const key of SETTINGS) await put(request, headers, key, null);
  const seen = await watch(page.context());
  await signIn(page, account);
  expect(await served(page)).toEqual({ product_name: "hirdir", help: null });

  // Nobody named: About says so, and tells an Admin where they are set.
  await menuBar(page).getByRole("link", { name: "About", exact: true }).click();
  const nobody = page.getByTestId("nobody-to-ask");
  await expect(nobody).toContainText("Nobody has been named yet.");
  await expect(page.getByTestId("whom-to-ask")).toHaveCount(0);
  await nobody.getByRole("link", { name: "Admin › Settings" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();

  // Each is typed in a text box, blank by default.
  const table = page.getByTestId("settings");
  for (const [key, value] of Object.entries(HELP)) {
    await expect(table.getByTestId(`default-${key}`)).toHaveText("Blank");
    await typeSetting(page, key, value);
  }
  // help_on_sign_in is Yes or No, and No by default.
  await expect(table.getByTestId("value-help_on_sign_in")).toHaveText("No");
  await expect(table.getByTestId("default-help_on_sign_in")).toHaveText("No");

  // About lists them: what to write to, to call and to open, each a link.
  await menuBar(page).getByRole("link", { name: "About", exact: true }).click();
  await expect(page.getByTestId("nobody-to-ask")).toHaveCount(0);
  const listed = page.getByRole("region", { name: "Whom to ask" }).getByTestId("whom-to-ask");
  await expectListed(listed);

  // While help_on_sign_in is No, the sign-in page lists nothing of them.
  await signOut(page);
  await expect(page.getByRole("heading", { level: 1, name: "Sign in to hirdir" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Whom to ask" })).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Sign in to hirdir" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Whom to ask" })).toHaveCount(0);
  expect(await served(page)).toEqual({ product_name: "hirdir", help: null });
  expect(await page.content()).not.toContain(HELP.help_email);

  // Turned on: the sign-in page lists them under the form, when the Admin signs out and
  // when the page is loaded afresh.
  await signIn(page, account);
  await openSettings(page);
  await chooseOnSignIn(page, true);
  await expect(table.getByTestId("standing-help_on_sign_in")).toHaveText("Set here");
  await signOut(page);
  const onSignIn = page.getByRole("region", { name: "Whom to ask" });
  await expect(onSignIn).toContainText("If you cannot sign in, ask the team that runs hirdir:");
  await expectListed(onSignIn.getByTestId("whom-to-ask"));
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Sign in to hirdir" })).toBeVisible();
  await expectListed(onSignIn.getByTestId("whom-to-ask"));
  expect(await served(page)).toEqual({
    product_name: "hirdir",
    help: {
      organization: HELP.help_organization,
      email: HELP.help_email,
      phone: HELP.help_phone,
      url: HELP.help_url,
    },
  });

  // Turned off again: nothing of them on the sign-in page, nor in the page served.
  await signIn(page, account);
  await openSettings(page);
  await chooseOnSignIn(page, false);
  await signOut(page);
  await expect(page.getByRole("heading", { level: 1, name: "Sign in to hirdir" })).toBeVisible();
  await expect(onSignIn).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Sign in to hirdir" })).toBeVisible();
  await expect(onSignIn).toHaveCount(0);
  expect(await served(page)).toEqual({ product_name: "hirdir", help: null });
  expect(await page.content()).not.toContain(HELP.help_email);
  await expectClean(page, seen);
});

/** The four of whom to ask, each as it is set, and the three that are links, as links. */
async function expectListed(listed: Locator) {
  await expect(listed.getByTestId("help-organization")).toHaveText(HELP.help_organization);
  const email = listed.getByTestId("help-email").getByRole("link", { name: HELP.help_email });
  await expect(email).toHaveAttribute("href", `mailto:${HELP.help_email}`);
  const phone = listed.getByTestId("help-phone").getByRole("link", { name: HELP.help_phone });
  await expect(phone).toHaveAttribute("href", "tel:+15550100");
  const url = listed.getByTestId("help-url").getByRole("link", { name: HELP.help_url });
  await expect(url).toHaveAttribute("href", HELP.help_url);
  // It opens in a new tab, and gives the page it opens nothing of this one's.
  await expect(url).toHaveAttribute("target", "_blank");
  await expect(url).toHaveAttribute("rel", "noopener noreferrer");
}
