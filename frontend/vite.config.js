import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Keeps the browser same-origin in development, so no CORS dance.
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
