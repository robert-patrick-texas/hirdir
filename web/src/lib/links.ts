// Links of a record: an address on the web and the text to show for it, in their order.
//
// A region, a site, a location and a catalog entry have their own; an item shows those
// of its model, and a place has none from the places above it. The list is one field of
// the record, changed whole. What an address may be is the server's rule: a page sends
// the list as it was typed and shows the server's reason when it is refused.

import type { Schemas } from "../api/client";

export type Link = Schemas["Link"];
export type LinkIn = Schemas["LinkIn"];

/** The most links a record has. */
export const MAX_LINKS = 20;

/** What a link is shown as: its text, or its address where it has none. */
export function linkLabel(link: Pick<Link, "url" | "text">): string {
  return link.text.trim() === "" ? link.url : link.text;
}

/**
 * Whether an address is one a page leads to: on the web, and nothing else. The server
 * takes no other, so this is only a guard: anything else is shown as text, not followed.
 */
export function isWebAddress(url: string): boolean {
  return /^https?:\/\/[^\s<>]+$/i.test(url);
}

/** One link as the editor holds it, with a key of its own while it is moved about. */
export interface LinkDraft {
  key: string;
  url: string;
  text: string;
}

let drafted = 0;

/** A key for a link of the editor, the same for it however it is moved. */
export function draftKey(): string {
  drafted += 1;
  return `link-${drafted}`;
}

/** The links of a record, as the editor starts with them. */
export function draftsOf(links: readonly Link[], key: () => string = draftKey): LinkDraft[] {
  return links.map((link) => ({ key: key(), url: link.url, text: link.text }));
}

/** The list with the link at `place` moved one up (-1) or down (1). Off either end, as it was. */
export function moved<T>(list: readonly T[], place: number, by: -1 | 1): T[] {
  const to = place + by;
  if (place < 0 || place >= list.length || to < 0 || to >= list.length) return [...list];
  const order = [...list];
  const [taken] = order.splice(place, 1);
  if (taken !== undefined) order.splice(to, 0, taken);
  return order;
}

/**
 * The links as they are sent: in their order, each address and text as typed with the
 * space around it trimmed. A link left wholly blank is no link, and is left out.
 */
export function linksBody(drafts: readonly Pick<LinkDraft, "url" | "text">[]): LinkIn[] {
  return drafts
    .map((draft) => ({ url: draft.url.trim(), text: draft.text.trim() }))
    .filter((link) => link.url !== "" || link.text !== "");
}

/** Whether the editor holds the links the record has, in the same order. */
export function sameLinks(links: readonly Link[], body: readonly LinkIn[]): boolean {
  return (
    links.length === body.length &&
    links.every((link, place) => {
      const other = body[place];
      return other !== undefined && link.url === other.url && link.text === (other.text ?? "");
    })
  );
}

/**
 * The number of the link a refusal names, as the server names it: "link 2: an address
 * that begins with https://". Null when it names none.
 */
export function refusedLink(message: string | undefined): number | null {
  const match = /^link (\d+):/.exec(message ?? "");
  return match ? Number(match[1]) : null;
}
