/**
 * Dispatching a CWatM run as an Accelerator "WKube" job.
 *
 * The payload shape (JobDispatchModel / WKubeTaskKwargs) and the dispatch
 * call itself (POST {aterm-cli}/{project_slug}/jobs/dispatch/, body =
 * the dispatch model as JSON, same x-authorization auth as file browsing)
 * were read directly from IIASA's accli reference client
 * (AcceleratorTaskDispatcher.py / AcceleratorTerminalCliProjectService.py),
 * then corrected against the server's own validation errors from a real
 * live dispatch (job_id 15411, successful): several fields the pydantic
 * model marks Optional are actually required once execute_cluster is
 * "WKUBE" - timeout, required_storage_workflow, and (when not using
 * base_stack) docker_filename must be explicit, not left to an implicit
 * "Dockerfile at repo root" default.
 *
 * Per the Accelerator team: give them a public GitHub repo + branch and a
 * Dockerfile at its root (repo_url/repo_branch/docker_filename below) and
 * they build the image automatically on first dispatch, caching it until
 * the repo's content actually changes (force_build overrides that). No
 * separate registration step - this is the whole mechanism.
 *
 * Job status/log checking is NOT available via aterm-cli yet as a proper
 * endpoint (confirmed live during the Milestone 1 auth investigation, and
 * again directly against the live OpenAPI spec - aterm-cli's only job-
 * related paths are jobs/dispatch/ and jobstore-push-url/) - so this
 * module only dispatches. See jobStatus.ts for the workaround (polling the
 * job's own uploaded log file).
 */

import { ATERM_BASE } from "./config";
import { atermFetch } from "./atermFetch";

/** Where the CWatM execution image is built from - see Dockerfile at the repo root. */
const CWATM_IMAGE_SOURCE = {
  repo_url: "https://github.com/iiasa/CWatM_GUI",
  repo_branch: "cwatm-docker-image",
  docker_filename: "Dockerfile",
} as const;

export interface DispatchCwatmRunOptions {
  /** A human-readable name for this job. */
  name: string;
  /**
   * The settings file's full path exactly as returned by listFiles/
   * FileEntry.path - i.e. still prefixed with the project slug (e.g.
   * "cwatm-gui-dev/inhale/settings_CWatM_Danube_30min.ini"). That prefix
   * is stripped below: /mnt/wdrv is the project's own mounted root inside
   * a running job (confirmed live by the Accelerator team), not a parent
   * of several projects, so it does not repeat the slug.
   */
  settingsPath: string;
  /** Cores/RAM(GB)/local+workflow storage(GB)/timeout(s) - all required by the server for execute_cluster WKUBE, confirmed live. Defaults are a modest guess for a single-catchment CWatM run, not tuned against a real one yet. */
  requiredCores?: number;
  requiredRam?: number;
  requiredStorageLocal?: number;
  requiredStorageWorkflow?: number;
  timeoutSeconds?: number;
}

const DEFAULT_REQUIRED_CORES = 1;
const DEFAULT_REQUIRED_RAM_GB = 2;
const DEFAULT_REQUIRED_STORAGE_GB = 5;
/** Exported so jobStatus.ts's polling can size its own timeout against whatever this dispatch actually used. */
export const DEFAULT_TIMEOUT_SECONDS = 3600;

