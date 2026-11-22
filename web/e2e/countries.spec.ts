// The browser scenarios of 0.9.18's lists of countries and states (P-318, P-321):
//
//   Admin › Choices lists the countries, the United States first and not removed nor
//   given another code, and the states of a country chosen; an Admin adds a country and
//   a state, each code kept in capitals, and the server's refusals are shown in its
//   words; both lists are exported as CSV and as JSON, as Geography exports its tables.
//   Every address form offers the countries by name and sends the code, shows a blank
//   country as the United States and sends it only beside another field of the same
//   address, offers the states of the country chosen, or a box of text where it has
//   none, and follows the country as it is changed. A state typed before its country had
//   states listed is not in the list: it is listed among the addresses not in the lists,
//   with a link to its place, whose form shows it as typed, marked so, until one is
//   chosen. A country an address holds is not removed; once none does, it is removed with
//   its states. A View-only person and an Inventory person read the lists and change
//   nothing of them.
//
// The file keeps the rules of support.ts. It signs in as an Admin of its own, and accounts
// of its own for the other roles; its mark is in every name it gives a record. Rule 5: it
// changes the list of countries, which every address form of every file reads, by a
// country of its own alone: one of the codes ISO 3166-1 keeps for private use, which no
// inventory starts with and no other file reads, with a state of its own, both removed
// at the end. The United States is opened and closed, and never saved. The addresses are
// fictional and the codes of the places of the list are public facts.

