/**
 * In-app job status, without any job-status API.
 *
 * aterm-cli doesn't expose job status/logs directly (confirmed live during
 * the Milestone 1 auth investigation - the parallel "/v1/projects/jobs/..."
 * routes need a session cookie, same as file browsing did before the
 * team's fix; they said they'd add a proper endpoint, no date given). But
 * every dispatched job's own log lands as a real project file at a
 * predictable path - confirmed live twice now (jobs 15412 and 15414):
 *
 *   {project_slug}/job-outputs/{job_id}/logs/full/job-{job_id}--{suffix}.log
 *
 * where {suffix} isn't known in advance (looks like a timestamp), so the
 * folder has to be listed rather than the path guessed outright. Once that
 * file exists, the job is done (success or failure) - its content carries
 * cwatm_model_runner.py's own `@@CWATM_GUI:RESULT:True|False:<last_dis>@@`
 * marker (see CLAUDE.md's CWatM Integration section) and, on failure,
 * CWatM's own "===== CWATM FILE ERROR =====" block. This module polls for
 * that file and parses it - no new Accelerator API surface needed.
 */

import { listFiles, getFileDownloadUrl } from "./client";
import { httpFetch } from "./platform";

export interface JobResult {
  /** null = log not found yet (job still building/running, or not dispatched long enough ago). */
  success: boolean | null;
  lastDischarge?: number;
  /** The CWATM FILE ERROR block's content, if the run failed with one. */
  errorSummary?: string;
  logPath: string;
  logUrl: string;
}

// The discharge group must also accept the literal "None" -
// cwatm_model_runner.py's own last_dis starts as None and stays that way
// for any failure before the model computes a real value (which is every
// failure we've seen live: bad settings path, Error 215/220, our own
// pre-processing fallback in jobs.ts). A number-only pattern here silently
// treated every one of those as "no marker found yet" (still running) -
// a real bug, caught by writing a test against the exact marker text we've
// seen live rather than an assumed shape.
const RESULT_MARKER_RE = /@@CWATM_GUI:RESULT:(True|False):(None|[\d.eE+-]+)@@/;
const FILE_ERROR_RE = /={5,}\s*CWATM FILE ERROR\s*={5,}\s*\n([\s\S]*?)\n\s*\n/;

/**
 * Pure parsing of a job log's text - no network, fully unit-testable.
 * Split out from fetchJobLog so the actual parsing logic (the part that's
 * broken exactly as often as the plumbing around it) can be tested without
 * mocking listFiles/getFileDownloadUrl/httpFetch.
 */
export function parseJobLog(logText: string): Omit<JobResult, "logPath" | "logUrl"> {
  const resultMatch = RESULT_MARKER_RE.exec(logText);
  if (!resultMatch) {
    // Log exists but the run hasn't reached its own result marker yet (e.g.
    // still mid-build, or an infra-level failure before cwatm_model_runner.py
    // ran at all) - treat as still unresolved rather than guessing.
    return { success: null };
  }
  const success = resultMatch[1] === "True";
  const lastDischarge = resultMatch[2] === "None" ? undefined : Number(resultMatch[2]);
  const errorMatch = !success ? FILE_ERROR_RE.exec(logText) : null;
  return {
    success,
    lastDischarge,
    errorSummary: errorMatch ? errorMatch[1].trim() : undefined,
  };
}

/** Finds and downloads the job's own log file, if it exists yet. Returns null if not (still running). */
export async function fetchJobLog(projectSlug: string, jobId: string): Promise<JobResult | null> {
  const folder = `${projectSlug}/job-outputs/${jobId}/logs/full`;
  let entries;
  try {
    entries = await listFiles(projectSlug, folder);
  } catch {
    // Folder doesn't exist yet - the job hasn't written its log, still in progress.
    return null;
  }
  const logFile = entries.find(
    (e) => !e.isFolder && e.name.startsWith(`job-${jobId}--`) && e.name.endsWith(".log"),
  );
  if (!logFile) return null;

  const logUrl = await getFileDownloadUrl(projectSlug, logFile.path);
  const logText = await (await httpFetch(logUrl)).text();
  return { ...parseJobLog(logText), logPath: logFile.path, logUrl };
}

/** Extra wall-clock time to keep polling beyond the job's own dispatch timeout, to cover build+queue time before execution even starts (the dispatch timeout governs execution, not the full wait). */
const POLL_GRACE_SECONDS = 10 * 60;

/**
 * Polls fetchJobLog until a result is found or time runs out. Returns a
 * cancel function; onUpdate is called with each poll's outcome (including
 * null/unresolved ones, so the caller can show "still running"), and once
 * more with `timedOut: true` if polling gives up without ever finding a
 * result - without this, giving up was previously silent: the UI would
 * stay on "running" forever with no sign anything had changed, even though
 * (with the old fixed 80 x 15s = 20min cap) that could happen well before
 * a job's own dispatch timeout (3600s by default) was reached, i.e. while
 * the job might still be legitimately running.
 *
 * `timeoutSeconds` should be the same value passed as `timeoutSeconds` to
 * the dispatch that started this job (defaults to jobs.ts's own default) -
 * polling runs for that long plus POLL_GRACE_SECONDS, not a disconnected
 * guess.
 */
export function pollJobLog(
  projectSlug: string,
  jobId: string,
  onUpdate: (result: JobResult | null, timedOut?: boolean) => void,
  { intervalMs = 15000, timeoutSeconds = 3600 }: { intervalMs?: number; timeoutSeconds?: number } = {},
): () => void {
  let cancelled = false;
  let attempts = 0;
  const maxAttempts = Math.ceil(((timeoutSeconds + POLL_GRACE_SECONDS) * 1000) / intervalMs);

  async function tick() {
    if (cancelled) return;
    attempts += 1;
    try {
      const result = await fetchJobLog(projectSlug, jobId);
      if (cancelled) return;
      onUpdate(result);
      if (result?.success !== undefined && result?.success !== null) return; // done
    } catch {
      // Transient fetch error - keep polling rather than giving up.
    }
    if (attempts < maxAttempts) {
      setTimeout(tick, intervalMs);
    } else if (!cancelled) {
      onUpdate(null, true);
    }
  }

  tick();
  return () => {
    cancelled = true;
  };
}
