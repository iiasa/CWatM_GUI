/**
 * The one authenticated-fetch helper for the Accelerator's "aterm-cli" API
 * (`/api/v1/aterm-cli/{project_slug}/...`). Confirmed live, with a real
 * device-flow (TERM_CLI-typed) access token: the only header/route
 * combination recognized at all is a bare token (no "Bearer" prefix) in
 * `x-authorization` against `aterm-cli` - `/v1/projects/` needs a session
 * cookie regardless of headers, even though its OpenAPI schema lists
 * x-authorization as an accepted parameter too.
 *
 * Shared by client.ts (file browsing) and jobs.ts (dispatch).
 */

import { getAccessToken, AcceleratorAuthError } from "./auth";
import { httpFetch } from "./platform";

export async function atermFetch(url: string, init?: RequestInit): Promise<Response> {
  const accessToken = await getAccessToken();
  const headers = new Headers(init?.headers);
  headers.set("x-authorization", accessToken);

  const res = await httpFetch(url, { ...init, headers });
  if (res.status === 401 || res.status === 403) {
    // Surface the server's own detail (e.g. "You are not allowed.") rather
    // than a generic message - it proved to be the useful diagnostic
    // signal during the auth investigation.
    const detail = await res
      .json()
      .then((d) => d?.detail)
      .catch(() => null);
    throw new AcceleratorAuthError(detail || "Not authorized for this project.");
  }
  if (!res.ok) {
    throw new Error(`Accelerator API error (HTTP ${res.status}) for ${url}`);
  }
  return res;
}
