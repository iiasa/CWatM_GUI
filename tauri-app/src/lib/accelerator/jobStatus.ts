/**
 * In-app job status, via the Accelerator's real job-log manifest endpoint.
 *
 * `GET {ATERM_BASE}/{project_slug}/jobs/{job_id}/logs/` (confirmed live in
 * the OpenAPI spec, 2026-11-02 - found via a direct link into the docs,
 * operationId get_job_logs_v1_aterm_cli__project_slug__jobs__job_id__logs__get)
 * didn't exist when this module was first written for Milestone 2 (the
 * team said they'd add a status/log endpoint, no date given) - back then
 * this polled for the job's own uploaded log FILE at a guessed path
 * instead (see git history). This replaces that entirely: the manifest
 * gives every log source of a job (merged by time), paginated by cursor,
 * plus the one thing file-polling could never provide - an explicit
 * `job_completed` flag from the Accelerator itself, independent of
 * whether the job's own code ever got to print anything at all (a pod
 * OOM-killed or evicted before cwatm_model_runner.py even ran used to
 * leave file-polling stuck on "running" forever).
 *
 * pickPrimarySource's guess that the "wkube" source carries CWatM's own
 * stdout/stderr (where the @@CWATM_GUI:...@@ markers are printed) is
 * confirmed live (job 15699, 2026-11-02): a full successful run showed
 * correctly in the app's inline log (catchment creation, routing,
 * progress lines, the OUTPUT_DIR and RESULT markers all present and
 * correctly parsed - the per-line ISO-timestamp prefix each log line
 * gets from this endpoint doesn't interfere, since neither regex is
 * anchored to line start), and job_completed correctly resolved the
 * status from "running" to "succeeded" with the right discharge value.
 */

import { ATERM_BASE } from "./config";
import { atermFetch } from "./atermFetch";
import { httpFetch } from "./platform";
import { wdrvPathToProjectPath } from "./outputs";

export interface JobLogSource {
  /** Folder name of the source, e.g. "wkube", "celery", "podevents". */
  name: string;
  kind: "stream" | "events";
}

export interface JobLogChunk {
  source: string;
  /** Position within its source - join chunks in this order. */
  seq: number;
  /** Presigned S3 GET URL for the chunk text, valid for about 30 minutes. */
  url: string;
  start?: string;
  end: string;
  size: number;
}

export interface JobLogEvent {
  id: string;
  time: string;
  precise: boolean;
  /** Kubernetes object kind, e.g. "Pod" or "Job". */
  kind: string;
  /** Kubernetes reason, e.g. "Scheduled" or "Evicted". */
  reason: string;
  message: string;
}

export interface JobLogManifestResponse {
  attempt: number | null;
  attempts: number[];
  sources: JobLogSource[];
  chunks: JobLogChunk[];
  events: JobLogEvent[];
  before: string | null;
  after: string | null;
  has_more_before: boolean;
  job_completed: boolean;
}

