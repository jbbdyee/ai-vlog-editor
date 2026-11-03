import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e-real",
  reporter: "list",
  timeout: 240_000,
  use: { ...devices["Desktop Chrome"], channel: "chrome", baseURL: process.env.WEB08B_BASE_URL ?? "http://127.0.0.1:5173" },
});
