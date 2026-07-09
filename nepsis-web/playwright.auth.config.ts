import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.PLAYWRIGHT_AUTH_PORT ?? 3101);

export default defineConfig({
  testDir: "./e2e-auth",
  testIgnore: /hosted-operator-otp\.spec\.ts/,
  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
  },
  webServer: {
    command:
      `NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=false ` +
      `NEPSIS_AUTH_SECRET=playwright-preview-auth-secret ` +
      `NEPSIS_AUTH_ALLOWED_EMAILS=operator@example.com,operator+logout@example.com,operator+session-cookie@example.com,operator+revoked@example.com,operator+invalid-code@example.com,operator+expired-code@example.com ` +
      `NEPSIS_AUTH_SESSION_REVOKE_BEFORE=2001-01-01T00:00:00.000Z ` +
      `NEPSIS_AUTH_ALLOW_CODE_PREVIEW=true ` +
      `RESEND_API_KEY= NEPSIS_AUTH_FROM_EMAIL= ` +
      `npm run dev -- --hostname 127.0.0.1 --port ${port}`,
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  projects: [
    {
      name: "chrome-desktop",
      use: { ...devices["Desktop Chrome"], channel: process.env.PLAYWRIGHT_CHANNEL ?? "chrome" },
    },
  ],
});