export interface JobResult {
  /** null = not resolved yet (job still building/running, or no result marker found yet). */
  success: boolean | null;
  lastDischarge?: number;
  /** The CWATM FILE ERROR block's content on a code-level failure, or a cluster-events summary on an infra-level one (job_completed but no result marker at all - a pod eviction/OOM-kill before any code ran, which the old file-polling design could never distinguish from "still running"). */
  errorSummary?: string;
  /** Project-relative path to this run's own output directory, if the job got far enough to print its OUTPUT_DIR marker (see jobs.ts's buildCommand) - undefined if it crashed before that point. */
  outputDir?: string;
  /** Full concatenated text of the job's primary log source, oldest first. */
  logText: string;
  /** The Accelerator's own authoritative "this job is done" signal (manifest's job_completed) - independent of whether a result marker was ever found. */
  jobCompleted: boolean;
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
// Printed by jobs.ts's buildCommand right after it computes its own
// job-unique output directory under /mnt/wdrv/output/ - the client can't
// predict that path ahead of dispatch (it's generated inside the
// container, from its own pid + the current time), so it's read back out
// of the job's log instead, same as the RESULT marker.
const OUTPUT_DIR_MARKER_RE = /@@CWATM_GUI:OUTPUT_DIR:(\S+)@@/;

/**
 * Pure parsing of a job log's text - no network, fully unit-testable.
 * `jobCompleted` (the Accelerator's own signal, not inferred from the
 * text) decides how to read the absence of a RESULT marker: still
 * running, or a genuine infra-level failure.
 */
export function parseJobLog(
  logText: string,
  projectSlug: string,
  jobCompleted: boolean,
): Pick<JobResult, "success" | "lastDischarge" | "errorSummary" | "outputDir"> {
  const outputDirMatch = OUTPUT_DIR_MARKER_RE.exec(logText);
  const outputDir = outputDirMatch ? wdrvPathToProjectPath(projectSlug, outputDirMatch[1]) : undefined;

  const resultMatch = RESULT_MARKER_RE.exec(logText);
  if (!resultMatch) {
    if (!jobCompleted) {
      // Still running (or no text yet) - nothing to parse.
      return { success: null, outputDir };
    }
    // The Accelerator itself says this job is done, but its own code never
    // printed a result - a pod eviction/OOM-kill/crash before
    // cwatm_model_runner.py even ran. fetchJobLog fills in errorSummary
    // from the manifest's cluster events for this case.
    return { success: false, outputDir };
  }
  const success = resultMatch[1] === "True";
  const lastDischarge = resultMatch[2] === "None" ? undefined : Number(resultMatch[2]);
  const errorMatch = !success ? FILE_ERROR_RE.exec(logText) : null;
  return {
    success,
    lastDischarge,
    errorSummary: errorMatch ? errorMatch[1].trim() : undefined,
    outputDir,
  };
}

/** Picks which log source carries the job's own stdout/stderr (where the @@CWATM_GUI:...@@ markers are printed) - see this module's doc comment for why "wkube" is the guess. */
export function pickPrimarySource(sources: JobLogSource[]): string | null {
  const streamSources = sources.filter((s) => s.kind === "stream");
  return streamSources.find((s) => s.name === "wkube")?.name ?? streamSources[0]?.name ?? null;
}

/** Turns the manifest's cluster events into a short readable summary - the only diagnostic available for an infra-level failure (no result marker, because no job code ever ran). */
export function summarizeEvents(events: JobLogEvent[]): string | undefined {
  if (events.length === 0) return undefined;
  return events.map((e) => `${e.time} ${e.kind}/${e.reason}: ${e.message}`).join("\n");
}

const MAX_CHUNKS_PER_PAGE = 100; // the API's own max
// Safety cap on how many pages to walk backward for in one fetch - about
// MAX_CHUNKS_PER_PAGE * this many chunks. A CWatM run's own text output
// isn't expected to be huge, but this avoids an unbounded loop against a
// pathological job.
const MAX_BACKWARD_PAGES = 20;

async function fetchJobLogManifest(
  projectSlug: string,
  jobId: string,
  opts: { sources?: string; before?: string; limit?: number } = {},
): Promise<JobLogManifestResponse> {
  const params = new URLSearchParams();
  if (opts.sources) params.set("sources", opts.sources);
  if (opts.before) params.set("before", opts.before);
  params.set("limit", String(opts.limit ?? MAX_CHUNKS_PER_PAGE));
  const res = await atermFetch(`${ATERM_BASE}/${projectSlug}/jobs/${jobId}/logs/?${params.toString()}`);
  return res.json();
}

async function fetchChunkText(chunk: JobLogChunk): Promise<string> {
  const res = await httpFetch(chunk.url);
  return res.text();
}

/**
 * Fetches the job's full primary-source log text (walking `before` pages
 * backward as needed - see MAX_BACKWARD_PAGES), plus whether the
 * Accelerator itself now considers the job done and the events from its
 * most recent page (likely to hold any terminal pod-eviction/OOM event).
 *
 * Re-fetches and re-concatenates everything on every call rather than
 * caching already-seen chunks across polls - simpler, and fine for a
 * CWatM run's modest text output; an obvious future optimization if a
 * job ever produces enough log text for this to matter.
 */
async function fetchFullSourceLog(
  projectSlug: string,
  jobId: string,
): Promise<{ text: string; jobCompleted: boolean; events: JobLogEvent[] }> {
  const first = await fetchJobLogManifest(projectSlug, jobId);
  const sourceName = pickPrimarySource(first.sources);
  if (!sourceName) {
    return { text: "", jobCompleted: first.job_completed, events: first.events };
  }

  let chunks = first.chunks.filter((c) => c.source === sourceName);
  let before = first.has_more_before ? first.before : null;
  let pages = 0;
  while (before && pages < MAX_BACKWARD_PAGES) {
    const page = await fetchJobLogManifest(projectSlug, jobId, { sources: sourceName, before });
    chunks = [...page.chunks, ...chunks];
    before = page.has_more_before ? page.before : null;
    pages += 1;
  }
  chunks.sort((a, b) => a.seq - b.seq);

  const texts = await Promise.all(chunks.map(fetchChunkText));
  return { text: texts.join(""), jobCompleted: first.job_completed, events: first.events };
}

/** Fetches and parses the job's current status. Always returns a real result - `success: null` means not resolved yet, `jobCompleted` is the authoritative done/not-done signal. */
export async function fetchJobLog(projectSlug: string, jobId: string): Promise<JobResult> {
  const { text, jobCompleted, events } = await fetchFullSourceLog(projectSlug, jobId);
  const parsed = parseJobLog(text, projectSlug, jobCompleted);
  const errorSummary = parsed.errorSummary ?? (jobCompleted && parsed.success === false ? summarizeEvents(events) : undefined);
  return { ...parsed, errorSummary, logText: text, jobCompleted };
}

/** Extra wall-clock time to keep polling beyond the job's own dispatch timeout, to cover build+queue time before execution even starts (the dispatch timeout governs execution, not the full wait). */
const POLL_GRACE_SECONDS = 10 * 60;

const EMPTY_RESULT: JobResult = { success: null, logText: "", jobCompleted: false };

/**
 * Polls fetchJobLog until the Accelerator reports the job done
 * (`jobCompleted`) or time runs out. Returns a cancel function; onUpdate
 * is called with each poll's result (including unresolved ones, so the
 * caller can show "still running"), and once more with `timedOut: true`
 * if polling gives up without the Accelerator ever reporting completion -
 * without this, giving up was previously silent.
 *
 * `timeoutSeconds` should be the same value passed as `timeoutSeconds` to
 * the dispatch that started this job (defaults to jobs.ts's own default) -
 * polling runs for that long plus POLL_GRACE_SECONDS, not a disconnected
 * guess.
 */
export function pollJobLog(
  projectSlug: string,
  jobId: string,
  onUpdate: (result: JobResult, timedOut?: boolean) => void,
  { intervalMs = 15000, timeoutSeconds = 3600 }: { intervalMs?: number; timeoutSeconds?: number } = {},
): () => void {
  let cancelled = false;
  let attempts = 0;
  let lastResult: JobResult = EMPTY_RESULT;
  const maxAttempts = Math.ceil(((timeoutSeconds + POLL_GRACE_SECONDS) * 1000) / intervalMs);

  async function tick() {
    if (cancelled) return;
    attempts += 1;
    try {
      const result = await fetchJobLog(projectSlug, jobId);
      if (cancelled) return;
      lastResult = result;
      onUpdate(result);
      if (result.jobCompleted) return; // done - the Accelerator's own authoritative signal
    } catch {
      // Transient fetch error - keep polling rather than giving up.
    }
    if (attempts < maxAttempts) {
      setTimeout(tick, intervalMs);
    } else if (!cancelled) {
      onUpdate(lastResult, true);
    }
  }

  tick();
  return () => {
    cancelled = true;
  };
}
