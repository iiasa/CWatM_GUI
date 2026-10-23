import { useState } from "react";
import { getFileDownloadUrl, listFiles, type FileEntry } from "../lib/accelerator/client";
import { logout } from "../lib/accelerator/auth";
import { openExternal } from "../lib/accelerator/platform";

interface FileBrowserProps {
  onLoggedOut: () => void;
}

export default function FileBrowser({ onLoggedOut }: FileBrowserProps) {
  // Confirmed live via GET /api/v1/projects/cwatm-gui-dev/ (public project
  // metadata, no auth needed) - a reasonable default now that it's a real
  // project rather than a proposed name.
  const [projectSlug, setProjectSlug] = useState("cwatm-gui-dev");
  const [files, setFiles] = useState<FileEntry[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The breadcrumb trail of absolute paths visited, root first - each
  // entry is already in the exact shape listFiles expects (no trailing
  // slash). pathStack[0] is always the project root.
  const [pathStack, setPathStack] = useState<string[]>([]);

  async function loadPath(stack: string[]) {
    setBusy(true);
    setError(null);
    setFiles(null);
    try {
      const absolutePath = stack[stack.length - 1];
      setFiles(await listFiles(projectSlug.trim(), absolutePath));
      setPathStack(stack);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function browse(e: React.FormEvent) {
    e.preventDefault();
    await loadPath([projectSlug.trim()]);
  }

  function open(entry: FileEntry) {
    if (entry.isFolder) {
      loadPath([...pathStack, entry.path]);
    }
  }

  function goTo(index: number) {
    loadPath(pathStack.slice(0, index + 1));
  }

  async function download(path: string) {
    try {
      const url = await getFileDownloadUrl(projectSlug.trim(), path);
      await openExternal(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <main className="container">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1>Project Files</h1>
        <button
          type="button"
          onClick={async () => {
            await logout();
            onLoggedOut();
          }}
        >
          Log out
        </button>
      </div>

      <form className="row" onSubmit={browse}>
        <input
          autoFocus
          value={projectSlug}
          onChange={(e) => setProjectSlug(e.currentTarget.value)}
          placeholder="Project slug (e.g. cwatm-gui-dev)"
        />
        <button type="submit" disabled={busy || !projectSlug.trim()}>
          {busy ? "Loading..." : "Browse"}
        </button>
      </form>

      {pathStack.length > 0 && (
        <p style={{ fontFamily: "monospace" }}>
          {pathStack.map((p, i) => (
            <span key={p}>
              {i > 0 && " / "}
              <button
                type="button"
                onClick={() => goTo(i)}
                disabled={i === pathStack.length - 1}
                style={{ fontFamily: "monospace" }}
              >
                {i === 0 ? p : p.split("/").pop()}
              </button>
            </span>
          ))}
        </p>
      )}

      {error && <p style={{ color: "crimson" }}>{error}</p>}

      {files && (
        <ul style={{ textAlign: "left" }}>
          {files.length === 0 && <li>(empty folder)</li>}
          {files.map((f) => (
            <li key={f.path}>
              {f.isFolder ? (
                <button type="button" onClick={() => open(f)}>
                  📁 {f.name}
                </button>
              ) : (
                <>
                  📄 {f.name}
                  {typeof f.size === "number" && ` (${f.size} bytes)`}
                  {" — "}
                  <button type="button" onClick={() => download(f.path)}>
                    Download
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
