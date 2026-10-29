import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import basicSsl from "@vitejs/plugin-basic-ssl";

/**
 * A second, separate dev config for testing the plain-browser-tab target,
 * alongside (not replacing) vite.config.ts's Tauri desktop dev server.
 *
 * Desktop bypasses browser CORS entirely (requests go through Tauri's
 * Rust-side HTTP client, see platform.ts), so vite.config.ts's port 1420
 * never needed HTTPS or a CORS-allowed origin. A plain browser tab does
 * need both - the Accelerator team confirmed (live, 2026-10-28) that
 * https://localhost:7979 is an already-allowlisted CORS origin (tested
 * directly: it's the only localhost origin/scheme combination that gets
 * back an Access-Control-Allow-Origin header - plain http://localhost:7979
 * and http://localhost:1420 both don't). @vitejs/plugin-basic-ssl
 * generates a local self-signed cert automatically so this origin can
 * actually be served over HTTPS without any manual cert setup.
 *
 * Run with: npm run dev:browser -- then open https://localhost:7979
 * (accept the self-signed cert warning once - it's your own local dev
 * server, not a real deployment) and log in there separately: browser-mode
 * token storage is localStorage, not the desktop keychain, so it's an
 * independent login from the Tauri app's.
 */
export default defineConfig({
  plugins: [react(), basicSsl()],
  server: {
    port: 7979,
    strictPort: true,
  },
});
