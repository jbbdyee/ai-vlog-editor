import path from "node:path";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, import.meta.dirname, "CUTORY_");
  const allowedHosts = (env.CUTORY_ALLOWED_HOSTS ?? "")
    .split(",")
    .map((host) => host.trim())
    .filter(Boolean);

  return {
    plugins: [react(), tailwindcss()],
    resolve: { alias: { "@": path.resolve(import.meta.dirname, "src") } },
    server: {
      host: "127.0.0.1",
      allowedHosts,
      proxy: {
        "/api": {
          target: env.CUTORY_API_PROXY_TARGET ?? "http://127.0.0.1:8000",
          changeOrigin: true,
          rewrite: (url) => url.replace(/^\/api/, ""),
          configure: (proxy) => {
            proxy.on("proxyReq", (proxyReq) => {
              // The backend is reached through this loopback-only proxy. A tailnet
              // client's forwarded address would trip its local media guard.
              proxyReq.removeHeader("x-forwarded-for");
              proxyReq.removeHeader("forwarded");
            });
          },
        },
      },
    },
    test: {
      include: ["src/**/*.test.{ts,tsx}"],
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      css: true,
    },
  };
});
