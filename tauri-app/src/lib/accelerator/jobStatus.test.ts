import { describe, expect, it } from "vitest";
import { parseJobLog } from "./jobStatus";

describe("parseJobLog", () => {
  it("returns success: null when no result marker is present yet (job still running)", () => {
    const log = "Waiting for FUSE mount on /mnt/wdrv to become ready...\nFUSE mount /mnt/wdrv is ready\n";
    expect(parseJobLog(log)).toEqual({ success: null });
  });

  it("parses a successful run's marker (real shape from job 15422)", () => {
    const log = [
      "58      27/02/2015 1061463.51",
      "@@CWATM_GUI:PROGRESS:98@@",
      "59      28/02/2015 1245047.60",
      "@@CWATM_GUI:RESULT:True:1245047.6002230425@@",
      "Resource Usage Report:",
    ].join("\n");
    const result = parseJobLog(log);
    expect(result.success).toBe(true);
    expect(result.lastDischarge).toBeCloseTo(1245047.6002230425);
    expect(result.errorSummary).toBeUndefined();
  });

  it("parses a failed run's marker and its CWATM FILE ERROR block (real shape from job 15416)", () => {
    const log = [
      "CWATM - Community Water Model Version: develop 5c6a663 not checked , Date: 2026-07-14",
      "",
      " ========================= CWATM FILE ERROR =========================",
      "",
      "Error 215: Cannot find precipitation maps",
      'In setting: "PrecipitationMaps"',
      'searching: "/mnt/wdrv/CWatM-Earth-30min/Danube_climate/Precipitation*"',
      "",
      "",
      "@@CWATM_GUI:RESULT:False:0.0@@",
      "command execution error: exit status 1",
    ].join("\n");
    const result = parseJobLog(log);
    expect(result.success).toBe(false);
    expect(result.lastDischarge).toBe(0);
    expect(result.errorSummary).toContain("Error 215: Cannot find precipitation maps");
    expect(result.errorSummary).toContain("PrecipitationMaps");
  });

  it("parses a failure with last_dis None (every failure we've seen live has this shape - bad settings path, Error 215/220, our own pre-processing fallback)", () => {
    const log = "Traceback (most recent call last):\n...\n@@CWATM_GUI:RESULT:False:None@@\n";
    const result = parseJobLog(log);
    expect(result.success).toBe(false);
    expect(result.lastDischarge).toBeUndefined();
  });

  it("does not set errorSummary when the run succeeded, even if an unrelated FILE ERROR-shaped block is present", () => {
    const log = [
      "===== CWATM FILE ERROR =====",
      "some unrelated warning text",
      "",
      "@@CWATM_GUI:RESULT:True:5.0@@",
    ].join("\n");
    const result = parseJobLog(log);
    expect(result.success).toBe(true);
    expect(result.errorSummary).toBeUndefined();
  });
});
