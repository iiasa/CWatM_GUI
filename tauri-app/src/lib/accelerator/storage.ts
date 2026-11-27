/**
 * Where the OAuth refresh token lives.
 *
 * Desktop: the OS credential store (Windows Credential Manager / macOS
 * Keychain / Linux Secret Service) via a small Rust command
 * (`src-tauri/src/keychain.rs`, the `keyring` crate) - the same mechanism
 * the existing PySide6 app's Supabase login already uses
 * (`src/gui/utils/account_store.py`), under a distinct service name so the
 * two apps' entries never collide. `accli` itself just uses a plain local
 * JSON file; we deliberately hold desktop storage to the stronger standard
 * the existing app already sets, rather than matching accli's weaker one.
 *
 * Browser: localStorage. No persistent native vault exists in a browser
 * tab, and a short-lived OAuth refresh token is the kind of credential a
 * browser session is expected to hold anyway.
 */

import { isDesktop } from "./platform";

const ACCOUNT = "refresh_token";
const LOCALSTORAGE_KEY = "refresh_token";

export async function getRefreshToken(): Promise<string | null> {
  if (isDesktop()) {
    const { invoke } = await import("@tauri-apps/api/core");
    const value = await invoke<string | null>("keychain_get", { account: ACCOUNT });
    return value ?? null;
  }
  return window.localStorage.getItem(LOCALSTORAGE_KEY);
}

export async function setRefreshToken(token: string): Promise<void> {
  if (isDesktop()) {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("keychain_set", { account: ACCOUNT, value: token });
    return;
  }
  window.localStorage.setItem(LOCALSTORAGE_KEY, token);
}

export async function clearRefreshToken(): Promise<void> {
  if (isDesktop()) {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("keychain_delete", { account: ACCOUNT });
    return;
  }
  window.localStorage.removeItem(LOCALSTORAGE_KEY);
}
