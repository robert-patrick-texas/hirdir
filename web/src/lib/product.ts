// 0.9.2: the name a site gives the product, and whom to ask (P-168, P-169).
//
// The page the server serves carries both in <meta name="hirdir-site">, written before
// anybody has signed in: the name always, and whom to ask only where an Admin shows it on
// the sign-in page. Under the development server the page has no such tag, and the name
// is hirdir. Once signed in, `GET /about` answers the name again, and the Settings page
// tells an Admin's own page of a change at once. Everything on the page that names the
// product reads it from here.

import { useSyncExternalStore } from "react";

/** The name of the product unless an Admin gives another, and of the software always. */
export const DEFAULT_NAME = "hirdir";

/** Whom to ask: the team that runs this installation. Each that is blank is null. */
export interface Help {
  organization: string | null;
  email: string | null;
  phone: string | null;
  url: string | null;
}

export interface Site {
  /** The name the site gives the product. */
  productName: string;
  /** Whom to ask, on the sign-in page: null unless an Admin shows it there and one is set. */
  signInHelp: Help | null;
}

const HELP_KEYS = ["organization", "email", "phone", "url"] as const;

/** Text with something in it, without the spaces at either end, or null. */
function filled(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  return text === "" ? null : text;
}

/** The product name as it is given, or hirdir for anything else. */
export function nameOf(value: unknown): string {
  return filled(value) ?? DEFAULT_NAME;
}

/** Whom to ask, from what was read: null where it is not an object or none of them is set. */
export function helpOf(value: unknown): Help | null {
  if (typeof value !== "object" || value === null) return null;
  const given = value as Record<string, unknown>;
  const help: Help = {
    organization: filled(given.organization),
    email: filled(given.email),
    phone: filled(given.phone),
    url: filled(given.url),
  };
  return HELP_KEYS.some((key) => help[key] !== null) ? help : null;
}

/**
 * What the page that was served says of the site: the content of its `hirdir-site` tag,
 * a JSON object. Anything missing or malformed is the name hirdir and nobody to ask.
 */
export function parseSite(content: string | null | undefined): Site {
  let value: unknown = null;
  try {
    value = content ? JSON.parse(content) : null;
  } catch {
    value = null;
  }
  const given =
    typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
  return { productName: nameOf(given.product_name), signInHelp: helpOf(given.help) };
}

/** What the page that is open was served with. */
function servedSite(): Site {
  if (typeof document === "undefined") return parseSite(null);
  return parseSite(document.querySelector('meta[name="hirdir-site"]')?.getAttribute("content"));
}

/** What `GET /about` says of the site: the name in force. */
export function siteOfAbout(about: { product_name?: unknown }): Partial<Site> {
  return { productName: nameOf(about.product_name) };
}

/**
 * What the settings say of the site, as the Settings page reads them: the name, and whom
 * the sign-in page lists, which is nobody unless `help_on_sign_in` is true. A setting
 * that is not in the list leaves what it decides as it was.
 */
export function siteOfSettings(
  settings: ReadonlyArray<{ key: string; value: unknown }>,
): Partial<Site> {
  const value = new Map(settings.map((setting) => [setting.key, setting.value]));
  const site: Partial<Site> = {};
  if (value.has("product_name")) site.productName = nameOf(value.get("product_name"));
  if (value.has("help_on_sign_in")) {
    const help = helpOf({
      organization: value.get("help_organization"),
      email: value.get("help_email"),
      phone: value.get("help_phone"),
      url: value.get("help_url"),
    });
    site.signInHelp = value.get("help_on_sign_in") === true ? help : null;
  }
  return site;
}

function sameHelp(one: Help | null, other: Help | null): boolean {
  if (one === null || other === null) return one === other;
  return HELP_KEYS.every((key) => one[key] === other[key]);
}

type Listener = () => void;

/** The site as the page knows it now, which a component reads and follows. */
export class SiteStore {
  private site: Site;
  private readonly listeners = new Set<Listener>();

  constructor(site: Site) {
    this.site = site;
  }

  /** The same object until something changes, as useSyncExternalStore needs. */
  get = (): Site => this.site;

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  /** Take what was read. Where nothing differs, nothing changes and nobody is told. */
  update = (changed: Partial<Site>): void => {
    const next = { ...this.site, ...changed };
    if (
      next.productName === this.site.productName &&
      sameHelp(next.signInHelp, this.site.signInHelp)
    ) {
      return;
    }
    this.site = next;
    for (const listener of this.listeners) listener();
  };
}

/** The site of the page that is open. */
export const site = new SiteStore(servedSite());

/** The site as the page knows it, followed as it changes. */
export function useSite(): Site {
  return useSyncExternalStore(site.subscribe, site.get);
}

/** The title of the browser's tab: the page and the product, `Items · Example Inventory`. */
export function titleOf(page: string, productName: string): string {
  return page ? `${page} · ${productName}` : productName;
}

/**
 * The product name as the first part of a file's name, by the server's rule: a letter
 * loses its accents first (`Réseau` is `Reseau`), then each run of anything but ASCII
 * letters, digits, `.`, `_` and `-` is one `-`, a `-` or a `.` at either end is taken
 * off, and hirdir stands where nothing is left.
 */
export function fileStem(productName: string): string {
  const plain = productName.normalize("NFKD").replace(/\p{M}/gu, "");
  const stem = plain.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^[-.]+|[-.]+$/g, "");
  return stem || DEFAULT_NAME;
}

/** The name of a file the page makes, after the product: `Example-Inventory-scoreboard-sites.csv`. */
export function namedFile(productName: string, rest: string): string {
  return `${fileStem(productName)}-${rest}`;
}

/**
 * Where a link to write to an address leads: the address as it is given, which the server
 * takes only without anything that would add to the link, as `?`, `&` or `%` (P-169).
 */
export function mailtoHref(email: string): string {
  return `mailto:${email}`;
}

/**
 * Where a link to call a number leads, or null where there is nothing to dial: the `+`
 * before its first digit and its ASCII digits, up to the first letter, where an extension
 * begins (`+1 555 0100 ext. 12` dials `+15550100`).
 */
export function telHref(phone: string): string | null {
  const [number = ""] = phone.split(/\p{L}/u);
  const digits = number.replace(/\D/g, "");
  if (digits === "") return null;
  const plus = /^[^\d]*\+/.test(number) ? "+" : "";
  return `tel:${plus}${digits}`;
}
