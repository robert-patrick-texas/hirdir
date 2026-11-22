// The browser scenarios of release 0.9.17, P-316: an account may be an agent's. Kind on
// New user offers Person, Service account and Agent, and an agent asks for the person
// answerable; the list of users writes Agent in Kind and is narrowed to each kind; the
// page of an agent names its person, hands it to another, and shows its role as held
// and as its person holds it to; the page of a person lists their agents; a person's
// retirement says what becomes of each agent, named on the button; the refusals of
// Admin to an agent are shown in the server's words; and the Audit page narrows to the
// changes of agents, each written `agent for sam`, as an item's history writes it.
//
// They keep to the rules of support.ts: an account of the file's own, people, an agent
// and records of its own with the file's mark in their names, and the accounts put away
// when the file ends. The agent's token is used through the API alone.

import { type APIRequestContext, expect, type Page } from "@playwright/test";
import { type Headers, make, session } from "./referenceSteps";
import { goAhead, openUser, putAway, read } from "./retiredSteps";
import { region } from "./structure";
import { createAccount, expectClean, mark, signIn, test, watch } from "./support";

const suffix = mark("agents");
const madeAccounts: string[] = [];

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
});

test.afterAll(async ({ request, accounts }) => {
  await putAway(request, await session(request, await accounts.of("agents")), madeAccounts);
});

interface Agent {
  hid: string;
  username: string;
  role: string | null;
  role_in_force: string | null;
  role_capped_by: string | null;
  answerable: { hid: string; username: string } | null;
}

/** A person of the file's own, with a role of their own. */
async function person(request: APIRequestContext, key: string, role: string) {
  const name = `${key.charAt(0).toUpperCase()}${key.slice(1)} Example ${suffix}`;
  const made = await createAccount(request, `e2e-${suffix}-${key}`, role, { name });
  madeAccounts.push(made.hid);
  return { ...made, name };
}

/** Choose a person in a search field of people, by their name. */
async function choosePerson(page: Page, label: string, name: string) {
  const field = page.locator(".place-field").filter({ has: page.getByLabel(label) });
  await page.getByLabel(label).fill(name);
  await field
    .getByRole("list", { name: "People that match" })
    .getByRole("button", { name: new RegExp(`^${name}`) })
    .click();
}

/** Change the role of a person's own grant, as the file's Admin, through the API. */
async function regrant(
  request: APIRequestContext,
  headers: Headers,
  user: { hid: string },
  role: string,
) {
  const held = await read<{ grants: Array<{ hid: string; group: unknown }> }>(
    request,
    headers,
    `/users/${user.hid}`,
  );
  for (const grant of held.grants.filter((one) => one.group === null)) {
    const gone = await request.delete(`./api/v1/role-grants/${grant.hid}`, { headers });
    expect(gone.status(), `delete grant: ${await gone.text()}`).toBe(204);
  }
  await make(request, headers, "/role-grants", { user_hid: user.hid, role });
}

test("P-316: an agent is made on New user, answerable to a person, and listed as an Agent", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const sam = await person(request, "sam", "inventory");
  const seen = await watch(page.context());
  await signIn(page, account);

  await page.goto("./admin/users");
  await page.getByRole("button", { name: "New user" }).click();
  const form = region(page, "New user");
  const username = `e2e-${suffix}-reconcile`;
  await form.getByLabel("Username").fill(username);
  const kinds = form.getByRole("group", { name: "Kind" });
  await expect(kinds.getByRole("radio")).toHaveCount(3);
  await kinds.getByRole("radio", { name: "Agent" }).check();
  // An agent is no person: no contact, no operator, no access code; never Admin.
  await expect(form.getByRole("checkbox", { name: "Also a contact" })).toHaveCount(0);
  await expect(form.getByRole("checkbox", { name: "Also an operator" })).toHaveCount(0);
  await expect(form.getByLabel("Access code")).toHaveCount(0);
  await expect(form.getByLabel("Role").locator("option")).toHaveText([
    "No role",
    "View-only",
    "Inventory",
  ]);
  // The person answerable is asked for before anything is sent.
  await form.getByRole("button", { name: "Create user" }).click();
  await expect(form.locator('[data-field="answerable_hid"]')).toContainText(
    "Choose the person answerable for the agent.",
  );
  await choosePerson(page, "Person answerable", sam.name);
  await form.getByLabel("Role").selectOption({ label: "Inventory" });
  await form.getByRole("button", { name: "Create user" }).click();
  await expect(
    page.getByText(`The agent ${username}, answerable to ${sam.username}, was created.`),
  ).toBeVisible();
  const link = page.getByTestId("user-made").getByRole("link", { name: username });
  const agentHid = decodeURIComponent((await link.getAttribute("href"))?.split("/").at(-1) ?? "");
  madeAccounts.push(agentHid);
  const agent = await read<Agent>(request, headers, `/users/${agentHid}`);
  expect(agent.answerable?.hid).toBe(sam.hid);
  expect(agent.role).toBe("inventory");

  // The list writes Agent in Kind, and is narrowed to each kind, kept in the address.
  await page.goto(`./admin/users?q=${encodeURIComponent(suffix)}`);
  const rows = page.getByTestId("users").locator("tbody tr[data-user]");
  const row = (name: string) => rows.and(page.locator(`[data-user="${name}"]`));
  await expect(row(username).getByTestId("user-kind")).toHaveText("Agent");
  await expect(row(sam.username).getByTestId("user-kind")).toHaveText("Person");
  await page.getByLabel("Kind").selectOption({ label: "Agent" });
  await expect(page).toHaveURL(/[?&]kind=agent(&|$)/);
  await expect(rows).toHaveCount(1);
  await expect(row(username)).toBeVisible();
  await page.getByLabel("Kind").selectOption({ label: "Person" });
  await expect(row(sam.username)).toBeVisible();
  await expect(row(username)).toHaveCount(0);
  await expectClean(page, seen);
});

