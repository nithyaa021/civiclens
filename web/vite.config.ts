import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The Vite dev/preview server proxies API calls in development. In production
// the SPA calls VITE_API_BASE_URL directly (see src/lib/api.ts).
const target = process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000";
const proxy = {
  "/api": { target, changeOrigin: true },
  // The sidebar's API reference link points at the FastAPI Swagger UI.
  "/docs": { target, changeOrigin: true },
  "/redoc": { target, changeOrigin: true },
  "/openapi.json": { target, changeOrigin: true },
};

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy,
  },
  preview: {
    port: 4173,
    proxy,
  },
});
