import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");

describe("index.html", () => {
  it("holds the exact base tag the server rewrites", () => {
    expect(html.split('<base href="/" />').length).toBe(2);
    expect(html.indexOf('<base href="/" />')).toBeLessThan(html.indexOf("<link"));
  });

  // 0.9.2: the server names the product as the site calls it in these, and writes what
  // the page reads when it starts before the end of the head (P-168, P-169).
  it("holds the exact title, note and end of the head the server rewrites", () => {
    expect(html.split("<title>hirdir</title>").length).toBe(2);
    expect(html.split("<noscript>hirdir needs JavaScript to run.</noscript>").length).toBe(2);
    expect(html.split("</head>").length).toBe(2);
    expect(html).not.toContain("hirdir-site");
  });

  it("has nothing inline that the content security policy would block", () => {
    expect(html).not.toMatch(/<style/i);
    expect(html).not.toMatch(/\sstyle=/i);
    expect(html).not.toMatch(/<script(?![^>]*\ssrc=)/i);
    expect(html).not.toMatch(/\son[a-z]+=/i);
    expect(html).not.toMatch(/(data|blob|https?):/i);
  });
});
