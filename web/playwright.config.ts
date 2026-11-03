import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  reporter: "list",
  use: { ...devices["Desktop Chrome"], channel: "chrome", baseURL: "http://127.0.0.1:5173" },
  webServer: { command: "node ./node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort", url: "http://127.0.0.1:5173", reuseExistingServer: true, timeout: 30_000 },
});
