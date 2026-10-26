import { describe, expect, it } from "vitest";
import { RESUME_REFRESH_MS, isExpiredNetworkError, isSessionExpired, shouldRefreshOnResume } from "./dataFetch";

describe("shouldRefreshOnResume", () => {
  const t0 = 1_000_000;
  it("skips a refresh when the data is fresh", () => {
    expect(shouldRefreshOnResume(t0, t0 + 30_000)).toBe(false);
    expect(shouldRefreshOnResume(t0, t0 + RESUME_REFRESH_MS)).toBe(false);
  });
  it("refreshes once the data is older than two minutes", () => {
    expect(shouldRefreshOnResume(t0, t0 + RESUME_REFRESH_MS + 1)).toBe(true);
  });
});

describe("isSessionExpired", () => {
  const ok = { status: 200, redirected: false, type: "basic" };
  it("treats a clean response as a live session", () => expect(isSessionExpired(ok)).toBe(false));
  it("treats 401/403 and redirects as an expired login", () => {
    expect(isSessionExpired({ ...ok, status: 401 })).toBe(true);
    expect(isSessionExpired({ ...ok, status: 403 })).toBe(true);
    expect(isSessionExpired({ ...ok, redirected: true })).toBe(true);
    expect(isSessionExpired({ status: 0, redirected: false, type: "opaqueredirect" })).toBe(true);
  });
  it("does not blame the session for a missing key (SPA shell on 200, or a plain 404)", () => {
    expect(isSessionExpired({ ...ok, status: 404 })).toBe(false);
  });
});

describe("isExpiredNetworkError", () => {
  it("is an expired session only when the browser thinks it is online", () => {
    expect(isExpiredNetworkError(new TypeError("Failed to fetch"), true)).toBe(true);
    expect(isExpiredNetworkError(new TypeError("Failed to fetch"), false)).toBe(false);
    expect(isExpiredNetworkError(new Error("boom"), true)).toBe(false);
  });
});
