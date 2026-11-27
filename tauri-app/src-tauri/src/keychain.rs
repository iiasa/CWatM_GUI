//! The Accelerator refresh token, stored in the OS credential store (Windows
//! Credential Manager / macOS Keychain / Linux Secret Service) via the
//! `keyring` crate - the same storage the existing PySide6 app's Supabase
//! login already uses (see `src/gui/utils/account_store.py`), kept under a
//! distinct service name so the two apps' entries never collide.
//!
//! Every command swallows a missing keychain backend (e.g. a headless Linux
//! session with no Secret Service) into `None`/`Ok(())` rather than failing -
//! the login simply isn't remembered, matching the Python side's behaviour.

use keyring::Entry;

const SERVICE: &str = "CWatM_GUI_Accelerator";

fn entry(account: &str) -> Option<Entry> {
    Entry::new(SERVICE, account).ok()
}

#[tauri::command]
pub fn keychain_get(account: String) -> Option<String> {
    entry(&account)?.get_password().ok()
}

#[tauri::command]
pub fn keychain_set(account: String, value: String) -> bool {
    match entry(&account) {
        Some(e) => e.set_password(&value).is_ok(),
        None => false,
    }
}

#[tauri::command]
pub fn keychain_delete(account: String) -> bool {
    match entry(&account) {
        Some(e) => matches!(
            e.delete_credential(),
            Ok(()) | Err(keyring::Error::NoEntry)
        ),
        None => false,
    }
}
