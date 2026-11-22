// What the browser scenarios of agents share (release 0.9.17, P-316): a person of the
// file's own with a role, an agent answerable to them, both made through the API as the
// file's own Admin, and a person chosen in a search field of people.

import { type APIRequestContext, expect, type Page } from "@playwright/test";
import { type Headers, make } from "./referenceSteps";
import { createAccount } from "./support";

export interface Made {
  hid: string;
  username: string;
  name: string;
}

/** A person with a role of their own, named with the file's mark; kept to put away. */
export async function makePerson(
  request: APIRequestContext,
  suffix: string,
  key: string,
  role: string,
  made: string[],
): Promise<Made> {
  const name = `${key.charAt(0).toUpperCase()}${key.slice(1)} Example ${suffix}`;
  const account = await createAccount(request, `e2e-${suffix}-${key}`, role, { name });
  made.push(account.hid);
  return { hid: account.hid, username: account.username, name };
}

/** An agent answerable to a person, with the role given, or none; kept to put away. */
export async function makeAgent(
  request: APIRequestContext,
  headers: Headers,
  suffix: string,
  key: string,
  person: { hid: string },
  role: string | null,
  made: string[],
): Promise<Made> {
  const answer = (await make(request, headers, "/users", {
    username: `e2e-${suffix}-${key}`,
    kind: "agent",
    answerable_hid: person.hid,
    ...(role ? { role } : {}),
  })) as unknown as { user: { hid: string; username: string } };
  made.push(answer.user.hid);
  return { hid: answer.user.hid, username: answer.user.username, name: answer.user.username };
}

/** Choose a person in a search field of people, by their name. */
export async function choosePerson(page: Page, label: string, name: string) {
  const box = page.getByLabel(label, { exact: true });
  const field = page.locator(".place-field").filter({ has: box });
  await box.fill(name);
  await field
    .getByRole("list", { name: "People that match" })
    .getByRole("button", { name: new RegExp(`^${name}`) })
    .click();
  await expect(field.getByRole("list", { name: "People that match" })).toHaveCount(0);
}
