// What the browser scenarios of reference files share (release 0.9.0, P-158 to P-163):
// records made through the API as the spec file's own Admin, files of a few bytes that
// are what their names say, and the section Files and links of a record's page.

import { readFile } from "node:fs/promises";
import { crc32, deflateSync } from "node:zlib";
import {
  type APIRequestContext,
  type Download,
  expect,
  type Locator,
  type Page,
} from "@playwright/test";
import type { Account } from "./support";

export type Headers = { Authorization: string };

/** Sign the spec file's own account in through the API, for making its records. */
export async function session(request: APIRequestContext, account: Account): Promise<Headers> {
  const answer = await request.post("./api/v1/auth/sign-in", {
    data: { username: account.username, access_code: account.accessCode },
  });
  expect(answer.status(), "the account of the file signs in through the API").toBe(200);
  const { token } = (await answer.json()) as { token: string };
  return { Authorization: `Bearer ${token}` };
}

/** Make a record through the API. */
export async function make(
  request: APIRequestContext,
  headers: Headers,
  path: string,
  data: unknown,
): Promise<{ hid: string; path?: string }> {
  const answer = await request.post(`./api/v1${path}`, { headers, data });
  expect(answer.status(), `post ${path}: ${await answer.text()}`).toBe(201);
  return (await answer.json()) as { hid: string; path?: string };
}

/** A file as Playwright hands it to a file input. */
export interface Payload {
  name: string;
  mimeType: string;
  buffer: Buffer;
}

function chunk(kind: string, data: Buffer): Buffer {
  const body = Buffer.concat([Buffer.from(kind, "latin1"), data]);
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const check = Buffer.alloc(4);
  check.writeUInt32BE(crc32(body));
  return Buffer.concat([length, body, check]);
}

/** A small picture of one colour, a real PNG of its own for each seed, that a browser shows. */
export function png(name: string, seed: number): Payload {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(8, 0);
  header.writeUInt32BE(8, 4);
  header.set([8, 2, 0, 0, 0], 8);
  const row = Buffer.concat([
    Buffer.from([0]),
    Buffer.from([seed % 256, 80, 160].flatMap((one) => Array(8).fill(one))),
  ]);
  const pixels = Buffer.concat(Array.from({ length: 8 }, () => row));
  const buffer = Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(pixels)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
  return { name, mimeType: "image/png", buffer };
}

/** A small PDF that says what it is, as a PDF begins and ends. */
export function pdf(name: string, text: string): Payload {
  return {
    name,
    mimeType: "application/pdf",
    buffer: Buffer.from(`%PDF-1.7\n% ${text}\n%%EOF\n`, "latin1"),
  };
}

/** A file of any name with the content given. */
export function file(
  name: string,
  content: string | Buffer,
  mimeType = "application/octet-stream",
): Payload {
  return {
    name,
    mimeType,
    buffer: typeof content === "string" ? Buffer.from(content, "latin1") : content,
  };
}

/** The section Files and links of the page on show. */
export function filesOf(page: Page): Locator {
  return page.getByRole("region", { name: "Files and links", exact: true });
}

/** A reference as a section or a table lists it, by its title. */
export function row(within: Locator, title: string): Locator {
  return within.locator(`tr[data-title="${title}"]`);
}

/** The group of references a section has from one record, by that record's path or name. */
export function from(section: Locator, label: string): Locator {
  return section.getByRole("region", { name: label, exact: true });
}

/** A file chosen to upload, by its name. */
export function chosen(section: Locator, name: string): Locator {
  return section.locator(`li[data-file="${name}"]`);
}

/** Open the page of a place by its HID, and wait for its path. */
export async function openPlace(page: Page, level: string, hid: string, path: string) {
  await page.goto(`./geography/${level}/${encodeURIComponent(hid)}`);
  await expect(page.getByTestId("place-path")).toHaveText(path);
  await expect(filesOf(page).getByRole("region", { name: "Its own", exact: true })).toBeVisible();
}

/** Download a reference from where it is listed, and check that it comes byte for byte. */
export async function downloaded(page: Page, within: Locator, title: string, expected: Payload) {
  const download: Promise<Download> = page.waitForEvent("download");
  await row(within, title)
    .getByRole("button", { name: `Download ${title}`, exact: true })
    .click();
  const saved = await download;
  expect(saved.suggestedFilename()).toBe(expected.name);
  const path = await saved.path();
  expect(Buffer.compare(await readFile(path), expected.buffer), "the bytes downloaded").toBe(0);
}

/** Choose files to upload in a section, and wait for each to be listed. */
export async function choose(section: Locator, files: Payload[]) {
  await section.getByLabel("Choose files").setInputFiles(files);
  for (const one of files) await expect(chosen(section, one.name)).toBeVisible();
}
