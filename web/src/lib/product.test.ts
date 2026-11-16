import { describe, expect, it, vi } from "vitest";
import {
  DEFAULT_NAME,
  fileStem,
  helpOf,
  mailtoHref,
  namedFile,
  nameOf,
  parseSite,
  SiteStore,
  site,
  siteOfAbout,
  siteOfSettings,
  telHref,
  titleOf,
} from "./product";

const NAME = "Example Inventory";
const HELP = {
  organization: "Network Tools, Example Corp",
  email: "tools@example.net",
  phone: "+1 555 0100",
  url: "https://help.example.net/network-tools",
};

describe("fileStem", () => {
  it("makes the product name the first part of a file's name, as the server does", () => {
    expect(fileStem("hirdir")).toBe("hirdir");
    expect(fileStem("Example Inventory")).toBe("Example-Inventory");
    expect(fileStem("Ben & Ada's: Net/2")).toBe("Ben-Ada-s-Net-2");
    expect(fileStem("--.assets.--")).toBe("assets");
    expect(fileStem("/// ...")).toBe("hirdir");
  });

  it("takes the accents off a letter first", () => {
    expect(fileStem("Réseau")).toBe("Reseau");
    expect(fileStem("Ünïcode")).toBe("Unicode");
    expect(fileStem("ÄÖÜ")).toBe("AOU");
    // A letter that is not of the Latin alphabet is no part of a file's name.
    expect(fileStem("Сеть")).toBe("hirdir");
  });

  it("keeps dots, underscores and hyphens within the name", () => {
    expect(fileStem("net_assets-2.0")).toBe("net_assets-2.0");
    expect(fileStem("Assets 🛰 Example")).toBe("Assets-Example");
  });
});

describe("namedFile", () => {
  it("names a file the page makes after the product", () => {
    expect(namedFile(NAME, "scoreboard-sites.csv")).toBe("Example-Inventory-scoreboard-sites.csv");
    expect(namedFile("Réseau", "scoreboard-operators.csv")).toBe("Reseau-scoreboard-operators.csv");
    expect(namedFile("Сеть", "items.csv")).toBe("hirdir-items.csv");
  });
});

describe("titleOf", () => {
  it("names the page and the product, or the product alone", () => {
    expect(titleOf("Items", NAME)).toBe("Items · Example Inventory");
    expect(titleOf("", NAME)).toBe("Example Inventory");
    expect(titleOf("Sign in", DEFAULT_NAME)).toBe("Sign in · hirdir");
  });
});

describe("nameOf and helpOf", () => {
  it("takes a name that is given, and hirdir for anything else", () => {
    expect(nameOf(NAME)).toBe(NAME);
    expect(nameOf(`  ${NAME}  `)).toBe(NAME);
    expect(nameOf("")).toBe("hirdir");
    expect(nameOf(null)).toBe("hirdir");
    expect(nameOf(7)).toBe("hirdir");
  });

  it("takes whom to ask where one of them is set, each blank one null", () => {
    expect(helpOf(HELP)).toEqual(HELP);
    expect(helpOf({ organization: null, email: "tools@example.net", phone: "", url: 3 })).toEqual({
      organization: null,
      email: "tools@example.net",
      phone: null,
      url: null,
    });
    expect(helpOf({ organization: null, email: null, phone: null, url: null })).toBeNull();
    expect(helpOf(null)).toBeNull();
    expect(helpOf("tools@example.net")).toBeNull();
  });
});

describe("parseSite", () => {
  it("reads what the served page carries", () => {
    expect(parseSite('{"product_name":"Example Inventory","help":null}')).toEqual({
      productName: NAME,
      signInHelp: null,
    });
    expect(parseSite(JSON.stringify({ product_name: "Ben & Ada's", help: HELP }))).toEqual({
      productName: "Ben & Ada's",
      signInHelp: HELP,
    });
  });

  it("is hirdir and nobody to ask without the tag, or with anything malformed", () => {
    const plain = { productName: "hirdir", signInHelp: null };
    expect(parseSite(null)).toEqual(plain);
    expect(parseSite(undefined)).toEqual(plain);
    expect(parseSite("")).toEqual(plain);
    expect(parseSite("{not json")).toEqual(plain);
    expect(parseSite("[1, 2]")).toEqual(plain);
    expect(parseSite('{"product_name": 7, "help": "x"}')).toEqual(plain);
  });

  it("is what the page under the development server has, which carries no tag", () => {
    expect(site.get()).toEqual({ productName: "hirdir", signInHelp: null });
  });
});

