import { describe, it, expect } from "vitest";
import { fmt, toTime } from "./dates";

describe("fmt", () => {
  const formatter = new Intl.DateTimeFormat("he-IL", { day: "numeric", month: "short" });

  it("formats valid ISO date", () => {
    const result = fmt(formatter, "2026-10-16T07:31:05+03:00");
    expect(result).toBeTruthy();
    expect(result).toMatch(/\d+/);
  });

  it("formats valid ISO date with Z", () => {
    const result = fmt(formatter, "2026-10-16T07:31:05Z");
    expect(result).toBeTruthy();
  });

  it("returns null for undefined", () => {
    expect(fmt(formatter, undefined)).toBeNull();
  });

  it("returns null for null", () => {
    expect(fmt(formatter, null)).toBeNull();
  });

  it("returns null for empty string", () => {
    expect(fmt(formatter, "")).toBeNull();
  });

  it("returns null for garbage string", () => {
    expect(fmt(formatter, "not a date")).toBeNull();
  });

  it("never throws on any input", () => {
    expect(() => fmt(formatter, undefined)).not.toThrow();
    expect(() => fmt(formatter, null)).not.toThrow();
    expect(() => fmt(formatter, "garbage")).not.toThrow();
    expect(() => fmt(formatter, "2026-13-45T99:99:99Z")).not.toThrow();
  });
});

describe("toTime", () => {
  it("parses valid ISO date to milliseconds", () => {
    const result = toTime("2026-10-16T07:31:05+03:00");
    expect(result).toBeGreaterThan(0);
  });

  it("returns 0 for undefined", () => {
    expect(toTime(undefined)).toBe(0);
  });

  it("returns 0 for null", () => {
    expect(toTime(null)).toBe(0);
  });

  it("returns 0 for empty string", () => {
    expect(toTime("")).toBe(0);
  });

  it("returns 0 for garbage string", () => {
    expect(toTime("not a date")).toBe(0);
  });

  it("never throws and never returns NaN", () => {
    expect(() => toTime(undefined)).not.toThrow();
    expect(() => toTime("garbage")).not.toThrow();
    expect(Math.max(0, toTime(undefined), toTime(null))).toBe(0);
    expect(isNaN(toTime(undefined))).toBe(false);
  });

  it("handles real sync-status entry with missing started_at", () => {
    // Real entry that crashed the app
    const entry = {
      status: "done",
      message: "x",
      updated_at: "2026-10-16T07:31:05+03:00",
      last_success_at: "2026-10-16T07:31:05+03:00",
      started_at: undefined,
    };
    expect(() => toTime(entry.started_at)).not.toThrow();
    expect(toTime(entry.started_at)).toBe(0);
  });
});
