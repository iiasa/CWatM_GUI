/**
 * Project-scoped file browsing against the Accelerator's "aterm-cli" API.
 * Login, token refresh, and authorized listing/download have all been
 * exercised end-to-end against the live cwatm-gui-dev project. See
 * atermFetch.ts for the auth details (confirmed live, applies here too).
 *
 * Job dispatch lives in jobs.ts, sharing the same atermFetch helper.
 */

import { ATERM_BASE } from "./config";
import { atermFetch } from "./atermFetch";

export interface FileEntry {
  /** Display name (the last path segment). */
  name: string;
  /** Full absolute path, as the server returns it - what file-stat/download-url expect. */
  path: string;
  size?: number;
  isFolder: boolean;
}

export function basename(path: string): string {
  return path.split("/").filter(Boolean).pop() ?? path;
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
  const res = await atermFetch(
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
  const res = await atermFetch(
    `${ATERM_BASE}/${projectSlug}/get-file-download-url/?filename=${encodeURIComponent(path)}`,
  );
  const data = await res.json();
  return typeof data === "string" ? data : data.url;
}
