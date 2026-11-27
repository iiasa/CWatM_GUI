/**
 * The one place that tells desktop (Tauri webview) and browser apart.
 *
 * Everything else in src/lib/accelerator should go through `httpFetch`/
 * `isDesktop` rather than re-checking `window.__TAURI_INTERNALS__` itself,
 * so the desktop/browser split stays in one spot as more of it appears
 * (token storage today; likely auth-flow branching later).
 */

export function isDesktop(): boolean {
  return "__TAURI_INTERNALS__" in window;
}

/**
 * fetch() that goes through Tauri's Rust-side http client on desktop
 * (bypasses the webview's CORS enforcement entirely - the request never
 * touches the browser engine's network stack) and plain browser fetch
 * otherwise (requires the Accelerator to allow our origin via CORS, which
 * the team confirmed they can enable on request).
 */
export async function httpFetch(
  url: string,
  init?: RequestInit,
): Promise<Response> {
  if (isDesktop()) {
    const { fetch: tauriFetch } = await import("@tauri-apps/plugin-http");
    return tauriFetch(url, init);
  }
  return window.fetch(url, init);
}

/**
 * Open `url` in the system's default handler (browser/downloader), never
 * inside the app's own window. `window.open()` doesn't do this on
 * desktop - Tauri's webview either blocks it or tries to open an in-app
 * webview, not hand off to the OS - so desktop goes through the opener
 * plugin instead.
 */
export async function openExternal(url: string): Promise<void> {
  if (isDesktop()) {
    const { openUrl } = await import("@tauri-apps/plugin-opener");
    await openUrl(url);
    return;
  }
  window.open(url, "_blank");
}
