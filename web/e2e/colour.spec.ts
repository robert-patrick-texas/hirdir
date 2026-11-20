// 0.9.13, a colour chosen from a grid of 64, by a slider of 32, or typed (P-285).
//
//   A tag is made on Admin › Tags with its colour pressed in the grid, moved on the
//   slider by the keyboard and typed, in and out of the grid: the three stay one value,
//   and the chip says the value in black or in white, whichever reads better on it. A
//   value that is no colour is said at the box before anything is sent. The grid is
//   moved through by the arrow keys and chosen from by Enter and Space. The tag is saved,
//   read back in the list and in its form, and changed there. With the colours held
//   back, the box takes a colour by itself, and Create makes the tag. The picker fits a
//   form 360 pixels wide, in light and in dark. An operator's colour is pressed, saved
//   and read back on its page and in its form; with the colours held back, Create waits
//   for the next free colour and makes the operator with it.
//
// The file keeps the rules of support.ts. It signs in as an Admin of its own, and its
// mark is in every name it gives a record: the tags, which it removes when it ends, and
// the operators. In the lists, which every file may add to, it looks at its own rows
// alone; the next free colour depends on every operator, and is not named.

import { expect, type Locator, type Page } from "@playwright/test";
import { region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const id = mark("colour");
const tagLabel = `Colour ${id}`;
const heldLabel = `Held ${id}`;

/** The picker of a form, by the name of its group. */
function picker(form: Locator, name = "Colour"): Locator {
  return form.getByRole("group", { name, exact: true });
}

function box(colour: Locator): Locator {
  return colour.getByRole("textbox", { name: "Colour", exact: true });
}

function slider(colour: Locator): Locator {
  return colour.getByRole("slider", { name: "Colour, Slider of 32", exact: true });
}

function swatch(colour: Locator, name: string): Locator {
  return colour.getByRole("button", { name, exact: true });
}

/** The swatches that are pressed: the one chosen, or none. */
function pressed(colour: Locator): Locator {
  return colour.locator('.colour-swatch[aria-pressed="true"]');
}

function chip(colour: Locator): Locator {
  return colour.locator(".colour-chip");
}

/** The colour the chip's text is drawn in, as the browser reckons it. */
async function chipText(colour: Locator): Promise<string> {
  return chip(colour).evaluate((element) => getComputedStyle(element).color);
}

const BLACK = "rgb(0, 0, 0)";
const WHITE = "rgb(255, 255, 255)";

/** The row of a tag of this file's in the list, by its label. */
function tagRow(page: Page, label: string): Locator {
  return page.locator(`tr[data-tag="${label}"]`);
}

test("a tag's colour is pressed, slid and typed, as one value, and saved", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./admin/tags");
  await expect(page.getByRole("heading", { level: 1, name: "Tags" })).toBeVisible();
  await page.getByRole("button", { name: "New tag", exact: true }).click();
  const form = region(page, "New tag");
  await form.getByLabel("Label (required)").fill(tagLabel);
  const colour = picker(form);
  await expect(box(colour)).toHaveValue("");
  await expect(chip(colour)).toHaveText("No colour");
  // The sample beside the chip is the tag as it will show.
  await expect(colour.locator(".colour-sample")).toHaveText(tagLabel);
  await expect(colour.locator(".colour-swatch")).toHaveCount(64);
  await expect(pressed(colour)).toHaveCount(0);
  await expect(slider(colour)).toHaveAttribute("aria-valuetext", "No step: no colour is chosen");

  // A swatch is one press: the box and the slider follow.
  await swatch(colour, "orange, shade 3 of 8, #fb9d59").click();
  await expect(box(colour)).toHaveValue("#fb9d59");
  await expect(pressed(colour)).toHaveAttribute("data-colour", "#fb9d59");
  await expect(pressed(colour)).toHaveText("✓");
  await expect(slider(colour)).toHaveAttribute(
    "aria-valuetext",
    "Step 5 of 32: orange, shade 3 of 8, #fb9d59",
  );
  await expect(chip(colour)).toHaveText("#fb9d59");
  expect(await chipText(colour)).toBe(BLACK);

  // The slider by the keyboard: a step at a time, and to its end. The grid follows.
  await slider(colour).focus();
  await page.keyboard.press("ArrowRight");
  await expect(box(colour)).toHaveValue("#ec7c0e");
  await expect(pressed(colour)).toHaveAttribute("data-colour", "#ec7c0e");
  await page.keyboard.press("End");
  await expect(box(colour)).toHaveValue("#b2307a");
  await expect(pressed(colour)).toHaveAttribute("data-colour", "#b2307a");
  // A dark colour takes white text.
  expect(await chipText(colour)).toBe(WHITE);

  // Typed, out of the grid: kept as typed, no swatch is chosen, and the slider says it
  // holds no step. The owner's example, somewhat orange, takes black text.
  await box(colour).fill("#eeaa00");
  await expect(pressed(colour)).toHaveCount(0);
  await expect(slider(colour)).toHaveAttribute(
    "aria-valuetext",
    "No step: #eeaa00 is not one of the 32",
  );
  await expect(colour.locator(".colour-slider")).toHaveAttribute("data-none", "true");
  await expect(chip(colour)).toHaveText("#eeaa00");
  expect(await chipText(colour)).toBe(BLACK);
  // Typed, of the grid, in capitals: its swatch is chosen, and the box keeps the capitals.
  await box(colour).fill("#00480E");
  await expect(pressed(colour)).toHaveAttribute("data-colour", "#00480e");
  await expect(box(colour)).toHaveValue("#00480E");
  expect(await chipText(colour)).toBe(WHITE);
  // The darkest green is no step of the slider, which rests at the green nearest it:
  // the first move goes on from there.
  await slider(colour).focus();
  await page.keyboard.press("ArrowLeft");
  await expect(box(colour)).toHaveValue("#11a22f");
  await expect(colour.locator(".colour-slider")).toHaveAttribute("data-none", "false");

  // What is no colour is said at the box when it is left, and Create sends nothing.
  await box(colour).fill("#eeaa0");
  await form.getByLabel("Label (required)").focus();
  await expect(colour.locator(".field-error")).toHaveText(/^In the form #1f6feb/);
  await expect(box(colour)).toHaveAttribute("aria-invalid", "true");
  await form.getByRole("button", { name: "Create tag", exact: true }).click();
  await expect(box(colour)).toBeFocused();
  await expect(form).toBeVisible();
  await expect(box(colour)).toHaveValue("#eeaa0");

  // The grid is one stop of Tab, at the swatch chosen; the arrow keys move, and Enter
  // and Space choose.
  await swatch(colour, "orange, shade 3 of 8, #fb9d59").click();
  await expect(swatch(colour, "orange, shade 3 of 8, #fb9d59")).toBeFocused();
  await expect(colour.locator('.colour-swatch[tabindex="0"]')).toHaveCount(1);
  await page.keyboard.press("ArrowDown");
  await expect(swatch(colour, "orange, shade 4 of 8, #ec7c0e")).toBeFocused();
  await expect(box(colour)).toHaveValue("#fb9d59");
  await page.keyboard.press("Enter");
  await expect(box(colour)).toHaveValue("#ec7c0e");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Space");
  await expect(box(colour)).toHaveValue("#bb9c00");
  await page.keyboard.press("Tab");
  await expect(colour.locator(".colour-swatch:focus")).toHaveCount(0);
  await page.keyboard.press("Shift+Tab");
  await expect(swatch(colour, "yellow, shade 4 of 8, #bb9c00")).toBeFocused();

  // Saved, the list shows it on its chip, and its form holds it.
  await form.getByRole("button", { name: "Create tag", exact: true }).click();
  await expect(page.getByText(`The tag ${tagLabel} was created.`)).toBeVisible();
  const row = tagRow(page, tagLabel);
  await expect(row.locator(".colour-chip")).toHaveText("#bb9c00");
  await row.getByRole("button", { name: `Edit the tag ${tagLabel}`, exact: true }).click();
  const edit = page.getByTestId("tag-form");
  const again = picker(edit);
  await expect(box(again)).toHaveValue("#bb9c00");
  await expect(pressed(again)).toHaveAttribute("data-colour", "#bb9c00");
  await swatch(again, "blue, shade 6 of 8, #0169cd").click();
  await edit.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText(`The tag ${tagLabel} was saved.`)).toBeVisible();
  await expect(row.locator(".colour-chip")).toHaveText("#0169cd");
  expect(await row.locator(".colour-chip").evaluate((chip) => getComputedStyle(chip).color)).toBe(
    WHITE,
  );

  await expectClean(page, seen);
});

