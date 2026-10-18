import { defineConfig, devices } from "@playwright/test";
import { prepareEnvironment, workerBootstrap } from "./e2e/global-setup";

if (!process.argv.includes("--list")) prepareEnvironment();

export default defineConfig({
  testDir: "./e2e", testMatch: "**/*.spec.ts", fullyParallel: false, workers: 1,
  retries: 0, timeout: 180_000, expect: { timeout: 30_000 },
  globalSetup: "./e2e/global-setup.ts", reporter: "list",
  use: { baseURL: "http://127.0.0.1:3000", trace: "off", screenshot: "off", video: "off" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `uv run --project ../worker python -c '${workerBootstrap.replaceAll("'", "'\\''")}'`,
      wait: { stdout: /fixture worker ready/ }, timeout: 60_000,
      gracefulShutdown: { signal: "SIGTERM", timeout: 20_000 },
      env: {
        KIWOOM_WORKER_TRANSPORT: "fixture",
        KIWOOM_WORKER_FIXTURE_FILE: "../worker/tests/fixtures/e2e_market.json",
        KIWOOM_WORKER_POLL_INTERVAL_S: "0.2", KIWOOM_WORKER_HEARTBEAT_INTERVAL_S: "1",
      },
    },
    { command: "pnpm dev --hostname 127.0.0.1", url: "http://127.0.0.1:3000/login", reuseExistingServer: false, timeout: 180_000 },
  ],
});