test("P-316: an agent's page names its person, holds it to their role, and hands it over; the person lists their agents", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const sam = await person(request, "sal", "inventory");
  const jan = await person(request, "jan", "inventory");
  const made = await make(request, headers, "/users", {
    username: `e2e-${suffix}-sync`,
    kind: "agent",
    answerable_hid: sam.hid,
    role: "inventory",
  });
  const answer = made as unknown as { user: { hid: string; username: string } };
  const agent = answer.user;
  madeAccounts.push(agent.hid);
  const seen = await watch(page.context());
  await signIn(page, account);

  await openUser(page, agent);
  const facts = page.getByTestId("user-facts");
  await expect(page.getByTestId("user-kind")).toHaveText("Agent");
  await expect(
    page.getByTestId("user-answerable").getByRole("link", { name: sam.name }),
  ).toHaveAttribute("href", new RegExp(`/admin/users/${sam.hid}$`));
  await expect(page.getByTestId("user-role")).toContainText("Inventory");
  await expect(page.getByTestId("user-role-capped")).toHaveCount(0);
  // No person's parts; its tokens, as a service account's.
  await expect(region(page, "Access code")).toHaveCount(0);
  await expect(region(page, "The person")).toHaveCount(0);
  const tokens = region(page, "Tokens");
  await tokens.getByLabel("Name (required)").fill(`${suffix}-run`);
  await tokens.getByRole("button", { name: "Create token" }).click();
  await expect(page.getByTestId("secret-box")).not.toContainText("refused");
  await page.getByTestId("secret-box").getByRole("button", { name: "Done" }).click();

  // The person's page lists the agent.
  await openUser(page, sam);
  await expect(
    page.getByTestId("user-agents").getByRole("link", { name: agent.username }),
  ).toBeVisible();

  // The person moved to View-only holds the agent to it, and the page says why.
  await regrant(request, headers, sam, "viewer");
  await openUser(page, agent);
  await expect(page.getByTestId("user-role")).toContainText("Inventory");
  await expect(page.getByTestId("user-role-capped")).toContainText(
    `held to View-only by ${sam.username}'s role`,
  );
  expect((await read<Agent>(request, headers, `/users/${agent.hid}`)).role_in_force).toBe("viewer");

  // Handed to another person, the button naming them.
  const hand = region(page, "Answerable to");
  await expect(hand.getByRole("button", { name: "Hand over" })).toBeDisabled();
  await choosePerson(page, "Hand to", jan.name);
  await hand.getByRole("button", { name: `Hand ${agent.username} to ${jan.name}` }).click();
  // The page read again names Jan, and still says what was done (review 2).
  await expect(
    page.getByTestId("user-answerable").getByRole("link", { name: jan.name }),
  ).toBeVisible();
  await expect(
    page.getByText(`${agent.username} is answerable to ${jan.name} from now on.`),
  ).toBeVisible();
  await expect(page.getByTestId("user-role-capped")).toHaveCount(0);
  await expect(facts).toContainText("Inventory");
  expect((await read<Agent>(request, headers, `/users/${agent.hid}`)).answerable?.hid).toBe(
    jan.hid,
  );

  // Admin is refused to an agent, in the server's words, at the role.
  await page.goto("./admin/roles");
  const grant = region(page, "Grant a role");
  await grant.getByLabel("Role").selectOption({ label: "Admin" });
  await grant.getByLabel("User", { exact: true }).selectOption({ value: agent.hid });
  await grant.getByRole("button", { name: "Grant role" }).click();
  await expect(grant.locator(".field-error")).toContainText("never Admin");
  await expectClean(page, seen, ["422 POST"]);
});

