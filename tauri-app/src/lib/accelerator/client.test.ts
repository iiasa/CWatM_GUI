import { describe, expect, it } from "vitest";
import { basename } from "./client";

describe("basename", () => {
  it("returns the last path segment", () => {
    expect(basename("cwatm-gui-dev/inhale/settings.ini")).toBe("settings.ini");
  });

  it("returns the whole string for a path with no slash", () => {
    expect(basename("settings.ini")).toBe("settings.ini");
  });

  it("ignores a trailing slash (a folder entry's own path)", () => {
    expect(basename("cwatm-gui-dev/inhale/")).toBe("inhale");
  });
});
