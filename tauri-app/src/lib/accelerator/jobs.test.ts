import { describe, expect, it } from "vitest";
import { buildCommand, buildDispatchPayload, shellDoubleQuote, DEFAULT_TIMEOUT_SECONDS } from "./jobs";

describe("shellDoubleQuote", () => {
  it("escapes backslash and double-quote, in that order (so added escaping backslashes aren't re-escaped)", () => {
    expect(shellDoubleQuote(String.raw`a\b"c`)).toBe(String.raw`"a\\b\"c"`);
  });

  it("leaves real newline characters untouched", () => {
    // Regression test: JSON.stringify escapes a real newline as the
    // two-character sequence \n, which neither a real shell's -c nor
    // Python's shlex.split decodes back into an actual newline inside a
    // double-quoted string - this broke buildCommand's try/except block
    // (SyntaxError: unexpected character after line continuation
    // character) before shellDoubleQuote replaced JSON.stringify for the
    // outer argument-quoting. A real newline must survive as a real
    // newline, not become the two characters "\" and "n".
    const quoted = shellDoubleQuote("line1\nline2");
    expect(quoted).toBe('"line1\nline2"');
    expect(quoted).not.toContain("\\n");
    expect(quoted.split("\n")).toHaveLength(2);
  });
});

describe("buildCommand", () => {
  it("strips the project-slug prefix and resolves to /mnt/wdrv/...", () => {
    const command = buildCommand("cwatm-gui-dev", "cwatm-gui-dev/inhale/settings.ini");
    expect(command).toContain("/mnt/wdrv/inhale/settings.ini");
    expect(command).not.toContain("/mnt/wdrv/cwatm-gui-dev/");
  });

  it("resolves a path without the project-slug prefix the same way", () => {
    const command = buildCommand("cwatm-gui-dev", "/inhale/settings.ini");
    expect(command).toContain("/mnt/wdrv/inhale/settings.ini");
  });

  it("patches PathOut to /mnt/output and wraps execution in a try/except that reports failure", () => {
    const command = buildCommand("cwatm-gui-dev", "cwatm-gui-dev/inhale/settings.ini");
    // The embedded Python source has its own double-quotes backslash-escaped
    // for the outer shell argument (see shellDoubleQuote) - match loosely
    // enough to not be brittle to that escaping style.
    expect(command).toContain("output_dir =");
    expect(command).toContain("/mnt/output");
    expect(command).toContain("try:");
    expect(command).toContain("except SystemExit:");
    expect(command).toContain("except BaseException:");
    expect(command).toContain("@@CWATM_GUI:RESULT:False:None@@");
    expect(command).toContain("runpy.run_path");
    expect(command).toContain("cwatm_model.py");
    expect(command).toContain('run_name=');
  });

  it("is a single python -c invocation whose script contains real newlines, not escaped \\n sequences", () => {
    // The actual regression this guards: a prior version used
    // JSON.stringify for the whole quoted argument, which produced a
    // syntactically invalid script (see shellDoubleQuote's tests above).
    const command = buildCommand("cwatm-gui-dev", "cwatm-gui-dev/inhale/settings.ini");
    expect(command.startsWith("python -c ")).toBe(true);
    const quotedScript = command.slice("python -c ".length);
    expect(quotedScript.startsWith('"')).toBe(true);
    expect(quotedScript.endsWith('"')).toBe(true);
    // A real newline must appear between "try:" and its body - if it had
    // been corrupted back into "\n" (backslash + n), this won't match.
    expect(quotedScript).toMatch(/try:\n {4}orig_path/);
  });
});

describe("buildDispatchPayload", () => {
  it("fills in the required WKUBE fields with their documented defaults", () => {
    const payload = buildDispatchPayload("cwatm-gui-dev", {
      name: "CWatM: test.ini",
      settingsPath: "cwatm-gui-dev/test.ini",
    });
    expect(payload.execute_cluster).toBe("WKUBE");
    expect(payload.job_kwargs.repo_url).toBe("https://github.com/iiasa/CWatM_GUI");
    expect(payload.job_kwargs.repo_branch).toBe("cwatm-docker-image");
    expect(payload.job_kwargs.docker_filename).toBe("Dockerfile");
    expect(payload.required_cores).toBe(1);
    expect(payload.required_ram).toBe(2);
    expect(payload.required_storage_local).toBe(5);
    expect(payload.required_storage_workflow).toBe(5);
    expect(payload.timeout).toBe(DEFAULT_TIMEOUT_SECONDS);
  });

  it("lets every default be overridden", () => {
    const payload = buildDispatchPayload("cwatm-gui-dev", {
      name: "CWatM: test.ini",
      settingsPath: "cwatm-gui-dev/test.ini",
      requiredCores: 4,
      requiredRam: 16,
      requiredStorageLocal: 50,
      requiredStorageWorkflow: 50,
      timeoutSeconds: 7200,
    });
    expect(payload.required_cores).toBe(4);
    expect(payload.required_ram).toBe(16);
    expect(payload.required_storage_local).toBe(50);
    expect(payload.required_storage_workflow).toBe(50);
    expect(payload.timeout).toBe(7200);
  });

  it("builds job_kwargs.command from the given settingsPath", () => {
    const payload = buildDispatchPayload("cwatm-gui-dev", {
      name: "CWatM: test.ini",
      settingsPath: "cwatm-gui-dev/inhale/test.ini",
    });
    expect(payload.job_kwargs.command).toContain("/mnt/wdrv/inhale/test.ini");
  });
});
