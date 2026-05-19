import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.PLAYWRIGHT_PORT ?? 3100);

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
  },
  webServer: {
    command: `NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=true npm run dev -- --hostname 127.0.0.1 --port ${port}`,
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  projects: [
    {
      name: "chrome-desktop",
      use: { ...devices["Desktop Chrome"], channel: process.env.PLAYWRIGHT_CHANNEL ?? "chrome" },
    },
    {
      name: "chrome-mobile",
      use: { ...devices["Pixel 5"], channel: process.env.PLAYWRIGHT_CHANNEL ?? "chrome" },
    },
  ],
});