import { readFile } from "node:fs/promises";
import { type APIRequestContext, expect, type Locator, type Page } from "@playwright/test";
import { answer, openImport } from "./answers";
import { places } from "./geographySteps";
import { session } from "./referenceSteps";
import { region } from "./structure";
import { type Account, createAccount, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const id = mark("countries");
const land = `Example Land ${id}`;
const northern = `Northern ${id}`;
// The state of an address there typed before the country had any states listed.
const typed = `Northern Province ${id}`;
const americas = `Region ${id}`;
const path = (...names: string[]) => names.join(" > ");
const depot = path(americas, `Depot ${id}`);
const works = path(americas, `Works ${id}`);
// What the file's places hold no items of: the tree is filtered to nothing of others.
const { geography, newPlace, pages } = places(`hostname:prefix:${id}-`);

// The codes ISO 3166-1 keeps for private use: none is the code of a country.
const PRIVATE = [
  "AA",
  ...Array.from({ length: 14 }, (_, at) => `Q${String.fromCharCode(77 + at)}`),
  ...Array.from({ length: 26 }, (_, at) => `X${String.fromCharCode(65 + at)}`),
  "ZZ",
];

/** A code of the private range that the list does not hold, taken from a random place. */
async function freeCode(request: APIRequestContext, account: Account): Promise<string> {
  const headers = await session(request, account);
  const listed = await request.get("./api/v1/countries", { headers });
  expect(listed.status()).toBe(200);
  const held = new Set(((await listed.json()) as Array<{ code: string }>).map((one) => one.code));
  const start = Math.floor(Math.random() * PRIVATE.length);
  for (let at = 0; at < PRIVATE.length; at += 1) {
    const code = PRIVATE[(start + at) % PRIVATE.length] ?? "";
    if (!held.has(code)) return code;
  }
  throw new Error("every code of the private range is in the list");
}

// The code of the file's country, once the first scenario has chosen it.
let code = "";

/** Admin › Choices on one of its lists, once the server has answered what it shows. */
async function openList(page: Page, label: "Countries" | "States") {
  const read = answer(page, "GET", "/countries");
  await page.goto("./admin/choices");
  await expect(page.getByRole("heading", { level: 1, name: "Choices" })).toBeVisible();
  await page.getByLabel("List", { exact: true }).selectOption({ label });
  await expect(page).toHaveURL(new RegExp(`list=${label.toLowerCase()}`));
  await read;
  await expect(page.getByTestId("countries-intro")).toBeVisible();
}

function countryRow(page: Page, one: string): Locator {
  return page.getByTestId("countries").locator(`tr[data-country="${one}"]`);
}

function stateRow(page: Page, one: string): Locator {
  return page.getByTestId("states").locator(`tr[data-state="${one}"]`);
}

/** The states of one country, by its name in the Country of the list of states. */
async function openStates(page: Page, name: string, of: string) {
  // The states of every country are read once, as the list opens; a country chosen shows
  // its own from them.
  const read = answer(page, "GET", "/states");
  await openList(page, "States");
  await read;
  await page.getByLabel("Country", { exact: true }).selectOption({ label: name });
  await expect(page).toHaveURL(new RegExp(`country=${of}`));
  await expect(page.getByTestId("states")).toHaveAttribute("data-country", of);
}

/** The value a select shows chosen, by its text. */
function chosen(select: Locator): Locator {
  return select.locator("option:checked");
}

test("the countries are listed with the United States first, and an Admin adds one, its code kept in capitals", async ({
  page,
  request,
  account,
}, testInfo) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  code = await freeCode(request, account);
  await signIn(page, account);
  await openList(page, "Countries");

  // The United States first, however it is named, then the rest by name.
  const rows = page.getByTestId("countries").locator("tbody tr");
  await expect(rows.first()).toHaveAttribute("data-country", "US");
  await expect(countryRow(page, "US")).toContainText("United States");
  await expect(countryRow(page, "MX")).toContainText("Mexico");
  await expect(
    countryRow(page, "MX").getByRole("link", { name: /^The states of Mexico/ }),
  ).toBeVisible();
  // The United States is not removed, and its code is shown in its form, not offered.
  await expect(countryRow(page, "US").getByRole("button", { name: /^Remove/ })).toHaveCount(0);
  await expect(countryRow(page, "US").getByTestId("us-stays")).toHaveText(
    "Always first, and not removed",
  );
  await countryRow(page, "US").getByRole("button", { name: "Edit United States" }).click();
  const usForm = page.getByTestId("country-form");
  await expect(usForm.getByTestId("shown-code")).toContainText("US, which the United States keeps");
  await expect(usForm.getByLabel("Name (required)")).toHaveValue("United States");
  await usForm.getByRole("button", { name: "Close" }).click();
  await expect(page.getByTestId("country-form")).toHaveCount(0);

  // A country of the file's own, its code given in lower case.
  await page.getByRole("button", { name: "New country" }).click();
  const form = region(page, "New country");
  await form.getByLabel("Code (required)").fill(code.toLowerCase());
  await form.getByLabel("Name (required)").fill(land);
  const made = answer(page, "POST", "/countries");
  await form.getByRole("button", { name: "Add country" }).click();
  expect((await made).status()).toBe(201);
  await expect(page.getByText(`${land} was added, as ${code}.`)).toBeVisible();
  await expect(countryRow(page, code)).toContainText(land);
  await expect(
    countryRow(page, code).getByRole("link", { name: `The states of ${land}: none` }),
  ).toBeVisible();

  // Its code again is refused in the server's words, with the country that has it.
  await page.getByRole("button", { name: "New country" }).click();
  const again = region(page, "New country");
  await again.getByLabel("Code (required)").fill(code);
  await again.getByLabel("Name (required)").fill(`Another ${land}`);
  const refused = answer(page, "POST", "/countries");
  await again.getByRole("button", { name: "Add country" }).click();
  expect((await refused).status()).toBe(409);
  await expect(again.getByLabel("Code (required)")).toHaveAttribute("aria-invalid", "true");
  await expect(again).toContainText("another country has it");
  await expect(again).toContainText(`The country that has it: ${land}`);
  await again.getByRole("button", { name: "Cancel" }).click();

  // Both lists are exported, as Geography exports its tables.
  const line = page.getByTestId("countries-export");
  const download = page.waitForEvent("download");
  await line.getByRole("button", { name: "Export Countries as CSV" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/^hirdir-countries-\d{8}T\d{6}[-+]\d{4}\.csv$/);
  const saved = testInfo.outputPath(file.suggestedFilename());
  await file.saveAs(saved);
  const text = await readFile(saved, "utf8");
  expect(text.split("\n")[0]).toBe("hid,code,name");
  expect(text).toContain(`,${code},${land}`);
  await expect(line.getByRole("button", { name: "Export States as JSON" })).toBeVisible();
  await expect(line.getByRole("link", { name: "Import page" })).toBeVisible();
  await expectClean(page, seen, ["409 POST"]);
});

test("an address in a country with no states takes its state as text, and a state added there leaves it not in the list, chosen from its place", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await geography(page);
  await newPlace(page, "New region", "region", americas);

  // A site with a street address in the file's country, whose state is typed.
  await page.getByRole("button", { name: "New site in it", exact: true }).click();
  const form = region(page, "New site");
  await form.getByLabel("Name (required)").fill(depot.split(" > ").at(-1) ?? "");
  await form.getByLabel("Address line 1", { exact: true }).fill("1 Example Way");
  await form.getByLabel("City", { exact: true }).fill("Exampleton");
  // The country is a list by name, the United States shown chosen while none is.
  const country = form.getByLabel("Country", { exact: true });
  await expect(chosen(country)).toHaveText("United States");
  await expect(form.getByLabel("State or province", { exact: true })).toHaveJSProperty(
    "tagName",
    "SELECT",
  );
  await country.selectOption({ label: land });
  // Where the country has no states listed, the state is a box of text.
  const state = form.getByLabel("State or province", { exact: true });
  await expect(state).toHaveJSProperty("tagName", "INPUT");
  await state.fill(typed);
  const sent = page.waitForRequest(
    (request) => request.method() === "POST" && request.url().endsWith("/api/v1/sites"),
  );
  await form.getByRole("button", { name: "Create site" }).click();
  const body = (await sent).postDataJSON() as Record<string, unknown>;
  expect(body).toMatchObject({ country: code, state: typed, city: "Exampleton" });
  // The shipping address was left blank: its country, shown as the United States, is not
  // sent, and the site inherits what is above it.
  expect(body).not.toHaveProperty("ship_country");
  await expect(page.getByTestId("place-path")).toHaveText(depot);
  pages.set(depot, `.${new URL(page.url()).pathname.replace(/^.*(?=\/geography\/)/, "")}`);
  const facts = page.getByTestId("place-facts");
  await expect(facts).toContainText(`1 Example Way, Exampleton, ${typed}, ${land}`);
  const hid = (await page.getByTestId("place").getAttribute("data-hid")) ?? "";

  // A state is added to the country: the one typed is none of its states now.
  await openStates(page, land, code);
  await expect(page.getByTestId("no-states")).toContainText(`${land} has no states listed`);
  await page.getByRole("button", { name: `New state of ${land}` }).click();
  const newState = region(page, `New state of ${land}`);
  await newState.getByLabel("Code (required)").fill("np");
  await newState.getByLabel("Name (required)").fill(northern);
  const added = answer(page, "POST", "/states");
  const relisted = answer(page, "GET", "/places/unlisted-addresses");
  await newState.getByRole("button", { name: "Add state" }).click();
  expect((await added).status()).toBe(201);
  await expect(page.getByText(`${northern} was added to ${land}, as NP.`)).toBeVisible();
  await expect(stateRow(page, "NP")).toContainText(northern);
  await relisted;

  // Listed among the addresses not in the lists, with a link to its place.
  const unlisted = page
    .getByTestId("unlisted-addresses")
    .locator(`tr[data-hid="${hid}"][data-field="state"]`);
  await expect(unlisted).toContainText("Street address");
  await expect(unlisted).toContainText("State or province");
  await expect(unlisted.getByTestId("unlisted-value")).toHaveText(typed);

  // The Import page leads to them, as a file that holds such a value is refused at its
  // field where it is loaded into another inventory: the link brings the window to them,
  // with the keyboard on their heading, once the page has come.
  await openImport(page);
  const lead = page.getByTestId("unlisted-lead");
  await expect(lead).toContainText("loaded into another inventory, it is refused at that field");
  const arrived = answer(page, "GET", "/places/unlisted-addresses");
  await lead.getByRole("link", { name: "Addresses not in the lists" }).click();
  await expect(page).toHaveURL(/list=countries#unlisted-addresses$/);
  await arrived;
  await expect(
    page.getByRole("heading", { level: 2, name: "Addresses not in the lists" }),
  ).toBeFocused();
  await expect(unlisted).toBeInViewport();
  await unlisted.getByRole("link", { name: depot }).click();
  await expect(page.getByTestId("place-path")).toHaveText(depot);

  // Its form shows it as typed, marked so, until one is chosen.
  const details = region(page, "Details");
  const held = details.getByLabel("State or province", { exact: true });
  await expect(chosen(held)).toHaveText(`${typed} (not in the list)`);
  await expect(details).toContainText(
    `${typed} is not in the list of the states of ${land}: choose the one it is.`,
  );
  await held.selectOption({ label: northern });
  const patched = page.waitForRequest(
    (request) => request.method() === "PATCH" && request.url().includes(`/api/v1/sites/${hid}`),
  );
  await details.getByRole("button", { name: "Save" }).click();
  const change = (await patched).postDataJSON() as Record<string, unknown>;
  expect(change).toMatchObject({ state: "NP" });
  expect(change).not.toHaveProperty("country");
  await expect(page.getByText("The site was saved.")).toBeVisible();
  await expect(facts).toContainText(`1 Example Way, Exampleton, ${northern}, ${land}`);

  // It is no longer among the addresses not in the lists, once the server has said what is.
  const listed = answer(page, "GET", "/places/unlisted-addresses");
  await openList(page, "Countries");
  await listed;
  const section = page.getByTestId("unlisted-addresses");
  await expect(section.getByTestId("unlisted-none").or(section.locator("table"))).toBeVisible();
  await expect(section.locator(`tr[data-hid="${hid}"]`)).toHaveCount(0);
  await expectClean(page, seen);
});

test("a blank country is the United States, sent beside an address and not alone, and the state follows the country", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await geography(page, americas);

  // A site with a name alone: no country of either address is sent.
  const made = page.waitForRequest(
    (request) => request.method() === "POST" && request.url().endsWith("/api/v1/sites"),
  );
  await newPlace(page, "New site in it", "site", works);
  const body = (await made).postDataJSON() as Record<string, unknown>;
  expect(body).not.toHaveProperty("country");
  expect(body).not.toHaveProperty("ship_country");
  await expect(page.getByTestId("ship-address")).toHaveAttribute("data-standing", "none");

  // A city and a state chosen from the United States' list, which is offered while the
  // country is blank: the country is sent beside them.
  const details = region(page, "Details");
  const country = details.getByLabel("Country", { exact: true });
  await expect(country).toHaveValue("US");
  await expect(chosen(country)).toHaveText("United States");
  await expect(chosen(details.getByLabel("Shipping country"))).toHaveText("United States");
  await details.getByLabel("City", { exact: true }).fill("Springfield");
  const state = details.getByLabel("State or province", { exact: true });
  await expect(state.locator("option", { hasText: "Puerto Rico" })).toHaveCount(1);
  await state.selectOption({ label: "Texas" });
  const patched = page.waitForRequest(
    (request) => request.method() === "PATCH" && request.url().includes("/api/v1/sites/"),
  );
  await details.getByRole("button", { name: "Save" }).click();
  const change = (await patched).postDataJSON() as Record<string, unknown>;
  expect(change).toMatchObject({ city: "Springfield", state: "TX", country: "US" });
  expect(change).not.toHaveProperty("ship_country");
  await expect(page.getByText("The site was saved.")).toBeVisible();
  await expect(page.getByTestId("place-facts")).toContainText("Springfield, Texas, United States");
  // The site still inherits its shipping address: none is in force.
  await expect(page.getByTestId("ship-address")).toHaveAttribute("data-standing", "none");

  // The state follows the country: a state of the United States is none of Canada's,
  // and is cleared; one of Canada's is offered by its name.
  const again = region(page, "Details");
  await again.getByLabel("Country", { exact: true }).selectOption({ label: "Canada" });
  const follows = again.getByLabel("State or province", { exact: true });
  await expect(follows).toHaveValue("");
  await expect(follows.locator("option", { hasText: "Ontario" })).toHaveCount(1);
  await expect(follows.locator("option", { hasText: "Texas" })).toHaveCount(0);
  await again.getByLabel("Country", { exact: true }).selectOption({ label: "United States" });
  await again.getByRole("button", { name: "Undo changes" }).click();
  await expect(chosen(again.getByLabel("State or province", { exact: true }))).toHaveText("Texas");
  await expectClean(page, seen);
});

