import { defineConfig } from "@playwright/test";

const apiUrl =
  process.env.CASEPILOT_E2E_API_URL ?? "http://localhost:8000";

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.CASEPILOT_E2E_BASE_URL ?? "http://localhost:3000",
    channel: "chrome",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video:
      process.env.CASEPILOT_E2E_VIDEO === "1"
        ? "on"
        : "retain-on-failure",
  },
  webServer: process.env.CASEPILOT_E2E_BASE_URL
    ? undefined
    : {
        command:
          `NEXT_PUBLIC_CASEPILOT_API_URL=${apiUrl} pnpm build && ` +
          `NEXT_PUBLIC_CASEPILOT_API_URL=${apiUrl} pnpm start --host localhost --port 3000`,
        url: "http://localhost:3000",
        reuseExistingServer: true,
        timeout: 120_000,
      },
});
