import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");

describe("index.html", () => {
  it("holds the exact base tag the server rewrites", () => {
    expect(html.split('<base href="/" />').length).toBe(2);
    expect(html.indexOf('<base href="/" />')).toBeLessThan(html.indexOf("<link"));
  });

  it("has nothing inline that the content security policy would block", () => {
    expect(html).not.toMatch(/<style/i);
    expect(html).not.toMatch(/\sstyle=/i);
    expect(html).not.toMatch(/<script(?![^>]*\ssrc=)/i);
    expect(html).not.toMatch(/\son[a-z]+=/i);
    expect(html).not.toMatch(/(data|blob|https?):/i);
  });
});
