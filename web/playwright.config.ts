import { defineConfig, devices } from "@playwright/test";

// Where the app under test is served: at the root of the development server by default,
// or under a prefix behind nginx, as in https://localhost:8443/hirdir/.
const given = process.env.E2E_BASE_URL || "http://127.0.0.1:8715/";
const baseURL = given.endsWith("/") ? given : `${given}/`;

export default defineConfig({
  testDir: "e2e",
  // The scenario signs in and changes accounts on one server: one worker, in order.
  workers: 1,
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