test("with the colours held back the box takes a colour, and the picker fits 360 pixels, light and dark", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.setViewportSize({ width: 360, height: 800 });
  await page.emulateMedia({ colorScheme: "dark" });
  // The colours come late: the form is filled and sent before they have come.
  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/v1/colours", async (route) => {
    await held;
    await route.continue();
  });
  await page.goto("./admin/tags");
  await page.getByRole("button", { name: "New tag", exact: true }).click();
  const form = region(page, "New tag");
  const colour = picker(form);
  await expect(colour.getByText("Loading the colours to choose from…")).toBeVisible();
  await form.getByLabel("Label (required)").fill(heldLabel);
  await box(colour).fill("#eeaa00");
  expect(await chipText(colour)).toBe(BLACK);
  await form.getByRole("button", { name: "Create tag", exact: true }).click();
  await expect(page.getByText(`The tag ${heldLabel} was created.`)).toBeVisible();
  await expect(tagRow(page, heldLabel).locator(".colour-chip")).toHaveText("#eeaa00");
  release();

  // The picker, in dark, in a window 360 pixels wide: nothing is wider than its form.
  await page.getByRole("button", { name: "New tag", exact: true }).click();
  const next = picker(region(page, "New tag"));
  await expect(next.locator(".colour-swatch")).toHaveCount(64);
  const fits = await next.evaluate((fieldset) => {
    const form = fieldset.closest("form");
    const right = form ? form.getBoundingClientRect().right : window.innerWidth;
    const widest = Math.max(
      ...[...fieldset.querySelectorAll("*")].map((part) => part.getBoundingClientRect().right),
    );
    return {
      widest,
      right,
      scrolls: document.documentElement.scrollWidth > window.innerWidth,
      own: fieldset.scrollWidth > fieldset.clientWidth,
    };
  });
  expect(fits.widest).toBeLessThanOrEqual(fits.right);
  expect(fits.own).toBe(false);
  expect(fits.scrolls).toBe(false);
  // The dark theme's text, on the dark ground.
  expect(await next.locator("legend").evaluate((legend) => getComputedStyle(legend).color)).toBe(
    "rgb(228, 232, 236)",
  );
  await swatch(next, "red, shade 1 of 8, #fee0dc").click();
  expect(await chipText(next)).toBe(BLACK);
  await region(page, "New tag").getByRole("button", { name: "Cancel", exact: true }).click();

  // The tags of this file are taken away: they are on no record.
  for (const label of [tagLabel, heldLabel]) {
    await tagRow(page, label).getByRole("button", { name: "Remove", exact: true }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Remove tag" }).click();
    await expect(page.getByText(`The tag ${label} was removed.`)).toBeVisible();
  }

  await expectClean(page, seen);
});