/**
 * Builds the job's command as a single `python -c "<script>"` invocation -
 * deliberately not `mkdir -p ... && python cwatm_model.py ...`, because
 * whether the Accelerator's build server executes job_kwargs.command via a
 * shell or splits it some other way (e.g. shlex) isn't documented or
 * confirmed live, and `&&` only works under the former. A single `python -c`
 * call needs neither: it's the same two-argument-beyond-"python" shape as
 * the already-proven `python cwatm_model.py "<path>"` command.
 *
 * Each run needs its own PathOut: reusing one fixed output directory across
 * runs breaks on the second run (confirmed live, job 15415 - CWatM got all
 * the way to writing output netCDFs, then PermissionError: [Errno 13]
 * Permission denied writing into a directory an earlier job's process had
 * already created and apparently "owns" - the job-outputs upload step's own
 * logs show each job running under its own uid/gid, e.g.
 * JOB_GID="273297" process uid=65534 gid=273297). CWatM itself has no
 * command-line override for PathOut and no environment-variable
 * substitution in its config parser (checked cwatm/run_cwatm.py's usage()
 * and management_modules/configuration.py), so the only way to change it is
 * to change the settings file's own text.
 *
 * This used to be done by having the CLIENT download, patch, and re-upload
 * a per-run settings copy before dispatch - abandoned (see git history)
 * after live testing showed that path: the Accelerator's real project file
 * index/FUSE mount is built on a separate content-addressable upload
 * protocol (Xet - huggingface/xet-core - used internally for the
 * job-outputs log uploads we already read), not the S3-multipart endpoints
 * that exist in accli's client code but turned out to be dead/unused there
 * (the Accelerator team confirmed live, 2026-10-28: the multipart uploader
 * is deprecated and on their backlog to remove) - an upload against those
 * "succeeds" (real object, real id) without ever becoming visible to
 * node-items or a job's own /mnt/wdrv mount. Reimplementing Xet's wire
 * protocol in TypeScript is real scope, not attempted (the team offered
 * help if real upload support is wanted later).
 *
 * Instead, the DISPATCHED JOB does this patching itself: it already has
 * full read access to the original (already correctly uploaded by the
 * user) settings file. Where it writes its own output went through two
 * iterations:
 *
 * 1. /mnt/output - the Accelerator team confirmed live (2026-10-28) that
 *    this path always maps to a fresh, job-ID-scoped directory
 *    automatically, that per-job write isolation there is intentional and
 *    guaranteed ("that won't change" - their words). In practice this
 *    broke live too (job 15561, 2026-10-29): PermissionError writing
 *    /mnt/output/settings_run.ini, before CWatM even started.
 * 2. Back to a job-unique directory under /mnt/wdrv/output/ (what an
 *    even earlier version of this function already did, before the
 *    /mnt/output shortcut was adopted) - this time informed by what that
 *    same job 15561's own build log showed about how output upload
 *    actually works: a step literally named
 *    `UploadWdrvFilesCreatedByJobGid` scans /mnt/wdrv (not /mnt/output)
 *    for files tagged with the job's own JOB_GID and uploads exactly
 *    those - /mnt/wdrv's own per-job write-overlay tracking file
 *    (`.hf_overlay_writes`) confirms the mount expects exactly this. The
 *    original problem with writing under /mnt/wdrv/output/ (job 15415,
 *    see git history) was a *fixed* directory name colliding with an
 *    earlier job's leftover, now owned by a different uid/gid - solved
 *    here the same way as before, by making the directory name unique
 *    per run (process id + unix time), not by avoiding /mnt/wdrv itself.
 *
 * Since that directory name is generated INSIDE the container at
 * runtime, the client can't predict it ahead of dispatch - so the script
 * prints it to stdout as its own `@@CWATM_GUI:OUTPUT_DIR:<path>@@`
 * marker (same technique as cwatm_model_runner.py's own RESULT marker),
 * which jobStatus.ts reads back out of the job's uploaded log once the
 * run finishes.
 *
 * The script reads the original settings file, rewrites its PathOut line
 * to that directory, creates it, writes the patched settings there too
 * (so it rides along with that run's uploaded outputs, handy for later
 * debugging which variant actually ran), and runs cwatm_model.py against
 * the patched copy via runpy (run_name "__main__", so its own entry
 * point fires exactly as a normal invocation would).
 */
