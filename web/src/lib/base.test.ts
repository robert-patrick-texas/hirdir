import { describe, expect, it } from "vitest";
import { apiUrl, basePath, routerBasename, slashed } from "./base";

describe("basePath", () => {
  it("is / when the app is served at the root", () => {
    expect(basePath("http://127.0.0.1:8715/")).toBe("/");
  });

  it("is the prefix the server wrote into the base tag", () => {
    expect(basePath("https://inventory.example/hirdir/")).toBe("/hirdir/");
    expect(basePath("https://inventory.example/tools/hirdir/")).toBe("/tools/hirdir/");
  });

  it("is the directory when the base names a file", () => {
    expect(basePath("https://inventory.example/hirdir/index.html")).toBe("/hirdir/");
  });

  it("ignores the query and the fragment", () => {
    expect(basePath("https://inventory.example/hirdir/?q=a/b#c/d")).toBe("/hirdir/");
  });
});

describe("routerBasename", () => {
  it("is the base path, trailing slash and all", () => {
    expect(routerBasename("http://127.0.0.1:8715/")).toBe("/");
    expect(routerBasename("https://inventory.example/hirdir/")).toBe("/hirdir/");
    expect(routerBasename("https://inventory.example/tools/hirdir/")).toBe("/tools/hirdir/");
  });
});

describe("slashed", () => {
  it("adds the final slash to the prefix when it is missing", () => {
    expect(slashed("https://inventory.example/hirdir/", "/hirdir")).toBe("/hirdir/");
  });

  it("leaves every other address alone", () => {
    expect(slashed("https://inventory.example/hirdir/", "/hirdir/")).toBeNull();
    expect(slashed("https://inventory.example/hirdir/", "/hirdir/admin/users")).toBeNull();
    expect(slashed("http://127.0.0.1:8715/", "/")).toBeNull();
    expect(slashed("http://127.0.0.1:8715/", "/about")).toBeNull();
  });
});

describe("apiUrl", () => {
  it("puts the API under the base, at the root and under a prefix", () => {
    expect(apiUrl("http://127.0.0.1:8715/", "/api/v1/about")).toBe(
      "http://127.0.0.1:8715/api/v1/about",
    );
    expect(apiUrl("https://inventory.example/hirdir/", "/api/v1/about")).toBe(
      "https://inventory.example/hirdir/api/v1/about",
    );
  });

  it("does not depend on which page of the app is open", () => {
    // The base tag, not the address bar, is what document.baseURI reports.
    expect(apiUrl("https://inventory.example/hirdir/", "/api/v1/users")).toBe(
      "https://inventory.example/hirdir/api/v1/users",
    );
  });

  it("fills path parameters and escapes them", () => {
    expect(
      apiUrl("https://inventory.example/hirdir/", "/api/v1/user-groups/{hid}/members/{user_hid}", {
        hid: "g 1",
        user_hid: "u/2",
      }),
    ).toBe("https://inventory.example/hirdir/api/v1/user-groups/g%201/members/u%2F2");
  });

  it("refuses a route with a parameter left unfilled", () => {
    expect(() => apiUrl("http://127.0.0.1:8715/", "/api/v1/users/{hid}")).toThrow(/hid/);
    expect(() => apiUrl("http://127.0.0.1:8715/", "/api/v1/users/{hid}", { hid: "" })).toThrow();
  });

  it("adds the query, leaving out blank values", () => {
    expect(
      apiUrl(
        "http://127.0.0.1:8715/",
        "/api/v1/audit-events",
        {},
        { action: "sign_in", record_type: "", limit: 50, offset: 0, actor_hid: undefined },
      ),
    ).toBe("http://127.0.0.1:8715/api/v1/audit-events?action=sign_in&limit=50&offset=0");
  });
});
