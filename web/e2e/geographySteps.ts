// What the scenarios of places do alike: the Geography page and its tree, a place made
// with the buttons of the page, a contact assigned to one, a location chosen by searching
// for it. The three files were one, geography.spec.ts, until they were to run side by
// side (rule 7 of support.ts): geography.spec.ts lays out the places and moves a site,
// geography-plans.spec.ts makes an owner outside the team and plans a new site, and
// geography-shipping.spec.ts types a shipping address once and rebuilds a room. Each
// lays out the places and loads the people it needs, under names of its own.

import { expect, type Locator, type Page } from "@playwright/test";
import { region } from "./structure";

/** A contact as a form offers it: its name, and its address beside it. */
export function offered(name: string, mail: string): string {
  return `${name} (${mail})`;
}

/** The row of one place in the tree, by its path. */
export function treeRow(page: Page, place: string): Locator {
  return page.getByTestId("geography-tree").locator(`tr[data-path="${place}"]`);
}

/** See what the tree counts at or beneath a place: its items, and the components among them. */
export async function expectCounts(row: Locator, items: number, components: number) {
  await expect(row.locator('[data-count="items"]')).toHaveText(String(items));
  await expect(row.locator('[data-count="components"]')).toHaveText(String(components));
}

/** Assign a contact to the place on show, in a role. */
export async function assign(page: Page, role: string, contact: string, name: string) {
  const form = region(page, "Assign a contact");
  await form.getByLabel("Role").selectOption({ label: role });
  await form.getByLabel("Contact", { exact: true }).selectOption({ label: contact });
  await form.getByRole("button", { name: "Assign contact" }).click();
  await expect(page.getByText(`${name} is now a ${role} contact of`)).toBeVisible();
}

/** The row of one role in what the place on show has in force. */
export function inForce(page: Page, role: string): Locator {
  return page.getByTestId("in-force-contacts").locator(`tr[data-role="${role}"]`);
}

/** Search for a location in a form's Location field, and choose it by its path. */
export async function chooseLocation(
  form: Locator,
  typed: string,
  place: string,
  label = "Location",
) {
  await form.getByLabel(label, { exact: true }).fill(typed);
  await form
    .getByRole("list", { name: "Locations that match" })
    .getByRole("button", { name: place, exact: true })
    .click();
}

/** The places a spec file has made, and the Geography page as that file reads it. */
export interface Places {
  /** The address of the page of each place, by its path. */
  pages: Map<string, string>;
  /** Remember the place on show, by its path. */
  remember(page: Page, place: string): void;
  /** The Geography page, counting the file's items only, with one place chosen or none. */
  geography(page: Page, place?: string): Promise<void>;
  /**
   * Make a place with one of the buttons of the page, and remember the address of its
   * page under its path.
   */
  newPlace(
    page: Page,
    button: string,
    what: "region" | "site" | "location",
    place: string,
    more?: { code?: string; kind?: string; status?: string },
  ): Promise<void>;
}

/** The places of one spec file, whose items `filter` keeps and no others. */
export function places(filter: string): Places {
  const pages = new Map<string, string>();
  const remember = (page: Page, place: string) => {
    pages.set(place, `.${new URL(page.url()).pathname.replace(/^.*(?=\/geography\/)/, "")}`);
  };
  return {
    pages,
    remember,
    async geography(page, place = "") {
      const address = place === "" ? "./geography" : pages.get(place);
      expect(address, `the page of ${place}`).toBeDefined();
      await page.goto(`${address}?${new URLSearchParams({ filter }).toString()}`);
      await expect(page.getByRole("heading", { level: 1, name: "Geography" })).toBeVisible();
      await expect(page.getByTestId("geography-tree")).toBeVisible();
      if (place !== "") await expect(page.getByTestId("place-path")).toHaveText(place);
    },
    async newPlace(page, button, what, place, more = {}) {
      await page.getByRole("button", { name: button, exact: true }).click();
      const form = region(page, `New ${what}`);
      await form.getByLabel("Name (required)").fill(place.split(" > ").at(-1) ?? "");
      if (more.code) await form.getByLabel("Code", { exact: true }).fill(more.code);
      if (more.kind) await form.getByLabel("Kind").selectOption({ label: more.kind });
      if (more.status) await form.getByLabel("Record status").selectOption({ label: more.status });
      await form.getByRole("button", { name: `Create ${what}` }).click();
      // The page goes to the new place, which shows the path the server worked out.
      await expect(page.getByTestId("place-path")).toHaveText(place);
      await expect(page.getByTestId("place")).toHaveAttribute("data-level", what);
      remember(page, place);
    },
  };
}
