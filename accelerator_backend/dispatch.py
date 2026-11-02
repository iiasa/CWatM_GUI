"""Writes a file into an Accelerator project by dispatching a tiny job -
there is no confirmed working direct-upload API into a project (the
S3-multipart endpoints in accli's reference client are dead/deprecated,
confirmed by the Accelerator team live, 2026-10-28), so the only
confirmed way a new file lands in a project from outside it is a
dispatched job writing to /mnt/wdrv, which Accelerator's own
infrastructure then auto-uploads once the job finishes - the same
mechanism the Tauri client's jobs.ts already proved live for CWatM's own
output files. This module ports that same shape (buildCommand /
buildDispatchPayload / dispatchCwatmRun), generalized from "run CWatM"
to "write this content to this path".

Reuses the already-proven CWatM execution image (iiasa/CWatM_GUI,
cwatm-docker-image branch) rather than building a separate minimal image
for this - writing a file needs no CWatM-specific dependency, and this
image is already known to work.
"""

import json

import config
import service_account

CWATM_IMAGE_SOURCE = {
    "repo_url": "https://github.com/iiasa/CWatM_GUI",
    "repo_branch": "cwatm-docker-image",
    "docker_filename": "Dockerfile",
}

DEFAULT_REQUIRED_CORES = 1
DEFAULT_REQUIRED_RAM_GB = 1
DEFAULT_REQUIRED_STORAGE_GB = 1
# A file write needs seconds, not the hour a CWatM run is given.
DEFAULT_TIMEOUT_SECONDS = 300

_REQUEST_TIMEOUT_SECONDS = 30


def shell_double_quote(s):
    """Wraps `s` in double quotes for embedding as one shell/exec-array
    argument - escapes only backslash and ", same as POSIX double-quote
    rules and jobs.ts's own shellDoubleQuote. Deliberately NOT json.dumps
    for this outer wrap: json.dumps would escape a real newline as the
    two-character sequence \\n, which neither a real shell's -c nor
    Python's own shlex.split decode back into an actual newline - a
    lesson jobs.ts already learned live, applied here before it needs
    re-learning. (json.dumps IS used below, correctly, for a different
    layer - see build_write_command.)"""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_write_command(relative_path, content):
    """The job's command: write `content` (text) to
    `/mnt/wdrv/<relative_path>`, creating parent directories as needed.

    `content` is embedded via json.dumps - correct here because this
    layer is a Python string LITERAL inside the generated script's own
    source, which Python's own parser decodes at run time (its \\n means
    a real newline once the script executes) - not the outer shell-
    argument layer shell_double_quote handles, where the same escaping
    would be wrong (see that function's own doc comment). The two layers
    compose correctly: shell_double_quote's backslash-doubling of this
    layer's own escape sequences round-trips through standard POSIX
    double-quote unescaping back to exactly the text written here.

    Wrapped in try/except so a failure (bad path, disk error) prints a
    result marker instead of being a raw unhandled exception - same
    pattern as jobs.ts's buildCommand for CWatM runs."""
    path = "/mnt/wdrv/" + relative_path
    script = "\n".join([
        "import os, sys, traceback",
        "try:",
        f"    path = {json.dumps(path)}",
        f"    content = {json.dumps(content)}",
        "    os.makedirs(os.path.dirname(path), exist_ok=True)",
        "    with open(path, 'w') as f:",
        "        f.write(content)",
        '    print("@@LEDGER_WRITE:True@@")',
        "except BaseException:",
        "    traceback.print_exc()",
        '    print("@@LEDGER_WRITE:False@@")',
        "    sys.exit(1)",
    ])
    return f"python -c {shell_double_quote(script)}"


def build_dispatch_payload(name, relative_path, content, timeout_seconds=None):
    """The full WKube dispatch payload - same shape as jobs.ts's
    buildDispatchPayload, minimal resources (a file write needs far less
    than a CWatM run)."""
    return {
        "is_holder_job": False,
        "build_only_task": False,
        "name": name,
        "execute_cluster": "WKUBE",
        "job_location": "acc_native_jobs.dispatch_wkube_task",
        "job_args": [],
        "job_kwargs": {
            **CWATM_IMAGE_SOURCE,
            "command": build_write_command(relative_path, content),
        },
        "required_cores": DEFAULT_REQUIRED_CORES,
        "required_ram": DEFAULT_REQUIRED_RAM_GB,
        "required_storage_local": DEFAULT_REQUIRED_STORAGE_GB,
        "required_storage_workflow": DEFAULT_REQUIRED_STORAGE_GB,
        "job_secrets": {},
        "timeout": timeout_seconds or DEFAULT_TIMEOUT_SECONDS,
        "ignore_duplicate_job": False,
        "free_node": False,
        "children": [],
    }


def dispatch_write_job(project_slug, name, relative_path, content):
    """Dispatches the write job as the validator's own service account;
    returns the Accelerator job id. Does not wait for it to finish - see
    README for what's not yet built (polling/confirming the write)."""
    import requests

    access_token = service_account.get_access_token()
    payload = build_dispatch_payload(name, relative_path, content)
    res = requests.post(
        f"{config.ATERM_BASE}/{project_slug}/jobs/dispatch/",
        json=payload,
        headers={"x-authorization": access_token},
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    if not res.ok:
        raise RuntimeError(f"Dispatch failed (HTTP {res.status_code}): {res.text}")
    return res.json()["job_id"]