export function buildCommand(projectSlug: string, settingsPath: string): string {
  const relativePath = settingsPath.startsWith(`${projectSlug}/`)
    ? settingsPath.slice(projectSlug.length + 1)
    : settingsPath.replace(/^\/+/, "");
  const absoluteSettingsPath = `/mnt/wdrv/${relativePath}`;
  // Wrapped in try/except so OUR OWN pre-processing (reading/patching the
  // settings file, before cwatm_model.py is even reached) reports failure
  // through the exact same @@CWATM_GUI:RESULT:...@@ marker protocol
  // cwatm_model_runner.py itself uses (see its _emit/MARKER constants) -
  // without this, a failure here (bad path, no "PathOut = ..." line, a
  // disk error) would be a raw unhandled exception that jobStatus.ts's
  // marker-parsing never finds, leaving the in-app status stuck on
  // "running" forever instead of showing a failure. cwatm_model_runner.py
  // itself always calls sys.exit(0 or 1) on its own completion (success or
  // a failure it already caught and reported) - that raises SystemExit,
  // which must pass through untouched here (its own correct marker was
  // already printed), so only non-SystemExit exceptions get our fallback.
  const script = [
    "import os, sys, re, runpy, time, traceback",
    "try:",
    `    orig_path = ${JSON.stringify(absoluteSettingsPath)}`,
    "    content = open(orig_path).read()",
    '    output_dir = f"/mnt/wdrv/output/run-{os.getpid()}-{int(time.time())}"',
    '    print(f"@@CWATM_GUI:OUTPUT_DIR:{output_dir}@@")',
    "    os.makedirs(output_dir, exist_ok=True)",
    '    patched = re.sub(r"(?m)^PathOut\\s*=.*$", f"PathOut = {output_dir}", content, count=1)',
    "    assert patched != content, 'No \"PathOut = ...\" line found to patch in ' + orig_path",
    '    patched_path = output_dir + "/settings_run.ini"',
    "    open(patched_path, 'w').write(patched)",
    '    sys.argv = ["cwatm_model.py", patched_path]',
    '    runpy.run_path("cwatm_model.py", run_name="__main__")',
    "except SystemExit:",
    "    raise",
    "except BaseException:",
    "    traceback.print_exc()",
    '    print("@@CWATM_GUI:RESULT:False:None@@")',
    "    sys.exit(1)",
  ].join("\n");
  return `python -c ${shellDoubleQuote(script)}`;
}

/**
 * Wraps `s` in double quotes for embedding as one shell/exec-array
 * argument - escapes only backslash and `"`, same as POSIX double-quote
 * rules. Deliberately NOT `JSON.stringify`: JSON escapes a real newline
 * character as the two-character sequence `\n`, which neither a real
 * shell's `-c` nor Python's own `shlex.split` (both confirmed live, this
 * command's earlier single-line form) decode back into an actual newline
 * inside a double-quoted string - they just leave a literal backslash
 * followed by "n", which is invalid Python syntax wherever that lands
 * mid-statement. A literal (unescaped) newline byte, by contrast, is valid
 * and preserved as-is by both parsers - exactly what multi-line Python
 * source (here, a try/except block) needs.
 */
export function shellDoubleQuote(s: string): string {
  return '"' + s.replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"';
}

/**
 * The full WKube dispatch payload for a CWatM run - exactly the shape
 * accli's own WKubeTask/JobDispatchModel pydantic models produce.
 * Exported (not just used internally) so it can be inspected/logged
 * before dispatching, while this is still new and worth double-checking.
 */
export function buildDispatchPayload(projectSlug: string, options: DispatchCwatmRunOptions) {
  return {
    is_holder_job: false,
    build_only_task: false,
    name: options.name,
    execute_cluster: "WKUBE",
    job_location: "acc_native_jobs.dispatch_wkube_task",
    job_args: [],
    job_kwargs: {
      ...CWATM_IMAGE_SOURCE,
      command: buildCommand(projectSlug, options.settingsPath),
    },
    required_cores: options.requiredCores ?? DEFAULT_REQUIRED_CORES,
    required_ram: options.requiredRam ?? DEFAULT_REQUIRED_RAM_GB,
    required_storage_local: options.requiredStorageLocal ?? DEFAULT_REQUIRED_STORAGE_GB,
    required_storage_workflow: options.requiredStorageWorkflow ?? DEFAULT_REQUIRED_STORAGE_GB,
    job_secrets: {},
    timeout: options.timeoutSeconds ?? DEFAULT_TIMEOUT_SECONDS,
    ignore_duplicate_job: false,
    free_node: false,
    children: [],
  };
}

export interface DispatchedJob {
  jobId: string;
  /** The timeout actually used for this dispatch - pass to jobStatus.ts's pollJobLog so its own give-up point matches, rather than guessing. */
  timeoutSeconds: number;
}

/** Dispatches a CWatM run; returns the Accelerator job id and the timeout actually used. */
export async function dispatchCwatmRun(projectSlug: string, options: DispatchCwatmRunOptions): Promise<DispatchedJob> {
  const timeoutSeconds = options.timeoutSeconds ?? DEFAULT_TIMEOUT_SECONDS;
  const res = await atermFetch(`${ATERM_BASE}/${projectSlug}/jobs/dispatch/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildDispatchPayload(projectSlug, { ...options, timeoutSeconds })),
  });
  const data = await res.json();
  return { jobId: data.job_id, timeoutSeconds };
}
