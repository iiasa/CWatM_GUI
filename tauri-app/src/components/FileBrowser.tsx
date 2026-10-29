import { useEffect, useState } from "react";
import { getFileDownloadUrl, listFiles, type FileEntry } from "../lib/accelerator/client";
import { dispatchCwatmRun, type DispatchedJob } from "../lib/accelerator/jobs";
import { pollJobLog, type JobResult } from "../lib/accelerator/jobStatus";
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
  const [dispatchedJob, setDispatchedJob] = useState<DispatchedJob | null>(null);
  // null = still polling/unresolved; a JobResult once the job's own log is found.
  const [jobResult, setJobResult] = useState<JobResult | null>(null);
  // true once pollJobLog gives up without ever finding a result - without
  // this, giving up was silent and the status just stayed on "running"
  // forever with no sign anything had changed.
  const [pollTimedOut, setPollTimedOut] = useState(false);

  // Poll for the dispatched job's log whenever dispatchedJob changes -
  // cancelled automatically on unmount or when a new job is dispatched.
  useEffect(() => {
    if (!dispatchedJob) return;
    const slug = projectSlug.trim();
    const cancel = pollJobLog(
      slug,
      dispatchedJob.jobId,
      (result, timedOut) => {
        setJobResult(result);
        if (timedOut) setPollTimedOut(true);
      },
      { timeoutSeconds: dispatchedJob.timeoutSeconds },
    );
    return cancel;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dispatchedJob]);

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

  async function runCwatm(entry: FileEntry) {
    setError(null);
    setDispatchedJob(null);
    setJobResult(null);
    setPollTimedOut(false);
    try {
      // The dispatched job itself gives this run its own fresh PathOut
      // (patching a local copy of the settings file at job start) - see
      // jobs.ts's buildCommand for why this is done there, not here.
      const job = await dispatchCwatmRun(projectSlug.trim(), {
        name: `CWatM: ${entry.name}`,
        settingsPath: entry.path,
      });
      setDispatchedJob(job);
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

      {dispatchedJob && (
        <div style={{ textAlign: "left" }}>
          <p>
            Dispatched job <code>{dispatchedJob.jobId}</code>
            {pollTimedOut ? (
              <>
                {" - "}
                <strong style={{ color: "orange" }}>status unknown</strong> (gave up checking after{" "}
                {Math.round(dispatchedJob.timeoutSeconds / 60)}+ min with no result - it may still be running; check
                the Accelerator web UI directly)
              </>
            ) : jobResult?.success === undefined || jobResult?.success === null ? (
              <> - running (building the image can take a few minutes on a content change; checking every 15s)...</>
            ) : jobResult.success ? (
              <> - <strong style={{ color: "green" }}>succeeded</strong> (last discharge: {jobResult.lastDischarge} m³/s)</>
            ) : (
              <> - <strong style={{ color: "crimson" }}>failed</strong></>
            )}
          </p>
          {jobResult?.success === false && jobResult.errorSummary && (
            <pre style={{ whiteSpace: "pre-wrap", background: "#2a1414", padding: "0.5em", borderRadius: 4 }}>
              {jobResult.errorSummary}
            </pre>
          )}
          {jobResult && (
            <button type="button" onClick={() => openExternal(jobResult.logUrl)}>
              View full log
            </button>
          )}
          {jobResult?.success === true && jobResult.outputDir && (
            <p>
              Output folder: <code>{jobResult.outputDir}</code>
              {" — "}
              <button type="button" onClick={() => loadPath([projectSlug.trim(), jobResult.outputDir!])}>
                Browse
              </button>
            </p>
          )}
          {jobResult?.success === true && !jobResult.outputDir && (
            <p style={{ color: "orange" }}>
              Run succeeded, but no output directory marker was found in its log (older job, or it predates this
              feature) - check the Accelerator web UI directly for its output files.
            </p>
          )}
        </div>
      )}

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
                  {f.name.endsWith(".ini") && (
                    <>
                      {" — "}
                      <button type="button" onClick={() => runCwatm(f)}>
                        Run CWatM
                      </button>
                    </>
                  )}
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
