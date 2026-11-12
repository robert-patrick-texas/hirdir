import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The server rewrites <base href="/" /> in index.html to the URL prefix it is served
// under, so every URL the build writes is relative and resolves against that tag.
export default defineConfig({
  base: "./",
  plugins: [react()],
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
