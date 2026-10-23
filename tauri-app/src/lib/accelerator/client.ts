/**
 * Project-scoped calls against the Accelerator's "aterm-cli" API
 * (`/api/v1/aterm-cli/{project_slug}/...`). Confirmed live, with a real
 * device-flow (TERM_CLI-typed) access token: the only header/route
 * combination recognized at all is a bare token (no "Bearer" prefix) in
 * `x-authorization` against `aterm-cli` - `/v1/projects/` needs a session
 * cookie regardless of headers. Login, token refresh, and authorized
 * listing/download have all been exercised end-to-end against the live
 * cwatm-gui-dev project.
 *
 * Job dispatch (`jobs/dispatch/`) is deliberately left out for now -
 * running CWatM remotely needs a CWatM-ready docker image on the
 * Accelerator's execution cluster first, a separate, not-yet-resolved
 * prerequisite. This module is scoped to what Milestone 1 needs: login +
 * browsing a project's files.
 */

import { ATERM_BASE } from "./config";
import { getAccessToken, AcceleratorAuthError } from "./auth";
import { httpFetch } from "./platform";

export interface FileEntry {
  /** Display name (the last path segment). */
  name: string;
  /** Full absolute path, as the server returns it - what file-stat/download-url expect. */
  path: string;
  size?: number;
  isFolder: boolean;
}

function basename(path: string): string {
  return path.split("/").filter(Boolean).pop() ?? path;
}

async function authedFetch(url: string, init?: RequestInit): Promise<Response> {
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

/**
 * The folders and files directly inside `absolutePath` (one level, not
 * recursive - unlike the old aterm-cli "enumerate-all-files", this is a
 * folder listing). Defaults to the project root.
 *
 * `absolutePath` must have NO trailing slash - confirmed live against a
 * real file: "cwatm-gui-dev" correctly lists its contents, but
 * "cwatm-gui-dev/" (the team's own example for this) silently returns
 * empty, as does any other path with a trailing slash (e.g.
 * "cwatm-gui-dev/inhale/" vs the working "cwatm-gui-dev/inhale"). A
 * folder entry's own `path` (from this function's own output) is always
 * already in the right shape to pass back in here to browse into it.
 */
export async function listFiles(projectSlug: string, absolutePath: string = projectSlug): Promise<FileEntry[]> {
  const encodedPath = btoa(absolutePath);
  const res = await authedFetch(
    `${ATERM_BASE}/${projectSlug}/node-items/${encodedPath}/`,
  );
  const data: { nodes: { absolute_node_name: string }[]; objects: { filename: string; file_size?: number }[] } =
    await res.json();
  const folders: FileEntry[] = data.nodes.map((n) => ({
    name: basename(n.absolute_node_name),
    path: n.absolute_node_name,
    isFolder: true,
  }));
  const files: FileEntry[] = data.objects.map((o) => ({
    name: basename(o.filename),
    path: o.filename,
    size: o.file_size,
    isFolder: false,
  }));
  return [...folders, ...files];
}

/** A presigned, time-limited URL to download the file at `path` (a full path, as from listFiles) directly - no auth header needed on the follow-up GET. */
export async function getFileDownloadUrl(projectSlug: string, path: string): Promise<string> {
  const res = await authedFetch(
    `${ATERM_BASE}/${projectSlug}/get-file-download-url/?filename=${encodeURIComponent(path)}`,
  );
  const data = await res.json();
  return typeof data === "string" ? data : data.url;
}
