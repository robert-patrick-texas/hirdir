// Where the app is served. The server writes the URL prefix into the page's <base> tag,
// so `document.baseURI` is the one place the prefix is read from.

/** The directory the app is served from, with a trailing slash: `/` or `/hirdir/`. */
export function basePath(baseURI: string): string {
  const { pathname } = new URL(baseURI);
  return pathname.slice(0, pathname.lastIndexOf("/") + 1);
}

/**
 * The base path as the router's basename. It keeps its trailing slash, so the first
 * page under a prefix is `/hirdir/`, the address the proxy serves, and not `/hirdir`.
 */
export function routerBasename(baseURI: string): string {
  return basePath(baseURI);
}

/**
 * The address to move to when the app was opened at its prefix without the final slash
 * (`/hirdir` for `/hirdir/`), or null when the address is fine as it is.
 */
export function slashed(baseURI: string, pathname: string): string | null {
  const base = basePath(baseURI);
  return `${pathname}/` === base ? base : null;
}

/**
 * The full URL of an API route under the base.
 *
 * `route` is a path of the contract such as `/api/v1/users/{hid}`. Each `{name}` is
 * filled from `params`, and `query` is added, leaving out blank values.
 */
export function apiUrl(
  baseURI: string,
  route: string,
  params: Readonly<Record<string, string | number>> = {},
  query: Readonly<Record<string, string | number | boolean | null | undefined>> = {},
): string {
  const filled = route.replace(/^\/+/, "").replace(/\{([^}]+)\}/g, (_, name: string) => {
    const value = params[name];
    if (value === undefined || value === "") {
      throw new Error(`the route ${route} needs a value for ${name}`);
    }
    return encodeURIComponent(String(value));
  });
  const url = new URL(filled, new URL(basePath(baseURI), baseURI));
  for (const [name, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(name, String(value));
    }
  }
  return url.toString();
}
