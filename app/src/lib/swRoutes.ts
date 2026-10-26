// Pure request/response rules shared by the service worker (src/sw.ts) and its tests.
// Kept free of `self`/`caches` so they run under vitest.

/** Paths the worker must never touch: live editing and the auth handshake. */
const BYPASS = ["/api", "/_callback", "/_passkey"];
/** Observed (to wipe cached financial JSON) but never answered by the worker. */
const LOGOUT = "/_logout";

export type RouteKind = "bypass" | "logout" | "navigation" | "data" | "other";

export interface RequestInfo {
  url: string;
  method: string;
  /** `Request.mode`; "navigate" for page loads. */
  mode: string;
  /** The worker's own origin. */
  origin: string;
}

const underPath = (pathname: string, base: string) => pathname === base || pathname.startsWith(`${base}/`);

/**
 * What the worker does with a request:
 * - bypass: `/api/*`, `/_callback`, `/_passkey`, cross-origin and non-GET are left to the network
 * - logout: `/_logout` passes through but clears the cached data on the way
 * - navigation: network-first, cached shell only on a network error
 * - data: `/data/*.json`, network-first with a timeout and a JSON-only cache
 * - other: precached assets (handled by workbox) or plain network
 */
export function classifyRequest({ url, method, mode, origin }: RequestInfo): RouteKind {
  const u = new URL(url);
  if (u.origin !== origin) return "bypass";
  if (u.pathname === LOGOUT) return "logout";
  if (BYPASS.some((p) => underPath(u.pathname, p))) return "bypass";
  if (method !== "GET") return "bypass";
  if (mode === "navigate") return "navigation";
  if (u.pathname.startsWith("/data/") && u.pathname.endsWith(".json")) return "data";
  return "other";
}

export interface ResponseInfo {
  status: number;
  /** `Response.redirected` */
  redirected: boolean;
  /** `Response.type` */
  type: string;
  contentType: string | null;
}

/**
 * Only a clean 200 JSON from our own origin may enter the data cache. An expired session
 * comes back as an opaque redirect or the login/SPA HTML, and caching that would poison the
 * offline copy. A followed same-origin redirect that ends in JSON is the edge renewing the
 * session, so `redirected` alone does not disqualify it.
 */
export function isCacheableData(r: ResponseInfo): boolean {
  return r.status === 200 && r.type === "basic" && /json/i.test(r.contentType ?? "");
}

/** Request header for a /data fetch that must skip the cached copy (app refresh after boot). */
export const FRESH_HEADER = "x-sw-fresh";

/** Network wait before `/data/*.json` falls back to the cached copy. */
export const DATA_TIMEOUT_MS = 4000;
