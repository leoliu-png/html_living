import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    strictPort: true,
    proxy: {
      "^/api/.*$": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "^/auth/.*$": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "^/skill/.*$": {
        target: "http://127.0.0.1:30002",
      },
      "^/mcp.*$": {
        target: "http://127.0.0.1:30002",
        changeOrigin: true,
      },
    },
  },
});
