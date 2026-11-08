import { defineConfig, devices } from "@playwright/test";

// e2e runs against an ALREADY RUNNING stack (docker compose via docker/ci-stack.sh, or `npm run dev` + backend).
// Required env: E2E_BASE_URL, E2E_REVIEWER_LOGIN, E2E_REVIEWER_PASSWORD, E2E_MINT_CMD (prints {"request_hash": ...}).
// Serial on purpose: every review test mutates the same hero record in the system of record.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
