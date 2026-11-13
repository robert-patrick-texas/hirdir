import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

const GRID_STYLES = `${sep}node_modules${sep}ag-grid-community${sep}styles${sep}`;
const UNPACKED = fileURLToPath(new URL("./node_modules/.cache/hirdir-grid/", import.meta.url));
const SUFFIXES: Readonly<Record<string, string>> = {
  "font/woff2": ".woff2",
  "image/svg+xml": ".svg",
};
// url("data:…"), url('data:…') and url(data:…): the media type, its parameters, the payload.
const DATA_URLS = [
  /url\(\s*"data:([^;,"]+)((?:;[^,"]*)?),([^"]*)"\s*\)/g,
  /url\(\s*'data:([^;,']+)((?:;[^,']*)?),([^']*)'\s*\)/g,
  /url\(\s*data:([^;,)]+)((?:;[^,)]*)?),([^)"']*)\)/g,
];

function unescaped(payload: string): string {
  try {
    return decodeURIComponent(payload);
  } catch {
    // Not percent-encoded throughout: it is then the text itself.
    return payload;
  }
}

/**
 * Ship what the grid's stylesheets embed as files of their own.
 *
 * AG Grid's stylesheets carry their icon font and a few pictures as `data:` URLs. The
 * content security policy allows nothing from `data:`, and it is not widened for the
 * grid: each embedded file is unpacked here, when the UI is built, and the stylesheet is
 * pointed at the file instead, which is then served from the same origin as everything
 * else. A build that still holds a `data:` URL in a stylesheet fails.
 */
function shipEmbeddedFiles(): Plugin {
  return {
    name: "hirdir:ship-embedded-files",
    enforce: "pre",
    transform(code, id) {
      const [file = ""] = id.split("?");
      if (!file.endsWith(".css") || !file.includes(GRID_STYLES) || !code.includes("data:")) {
        return null;
      }
      const unpack = (whole: string, type: string, parameters: string, payload: string) => {
        const suffix = SUFFIXES[type];
        if (suffix === undefined) {
          throw new Error(`${file} embeds a ${type}, which this build does not know how to ship`);
        }
        const content = parameters.includes(";base64")
          ? Buffer.from(payload, "base64")
          : Buffer.from(unescaped(payload), "utf8");
        if (content.length === 0) {
          throw new Error(`${file} embeds a file that cannot be read: ${whole.slice(0, 80)}`);
        }
        const name = `grid-${createHash("sha256").update(content).digest("hex").slice(0, 16)}`;
        mkdirSync(UNPACKED, { recursive: true });
        writeFileSync(join(UNPACKED, name + suffix), content);
        const path = relative(dirname(file), join(UNPACKED, name + suffix));
        return `url("${path.split(sep).join("/")}")`;
      };
      let out = code;
      for (const pattern of DATA_URLS) out = out.replace(pattern, unpack);
      return { code: out, map: null };
    },
    generateBundle(_, bundle) {
      for (const [name, chunk] of Object.entries(bundle)) {
        if (chunk.type !== "asset" || !name.endsWith(".css")) continue;
        if (/url\(\s*["']?data:/.test(String(chunk.source))) {
          this.error(`${name} holds a data: URL, which the content security policy forbids`);
        }
      }
    },
  };
}

// The server rewrites <base href="/" /> in index.html to the URL prefix it is served
// under, so every URL the build writes is relative and resolves against that tag.
export default defineConfig({
  base: "./",
  plugins: [shipEmbeddedFiles(), react()],
  build: {
    outDir: "../src/hirdir/static",
    emptyOutDir: true,
    // The content security policy allows nothing from data: URLs.
    assetsInlineLimit: 0,
    modulePreload: { polyfill: false },
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8715" },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "*.test.ts"],
  },
});
