// 0.9.8, a field that must be filled says so at a glance (P-260): the word "required"
// beside its label stands in the page's amber on its ground, where it was small and
// grey, and the field has a mark down its left edge while it is still empty, which
// goes when it is filled. The words of the label are as they were.
//
// The file keeps the rules of support.ts: an Admin of its own, and it makes nothing:
// the form is opened, measured and left.

import { expect } from "@playwright/test";
import { expectClean, mark, signIn, test, watch } from "./support";

const suffix = mark("required-mark");

test("a required field is marked in colour, and its edge until it is filled", async ({
  page,
  account,
  context,
}) => {
  const seen = await watch(context);
  await signIn(page, account);
  await page.goto("./systems");
  await expect(page.getByRole("heading", { level: 1, name: "External systems" })).toBeVisible();
  await page.getByRole("button", { name: "New system" }).click();

  const name = page.getByLabel("Name (required)");
  await expect(name).toBeVisible();
  const word = page.locator("label", { hasText: "Name" }).locator(".required").first();
  const colours = await word.evaluate((element) => {
    const style = getComputedStyle(element);
    const root = getComputedStyle(document.documentElement);
    return {
      colour: style.color,
      ground: style.backgroundColor,
      weight: Number(style.fontWeight),
      warn: root.getPropertyValue("--warn").trim(),
      muted: root.getPropertyValue("--muted").trim(),
    };
  });
  // The colour of what needs a person, not the grey of a note; on a ground; and bold.
  const probe = await page.evaluate((value) => {
    const span = document.createElement("span");
    span.style.color = value;
    document.body.append(span);
    const seenAs = getComputedStyle(span).color;
    span.remove();
    return seenAs;
  }, colours.warn);
  expect(colours.colour).toBe(probe);
  expect(colours.ground).not.toBe("rgba(0, 0, 0, 0)");
  expect(colours.weight).toBeGreaterThanOrEqual(600);

  // Empty, the field has its mark; filled, it has none. A field that need not be filled
  // never has one.
  const edge = () => name.evaluate((element) => getComputedStyle(element).boxShadow);
  expect(await edge()).toContain("inset");
  await name.fill(`NetWatch ${suffix}`);
  expect(await edge()).toBe("none");
  await name.fill("");
  expect(await edge()).toContain("inset");
  const notes = page.getByLabel("Notes");
  if ((await notes.count()) > 0) {
    expect(await notes.first().evaluate((element) => getComputedStyle(element).boxShadow)).toBe(
      "none",
    );
  }
  await expectClean(page, seen);
});