test("an operator's colour is pressed, saved and read back, and a Create pressed before the colours have come waits for the next free one", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./operators");
  await page.getByRole("button", { name: "New operator", exact: true }).click();
  const form = region(page, "New operator");
  await form.getByLabel("Label (required)").fill(`C1-${id}`);
  const colour = picker(form);
  // The sample is the label as the lists show an operator: a dot, and the label.
  await expect(colour.locator(".colour-sample.operator-mark")).toHaveText(`C1-${id}`);
  await swatch(colour, "teal, shade 6 of 8, #027c7c").click();
  await form.getByRole("button", { name: "Create operator", exact: true }).click();
  await expect(page.getByTestId("operator-heading")).toContainText(`C1-${id}`);
  await expect(page.getByTestId("operator-colour")).toHaveText("#027c7c");
  expect(
    await page
      .getByTestId("operator-colour")
      .evaluate((element) => getComputedStyle(element).color),
  ).toBe(WHITE);
  const details = picker(region(page, "Details"));
  await expect(box(details)).toHaveValue("#027c7c");
  await expect(pressed(details)).toHaveAttribute("data-colour", "#027c7c");

  // The colours come late: Create, pressed before, waits for the next free colour and
  // makes the operator with it.
  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/v1/colours", async (route) => {
    await held;
    await route.continue();
  });
  await page.goto("./operators");
  await page.getByRole("button", { name: "New operator", exact: true }).click();
  const late = region(page, "New operator");
  await late.getByLabel("Label (required)").fill(`C2-${id}`);
  await expect(box(picker(late))).toHaveValue("");
  await late.getByRole("button", { name: "Create operator", exact: true }).click();
  await expect(late.getByText("Waiting for what the form fills in")).toBeVisible();
  release();
  await expect(page.getByTestId("operator-heading")).toContainText(`C2-${id}`);
  await expect(page.getByTestId("operator-colour")).toHaveText(/^#[0-9a-f]{6}$/);

  await expectClean(page, seen);
});
