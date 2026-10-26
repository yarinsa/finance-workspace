// Pure helpers for lib/data.ts so they can be tested without its top-level await.

/** Thrown when a data fetch shows the auth cookie lapsed (redirect/HTML/401 instead of JSON). */
export class SessionExpiredError extends Error {
  constructor() {
    super("החיבור פג — התחבר מחדש");
    this.name = "SessionExpiredError";
  }
}

export interface FetchedInfo {
  status: number;
  redirected: boolean;
  type: string;
}

/**
 * True when a response to /data/<name>.json means "log in again": a 401/403 or a redirect
 * (the edge bounces an unauthenticated page request to Cognito). HTML on a 200 is NOT this:
 * with a valid session CloudFront maps a missing S3 key to the SPA shell, so that stays the
 * "file not published" error.
 */
export function isSessionExpired(r: Pick<FetchedInfo, "status" | "redirected" | "type">): boolean {
  return r.status === 401 || r.status === 403 || r.redirected || r.type === "opaqueredirect";
}

/**
 * A fetch that throws while the browser believes it is online is most likely the cross-origin
 * hop to the Cognito login being blocked by CORS, i.e. an expired session. Offline throws are
 * just offline.
 */
export function isExpiredNetworkError(err: unknown, online: boolean): boolean {
  return online && err instanceof TypeError;
}

/** Throttle for "refresh when the app comes back to the foreground". */
export const RESUME_REFRESH_MS = 2 * 60_000;

/** Whether data last fetched at `lastFetchedAt` is old enough to re-fetch on resume. */
export function shouldRefreshOnResume(lastFetchedAt: number, now: number, minAgeMs = RESUME_REFRESH_MS): boolean {
  return now - lastFetchedAt > minAgeMs;
}
