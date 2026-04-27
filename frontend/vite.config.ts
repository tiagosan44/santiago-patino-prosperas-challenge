import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: "0.0.0.0",
  },
  test: {
    environment: "happy-dom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    // Exclude Playwright e2e specs — they have their own runner (npm run e2e).
    exclude: ["**/node_modules/**", "**/dist/**", "tests/e2e/**"],
  },
});
