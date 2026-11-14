import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

// Where the app under test is served: at the root of the development server by default,
// or under a prefix behind nginx, as in https://localhost:8443/hirdir/.
const given = process.env.E2E_BASE_URL || "http://127.0.0.1:8715/";
const baseURL = given.endsWith("/") ? given : `${given}/`;

/**
 * How many spec files run at once. E2E_WORKERS sets the number outright. Left unset, it
 * is what scripts/test_load.py says of the host as it is at this moment, as for every
 * other run of tests: the cores that are not busy, and no more than the free memory
 * allows. So a run beside other work, as in the package test with its three passes at
 * once, starts fewer. One at a time where the script cannot be asked.
 */
function workers(): number {
  const wanted = (process.env.E2E_WORKERS ?? "").trim();
  if (/^[1-9]\d*$/.test(wanted)) return Number(wanted);
  // A worker reads this file too, and has no use for the number.
  if (process.env.TEST_WORKER_INDEX !== undefined) return 1;
  try {
    const script = fileURLToPath(new URL("../scripts/test_load.py", import.meta.url));
    const said = execFileSync("python3", [script], {
      encoding: "utf8",
      // What the script says of the host, on its standard error, is shown.
      stdio: ["ignore", "pipe", "inherit"],
    }).trim();
    return /^[1-9]\d*$/.test(said) ? Number(said) : 1;
  } catch {
    return 1;
  }
}

export default defineConfig({
  testDir: "e2e",
  // The spec files run side by side, each in a worker of its own and with accounts and
  // names of its own, as e2e/support.ts describes. The tests of one file run in order.
  workers: workers(),
  fullyParallel: false,
  retries: 0,
  forbidOnly: true,
  reporter: [["list"]],
  outputDir: "test-results",
  use: {
    baseURL,
    // The test container's nginx site has a throwaway certificate.
    ignoreHTTPSErrors: true,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    // Asked for by name: npm run e2e -- --project=firefox
    ...(process.env.E2E_FIREFOX
      ? [{ name: "firefox", use: { ...devices["Desktop Firefox"] } }]
      : []),
  ],
});
