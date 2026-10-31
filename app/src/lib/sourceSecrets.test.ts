import { describe, expect, it } from "vitest";
import { secretStatus } from "./sourceSecrets";

const NOW = new Date("2026-10-31T12:00:00Z").getTime();

describe("secretStatus", () => {
  it("says a missing secret is missing, with no date", () => {
    expect(secretStatus({ isSet: false, updatedAt: null }, NOW)).toBe("חסר");
  });
  it("says how long ago a set secret changed", () => {
    expect(secretStatus({ isSet: true, updatedAt: "2026-10-31T08:00:00Z" }, NOW)).toBe("מוגדר · עודכן היום");
    expect(secretStatus({ isSet: true, updatedAt: "2026-10-30T08:00:00Z" }, NOW)).toBe("מוגדר · עודכן אתמול");
    expect(secretStatus({ isSet: true, updatedAt: "2026-10-01T08:00:00Z" }, NOW)).toBe("מוגדר · עודכן לפני 30 ימים");
  });
  it("still says set when the vault gave no time", () => {
    expect(secretStatus({ isSet: true, updatedAt: null }, NOW)).toBe("מוגדר");
  });
});