test("P-316: a person's retirement says what becomes of each agent, named on the button", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const ann = await person(request, "ann", "inventory");
  const ben = await person(request, "ben", "inventory");
  const agents = [];
  for (const key of ["one", "two"]) {
    const made = (await make(request, headers, "/users", {
      username: `e2e-${suffix}-${key}`,
      kind: "agent",
      answerable_hid: ann.hid,
      role: "viewer",
    })) as unknown as { user: { hid: string; username: string } };
    madeAccounts.push(made.user.hid);
    agents.push(made.user);
  }
  const [one, two] = agents as [
    { hid: string; username: string },
    { hid: string; username: string },
  ];
  const seen = await watch(page.context());
  await signIn(page, account);

  await openUser(page, ann);
  await region(page, "Retire").getByRole("button", { name: "Retire account" }).click();
  const ask = page.getByTestId("retire-person");
  const rowOf = (agent: { hid: string }) =>
    ask.locator(`[data-row="agent"][data-agent="${agent.hid}"]`);
  // Each agent, Retire ticked from the start, and named on the button.
  await expect(rowOf(one).getByRole("radio", { name: "Retire", exact: true })).toBeChecked();
  await expect(rowOf(two).getByRole("radio", { name: "Retire", exact: true })).toBeChecked();
  const go = goAhead(ask);
  await expect(go).toContainText(`agent ${one.username} and agent ${two.username}`);
  // One handed to Ben: to nobody yet, said at its row and nothing sent; then to Ben.
  await rowOf(two).getByRole("radio", { name: "Hand to another person" }).check();
  await expect(go).toContainText(`hand ${two.username} over`);
  await go.click();
  await expect(rowOf(two)).toContainText("Choose the person the agent is handed to");
  await choosePerson(page, `Person to hand ${two.username} to`, ben.name);
  await expect(go).toContainText(`agent ${one.username}`);
  await expect(go).toContainText(`hand ${two.username} to ${ben.name}`);
  await go.click();
  await expect(ask).toHaveCount(0);
  await expect(page.getByText(`${two.username} was handed to ${ben.name}`)).toBeVisible();
  expect(
    (await read<{ record_status: string }>(request, headers, `/users/${one.hid}`)).record_status,
  ).toBe("retired");
  const handed = await read<Agent & { record_status: string }>(
    request,
    headers,
    `/users/${two.hid}`,
  );
  expect(handed.record_status).toBe("active");
  expect(handed.answerable?.hid).toBe(ben.hid);
  await expectClean(page, seen);
});

test("P-316: the Audit page narrows to the changes of agents, each written for its person, as an item's history is", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const kit = await person(request, "kit", "inventory");
  const made = (await make(request, headers, "/users", {
    username: `e2e-${suffix}-tidy`,
    kind: "agent",
    answerable_hid: kit.hid,
    role: "inventory",
  })) as unknown as { user: { hid: string; username: string } };
  const agent = made.user;
  madeAccounts.push(agent.hid);
  const token = (await make(request, headers, `/users/${agent.hid}/service-tokens`, {
    name: `${suffix}-tidy`,
  })) as unknown as { secret: string };
  const vendor = await make(request, headers, "/vendors", { name: `${suffix} Vendor` });
  const model = await make(request, headers, "/catalog-entries", {
    vendor_hid: vendor.hid,
    pid: `AGT-${suffix}`,
  });
  const hostname = `agt-${suffix}`;
  const item = await make(request, headers, "/items", {
    catalog_entry_hid: model.hid,
    hostname,
  });
  // The agent changes the item, with its own token.
  const asAgent = { Authorization: `Bearer ${token.secret}` };
  const now = await read<{ row_version: number }>(request, headers, `/items/${item.hid}`);
  const changed = await request.patch(`./api/v1/items/${item.hid}`, {
    headers: asAgent,
    data: { row_version: now.row_version, comments: `Tidied by the agent ${suffix}.` },
  });
  expect(changed.status(), `the agent changes the item: ${await changed.text()}`).toBe(200);
  const seen = await watch(page.context());
  await signIn(page, account);

  // Who offers the agent marked with its person; Kind narrows to the changes of agents.
  await page.goto("./audit");
  await expect(
    page
      .getByLabel("Who")
      .locator("option", { hasText: `${agent.username} (agent, for ${kit.username})` }),
  ).toHaveCount(1);
  await page.getByLabel("Kind").selectOption({ label: "Agents" });
  await page.getByLabel("Record type").fill("item");
  await page.getByRole("button", { name: "Filter" }).click();
  await expect(page).toHaveURL(/[?&]actor_kind=agent(&|$)/);
  const row = page.locator("table.audit tbody tr").filter({ hasText: item.hid });
  await expect(row.first()).toBeVisible();
  const who = row.first().getByTestId("actor");
  await expect(who).toHaveText(`${agent.username} for ${kit.username}`);
  await expect(who.getByRole("link", { name: agent.username })).toHaveAttribute(
    "href",
    new RegExp(`/admin/users/${agent.hid}$`),
  );
  await expect(who.getByRole("link", { name: kit.username })).toHaveAttribute(
    "href",
    new RegExp(`/admin/users/${kit.hid}$`),
  );

  // The item's history writes it the same way.
  await page.goto(`./items/${encodeURIComponent(item.hid)}`);
  await expect(page.getByRole("heading", { level: 1, name: hostname })).toBeVisible();
  const history = region(page, "History");
  await expect(history.getByTestId("actor").filter({ hasText: agent.username })).toHaveText(
    `${agent.username} for ${kit.username}`,
  );
  await expectClean(page, seen);
});
