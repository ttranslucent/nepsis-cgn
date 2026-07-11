import { defineConfig, devices } from "@playwright/test";

const appPort = Number(process.env.PLAYWRIGHT_HOSTED_AUTH_PORT ?? 3103);
const supabasePort = Number(process.env.PLAYWRIGHT_SUPABASE_OTP_PORT ?? 3102);

export default defineConfig({
  testDir: "./e2e-auth",
  testMatch: /hosted-operator-otp\.spec\.ts/,
  timeout: 45_000,
  expect: {
    timeout: 7_500,
  },
  use: {
    baseURL: `http://127.0.0.1:${appPort}`,
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `node e2e-auth/fake-supabase-otp-server.mjs --port ${supabasePort}`,
      url: `http://127.0.0.1:${supabasePort}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
    {
      command:
        `NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=false ` +
        `NEPSIS_DEPLOYMENT_MODE=operator ` +
        `NEXT_PUBLIC_NEPSIS_OPERATOR_SITE=true ` +
        `NEPSIS_LIVE_OPERATOR_ENABLED=true ` +
        `NEPSIS_MODEL_ROUTES_ENABLED=false ` +
        `NEPSIS_ENGINE_ALLOW_ANON=false ` +
        `NEPSIS_AUTH_SECRET=playwright-hosted-auth-secret ` +
        `NEPSIS_AUTH_ALLOWED_EMAILS=operator+hosted@example.com ` +
        `NEPSIS_AUTH_ALLOW_CODE_PREVIEW=false ` +
        `NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:${supabasePort} ` +
        `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=playwright-supabase-publishable-key ` +
        `RESEND_API_KEY= NEPSIS_AUTH_FROM_EMAIL= ` +
        `npm run dev -- --hostname 127.0.0.1 --port ${appPort}`,
      url: `http://127.0.0.1:${appPort}`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
  projects: [
    {
      name: "chrome-desktop",
      use: { ...devices["Desktop Chrome"], channel: process.env.PLAYWRIGHT_CHANNEL ?? "chrome" },
    },
  ],
});