describe("siteOfAbout and siteOfSettings", () => {
  it("takes the name from About", () => {
    expect(siteOfAbout({ product_name: NAME })).toEqual({ productName: NAME });
  });

  const settings = [
    { key: "product_name", value: NAME },
    { key: "help_organization", value: HELP.organization },
    { key: "help_email", value: HELP.email },
    { key: "help_phone", value: HELP.phone },
    { key: "help_url", value: HELP.url },
    { key: "help_on_sign_in", value: true },
    { key: "time_zone", value: "UTC" },
  ];

  it("lists whom to ask for the sign-in page only where help_on_sign_in is true", () => {
    expect(siteOfSettings(settings)).toEqual({ productName: NAME, signInHelp: HELP });
    const off = settings.map((one) =>
      one.key === "help_on_sign_in" ? { ...one, value: false } : one,
    );
    expect(siteOfSettings(off)).toEqual({ productName: NAME, signInHelp: null });
  });

  it("lists nobody where none of them is set, even with help_on_sign_in true", () => {
    const none = settings.map((one) =>
      one.key.startsWith("help_") && one.key !== "help_on_sign_in" ? { ...one, value: null } : one,
    );
    expect(siteOfSettings(none).signInHelp).toBeNull();
  });

  it("leaves alone what the list does not hold", () => {
    expect(siteOfSettings([{ key: "time_zone", value: "UTC" }])).toEqual({});
    expect(siteOfSettings([{ key: "product_name", value: null }])).toEqual({
      productName: "hirdir",
    });
  });
});

describe("SiteStore", () => {
  it("tells those that follow it of a change, and of nothing that is the same", () => {
    const store = new SiteStore({ productName: "hirdir", signInHelp: null });
    const told = vi.fn();
    const stop = store.subscribe(told);
    const first = store.get();
    store.update({ productName: "hirdir" });
    expect(told).not.toHaveBeenCalled();
    expect(store.get()).toBe(first);

    store.update({ productName: NAME });
    expect(told).toHaveBeenCalledTimes(1);
    expect(store.get()).toEqual({ productName: NAME, signInHelp: null });

    store.update({ signInHelp: { ...HELP } });
    store.update({ signInHelp: { ...HELP } });
    expect(told).toHaveBeenCalledTimes(2);
    expect(store.get().signInHelp).toEqual(HELP);

    stop();
    store.update({ productName: "Other Example" });
    expect(told).toHaveBeenCalledTimes(2);
  });
});

describe("mailtoHref and telHref", () => {
  it("writes to the address as it is given", () => {
    expect(mailtoHref("tools@example.net")).toBe("mailto:tools@example.net");
    expect(mailtoHref("net+tools@example.net")).toBe("mailto:net+tools@example.net");
  });

  it("dials the + and the digits, up to the first letter", () => {
    expect(telHref("+1 555 0100")).toBe("tel:+15550100");
    expect(telHref("+1 555 0100 ext. 12")).toBe("tel:+15550100");
    expect(telHref("+1 (555) 0100 x12")).toBe("tel:+15550100");
    expect(telHref("(+1) 555-0100")).toBe("tel:+15550100");
    expect(telHref("555.0100")).toBe("tel:5550100");
    expect(telHref("+1 555 0100, 12")).toBe("tel:+15550100");
    expect(telHref("+1 555 0100 #12")).toBe("tel:+15550100");
  });

  it("drops a + that is not before the first digit, and every other mark", () => {
    expect(telHref("555+0100")).toBe("tel:5550100");
    expect(telHref("*555 0100#")).toBe("tel:5550100");
  });

  it("links nothing where there is nothing to dial before a letter", () => {
    expect(telHref("ext. 12")).toBeNull();
    expect(telHref("+")).toBeNull();
  });
});
