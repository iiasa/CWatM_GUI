/**
 * Accelerator server endpoints.
 *
 * Mirrors the defaults in IIASA's own reference CLI (`accli`), confirmed
 * against the live OpenAPI spec at {SERVER_URL}/api/docs.
 */
export const SERVER_URL = "https://accelerator.iiasa.ac.at";
export const WEBCLI_URL = "https://accelerator.iiasa.ac.at";

/** Where a user gets their device-flow authorization code (opened in a real browser). */
export const AUTH_CODE_URL = `${WEBCLI_URL}/acli-auth-code`;

export const API_BASE = `${SERVER_URL}/api/v1`;
export const OAUTH_BASE = `${API_BASE}/oauth/device`;
/**
 * User-facing file/project browsing API ("aterm-cli" = "Accelerator
 * terminal CLI"). Confirmed live, with a real device-flow token: the
 * parallel general "/v1/projects/..." routes require a session cookie
 * regardless of what's sent in headers ("User session not present." even
 * with a valid token) - aterm-cli is the one that actually recognizes a
 * device-flow (TERM_CLI-typed) token at all.
 */
export const ATERM_BASE = `${API_BASE}/aterm-cli`;
