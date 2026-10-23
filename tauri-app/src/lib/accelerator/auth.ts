/**
 * Accelerator device-flow login, mirroring `accli`'s own implementation
 * (see accli/cli.py `login()` and accli/token.py `exchange_refresh_token`,
 * read directly from IIASA's open-source CLI to pin down the exact
 * sequencing - the OpenAPI spec alone left it ambiguous):
 *
 *   1. The user opens AUTH_CODE_URL in a real browser while logged into
 *      the Accelerator web session; that page shows them a short code.
 *   2. `redeemDeviceCode(code)` exchanges it for a refresh token.
 *   3. `getAccessToken()` exchanges the stored refresh token for a
 *      short-lived access token, rotating the refresh token each time -
 *      every authenticated API call goes through this.
 *
 * Note: this is unrelated to the separate `/oauth/device/cas-token/`
 * endpoint, which is purely an internal refresh callback for hf_xet's
 * large-file transfer sessions (see accli/token.py `exchange_refresh_token`
 * building `xet_session_prj_...`), not something application code calls
 * directly.
 */

import { OAUTH_BASE } from "./config";
import { httpFetch } from "./platform";
import { clearRefreshToken, getRefreshToken, setRefreshToken } from "./storage";

export class AcceleratorAuthError extends Error {}

interface AccessTokenResponse {
  access_token: string;
  refresh_token: string;
}

/** Exchange a device authorization code (from AUTH_CODE_URL) for a refresh token. */
export async function redeemDeviceCode(deviceAuthorizationCode: string): Promise<void> {
  const res = await httpFetch(`${OAUTH_BASE}/token/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ device_authorization_code: deviceAuthorizationCode }),
  });

  if (res.status === 400) {
    const body = await res.json().catch(() => ({}));
    throw new AcceleratorAuthError(body.detail ?? "Invalid or expired authorization code.");
  }
  if (!res.ok) {
    throw new AcceleratorAuthError(`Login failed (HTTP ${res.status}).`);
  }

  // The token/ endpoint's response body is the refresh token itself
  // (a JSON-encoded string, not an object - matches accli's
  // `save_token_details(token_response.json(), ...)`).
  const refreshToken: string = await res.json();
  await setRefreshToken(refreshToken);
}

export async function isLoggedIn(): Promise<boolean> {
  return (await getRefreshToken()) !== null;
}

export async function logout(): Promise<void> {
  await clearRefreshToken();
  cachedAccessToken = null;
  cachedExpiresAt = 0;
}

// In-memory access-token cache, same shape as accli's: short-lived
// (expires in ~1h), refreshed with a few minutes of headroom, and a
// single in-flight exchange shared by concurrent callers instead of each
// one rotating the refresh token out from under the others.
let cachedAccessToken: string | null = null;
let cachedExpiresAt = 0;
let inFlightExchange: Promise<string> | null = null;

const EXPIRY_HEADROOM_MS = 5 * 60 * 1000;

export async function getAccessToken(): Promise<string> {
  const now = Date.now();
  if (cachedAccessToken && cachedExpiresAt - now > EXPIRY_HEADROOM_MS) {
    return cachedAccessToken;
  }
  if (inFlightExchange) {
    return inFlightExchange;
  }

  inFlightExchange = (async () => {
    const refreshToken = await getRefreshToken();
    if (!refreshToken) {
      throw new AcceleratorAuthError("Not logged in.");
    }

    const res = await httpFetch(`${OAUTH_BASE}/access-token/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (res.status === 400 || res.status === 401 || res.status === 403) {
      await clearRefreshToken();
      throw new AcceleratorAuthError("Session expired. Please log in again.");
    }
    if (!res.ok) {
      throw new AcceleratorAuthError(`Could not refresh session (HTTP ${res.status}).`);
    }

    const data: AccessTokenResponse = await res.json();
    await setRefreshToken(data.refresh_token);

    cachedAccessToken = data.access_token;
    // Server tokens last ~1h; match accli's conservative ~50 min cache window.
    cachedExpiresAt = Date.now() + 50 * 60 * 1000;
    return data.access_token;
  })();

  try {
    return await inFlightExchange;
  } finally {
    inFlightExchange = null;
  }
}
