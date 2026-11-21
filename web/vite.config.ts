import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev mode (npm run dev): the page runs on :5173 and forwards /api calls to the Python API on :8000.
export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
  build: { outDir: "dist", sourcemap: false },
});
