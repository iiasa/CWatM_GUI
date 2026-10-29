import { describe, expect, it } from "vitest";
import { wdrvPathToProjectPath } from "./outputs";

describe("wdrvPathToProjectPath", () => {
  it("strips /mnt/wdrv and prefixes the project slug", () => {
    expect(wdrvPathToProjectPath("cwatm-gui-dev", "/mnt/wdrv/output/run-123-456")).toBe(
      "cwatm-gui-dev/output/run-123-456",
    );
  });

  it("handles a trailing slash on /mnt/wdrv/ itself", () => {
    expect(wdrvPathToProjectPath("cwatm-gui-dev", "/mnt/wdrv/")).toBe("cwatm-gui-dev");
  });
});
