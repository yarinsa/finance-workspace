import { describe, expect, it } from "vitest";
import { classifyRequest, isCacheableData } from "./swRoutes";

const origin = "https://my-finance.yarinsa.me";
const get = (path: string, mode = "cors") => classifyRequest({ url: origin + path, method: "GET", mode, origin });

describe("classifyRequest", () => {
  it("never touches the API or the auth handshake", () => {
    expect(get("/api/health")).toBe("bypass");
    expect(get("/api/transactions?excluded=only")).toBe("bypass");
    expect(get("/_callback")).toBe("bypass");
    expect(get("/_passkey/register")).toBe("bypass");
    // A navigation to an auth path must not be answered with the cached shell either.
    expect(get("/_callback", "navigate")).toBe("bypass");
  });

  it("only observes logout so the data cache can be wiped", () => {
    expect(get("/_logout", "navigate")).toBe("logout");
  });

  it("does not mistake look-alike paths for the API", () => {
    expect(get("/apiary")).toBe("other");
    expect(get("/monthly", "navigate")).toBe("navigation");
  });

  it("leaves writes and cross-origin requests alone", () => {
    expect(classifyRequest({ url: `${origin}/data/cashflow.json`, method: "POST", mode: "cors", origin })).toBe("bypass");
    expect(classifyRequest({ url: "https://auth.example.test/login", method: "GET", mode: "navigate", origin })).toBe("bypass");
  });

  it("routes the digested JSON to the data strategy", () => {
    expect(get("/data/cashflow.json")).toBe("data");
    expect(get("/data/cashflow.json?x=1")).toBe("data");
    expect(get("/data/notes.txt")).toBe("other");
  });

  it("leaves hashed assets to the precache", () => {
    expect(get("/assets/index-abc123.js")).toBe("other");
  });
});

describe("isCacheableData", () => {
  const ok = { status: 200, redirected: false, type: "basic", contentType: "application/json; charset=utf-8" };
  it("accepts a clean JSON 200", () => expect(isCacheableData(ok)).toBe(true));
  it("rejects the SPA/login HTML that an expired session or missing key returns", () => {
    expect(isCacheableData({ ...ok, contentType: "text/html; charset=utf-8" })).toBe(false);
    expect(isCacheableData({ ...ok, contentType: null })).toBe(false);
  });
  it("caches the JSON at the end of the edge's session-renewal redirect", () => {
    expect(isCacheableData({ ...ok, redirected: true })).toBe(true);
  });

  it("rejects HTML redirects, errors and opaque responses", () => {
    expect(isCacheableData({ ...ok, redirected: true, contentType: "text/html" })).toBe(false);
    expect(isCacheableData({ ...ok, status: 401 })).toBe(false);
    expect(isCacheableData({ ...ok, status: 304 })).toBe(false);
    expect(isCacheableData({ ...ok, type: "opaqueredirect", status: 0 })).toBe(false);
  });
});