test("a country an address holds is not removed; once none does, it is removed with its state", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // Held by the depot's address, the country is not removed: the server says by what.
  await openList(page, "Countries");
  const row = countryRow(page, code);
  await expect(row.getByRole("link", { name: `The states of ${land}: 1 state` })).toBeVisible();
  await row.getByRole("button", { name: `Remove ${land}` }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Its one state is removed with it, in the same change.");
  const refused = answer(page, "DELETE", /\/api\/v1\/countries\//);
  await dialog.getByRole("button", { name: "Remove country" }).click();
  expect((await refused).status()).toBe(409);
  const alert = page.locator('.alert-error[data-status="409"]');
  await expect(alert).toContainText(`${land} is not removed: an address holds it`);
  await expect(alert).toContainText("give each another first");
  await expect(countryRow(page, code)).toHaveCount(1);

  // The depot is given the United States: its state follows, and Texas is chosen.
  await geography(page, depot);
  const details = region(page, "Details");
  await details.getByLabel("Country", { exact: true }).selectOption({ label: "United States" });
  const state = details.getByLabel("State or province", { exact: true });
  await expect(state).toHaveValue("");
  await state.selectOption({ label: "Texas" });
  const patched = page.waitForRequest(
    (request) => request.method() === "PATCH" && request.url().includes("/api/v1/sites/"),
  );
  await details.getByRole("button", { name: "Save" }).click();
  expect((await patched).postDataJSON()).toMatchObject({ country: "US", state: "TX" });
  await expect(page.getByText("The site was saved.")).toBeVisible();
  await expect(page.getByTestId("place-facts")).toContainText(
    "1 Example Way, Exampleton, Texas, United States",
  );

  // Now held by no address, it is removed with its state, in one change.
  await openList(page, "Countries");
  await countryRow(page, code)
    .getByRole("button", { name: `Remove ${land}` })
    .click();
  const removed = answer(page, "DELETE", /\/api\/v1\/countries\//);
  await page.getByRole("dialog").getByRole("button", { name: "Remove country" }).click();
  expect((await removed).status()).toBe(204);
  await expect(page.getByText(`${land} was removed, with its 1 state.`)).toBeVisible();
  await expect(countryRow(page, code)).toHaveCount(0);
  await expectClean(page, seen, ["409 DELETE"]);
});

test("a View-only person and an Inventory person read the lists and change nothing of them", async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  for (const role of ["viewer", "inventory"] as const) {
    const person = await createAccount(request, `e2e-${id}-${role}`, role);
    await signIn(page, person);
    await openList(page, "Countries");
    await expect(page.getByTestId("countries").locator("tbody tr").first()).toHaveAttribute(
      "data-country",
      "US",
    );
    await expect(page.getByRole("button", { name: "New country" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^Edit / })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^Remove/ })).toHaveCount(0);
    await expect(page.getByTestId("countries-export")).toContainText(
      "An Admin loads a file of either on the Import page.",
    );
    await openStates(page, "Mexico", "MX");
    await expect(stateRow(page, "NLE")).toContainText("Nuevo León");
    await expect(page.getByRole("button", { name: /^New state/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^Edit / })).toHaveCount(0);
    // The lists of choices are the Inventory role's to change, as before.
    const values = answer(page, "GET", "/choices");
    await page.getByLabel("List", { exact: true }).selectOption({ label: "Location kind" });
    await values;
    await expect(page.getByRole("rowheader").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "New value" })).toHaveCount(
      role === "inventory" ? 1 : 0,
    );
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Sign in to hirdir" })).toBeVisible();
  }
  await expectClean(page, seen);
});
