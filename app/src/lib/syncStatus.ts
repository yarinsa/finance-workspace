import { tenantQuery } from "./tenant";
import { useSyncExternalStore } from "react";
import { sourceLabel, type HomeAction } from "./data";

/**
 * Live state of the automated (Temporal) sync.
 *
 * Transport: Server-Sent Events from the Ledger API (`GET /api/sync/events`). The
 * stream sends a full `snapshot` on every connect and then one `source` event per
 * changed source, so while it is healthy nothing is polled.
 *
 * Fallback: when the Mac/API is off the stream keeps failing. After 3 errors with no
 * snapshot in between we close it and poll the published data/sync-status.json on S3
 * (fast while a run is active, slow when idle; the worker rewrites it on every status
 * change, sync/activities.py publish_status), fetching once immediately. SSE is retried
 * every 60 s while in fallback. A missing file just means "no automated sync" (null).
 *
 * A hidden tab closes the stream and stops polling; becoming visible starts over.
 */

export type SyncState =
  | "starting"
  | "checking_session"
  | "waiting_for_login"
  | "waiting_for_otp"
  | "scraping"
  | "validating"
  | "digesting"
  | "publishing"
  | "done"
  | "needs_login"
  | "rejected"
  | "failed";

export interface SourceStatus {
  status: SyncState;
  /** Short Hebrew text written by the workflow for the current step. */
  message: string;
  step: number | null;
  total_steps: number;
  workflow_id: string;
  run_id: string;
  started_at: string;
  updated_at: string;
  last_success_at: string | null;
  /** One-line root cause when status is `failed` or `rejected`. */
  error: string | null;
  /** Normalized record counts per entity after / before this run's scrape (dump gate); absent on older entries. */
  records?: Record<string, number> | null;
  records_before?: Record<string, number> | null;
  /** Newest transaction in the fresh dump. */
  latest_txn?: string | null;
  /** This run's steps in order, each with when it started; absent on older entries. */
  log?: { status: SyncState; at: string }[];
}

export interface SyncStatusDoc {
  updated_at: string;
  sources: Record<string, SourceStatus>;
}

/** States where the workflow is still moving on its own. */
const RUNNING: ReadonlySet<SyncState> = new Set(["starting", "checking_session", "scraping", "validating", "digesting", "publishing"]);
/** States that need the human (or a look at the Temporal UI). */
const ATTENTION: ReadonlySet<SyncState> = new Set(["waiting_for_login", "waiting_for_otp", "needs_login", "rejected", "failed"]);

/** Sources that log in with an SMS code typed in the app (sync/sources.py `otp`). */
export const OTP_SOURCES: ReadonlySet<string> = new Set(["harel"]);

/** A running status this old means the worker died mid-run; don't keep claiming progress. */
export const STALE_AFTER_MS = 15 * 60_000;
export const POLL_ACTIVE_MS = 5_000;
export const POLL_IDLE_MS = 60_000;

/** What the UI should show: the reported state, or `stale` if a run stopped reporting. */
export type Display = SyncState | "stale";

export function displayState(s: SourceStatus, now = Date.now()): Display {
  if (RUNNING.has(s.status) && now - new Date(s.updated_at).getTime() > STALE_AFTER_MS) return "stale";
  return s.status;
}

export const isRunning = (d: Display) => d !== "stale" && RUNNING.has(d);
export const needsAttention = (d: Display) => d !== "stale" && ATTENTION.has(d);

/** Poll fast only while some source is actually mid-run. */
export function pollInterval(doc: SyncStatusDoc | null, now = Date.now()): number {
  if (!doc) return POLL_IDLE_MS;
  // A login waiting for its code also polls fast, so the row moves on right after you submit it.
  return Object.values(doc.sources).some((s) => {
    const d = displayState(s, now);
    return isRunning(d) || d === "waiting_for_otp";
  })
    ? POLL_ACTIVE_MS
    : POLL_IDLE_MS;
}

export const STATE_PILL: Record<Display, { text: string; cls: string }> = {
  starting: { text: "מתחיל", cls: "pill-run" },
  checking_session: { text: "בודק חיבור", cls: "pill-run" },
  scraping: { text: "מוריד נתונים", cls: "pill-run" },
  validating: { text: "בודק נתונים", cls: "pill-run" },
  digesting: { text: "מעבד", cls: "pill-run" },
  publishing: { text: "מפרסם", cls: "pill-run" },
  waiting_for_login: { text: "ממתין להתחברות", cls: "pill-warn" },
  waiting_for_otp: { text: "ממתין לקוד", cls: "pill-warn" },
  needs_login: { text: "נדרשת התחברות", cls: "pill-bad" },
  rejected: { text: "הנתונים נדחו", cls: "pill-bad" },
  failed: { text: "נכשל", cls: "pill-bad" },
  done: { text: "הושלם", cls: "pill-good" },
  stale: { text: "לא ידוע", cls: "pill-muted" },
};

/** Worst state across sources, for the header dot: attention > running > nothing. */
export function headline(doc: SyncStatusDoc | null, now = Date.now()): "attention" | "running" | null {
  if (!doc) return null;
  const states = Object.values(doc.sources).map((s) => displayState(s, now));
  if (states.some(needsAttention)) return "attention";
  if (states.some(isRunning)) return "running";
  return null;
}

/** Home "לטיפול" items: one per source that is waiting for (or gave up on) a login, or failed. */
export function syncActions(doc: SyncStatusDoc | null, now = Date.now()): HomeAction[] {
  if (!doc) return [];
  const out: HomeAction[] = [];
  for (const [source, s] of Object.entries(doc.sources)) {
    const d = displayState(s, now);
    const name = sourceLabel(source);
    // Keyed by run so dismissing one run's alert doesn't hide the next run's.
    const id = `sync-${source}-${d}-${s.run_id}`;
    const cta = { label: "לסנכרונים", to: "/syncs" };
    if (d === "waiting_for_otp") {
      out.push({ id, severity: "high", title: `הזן את קוד ה-SMS של ${name}`, detail: s.message, cta, amount: null });
    } else if (d === "needs_login" && OTP_SOURCES.has(source)) {
      out.push({ id, severity: "medium", title: `התחבר ל${name}`, detail: "קוד ב-SMS, מכאן מהאפליקציה", cta, amount: null });
    } else if (d === "waiting_for_login" || d === "needs_login") {
      out.push({
        id,
        severity: d === "waiting_for_login" ? "high" : "medium",
        title: `התחבר ל${name} ב-Chrome`,
        detail: s.message,
        cta,
        amount: null,
      });
    } else if (d === "failed") {
      out.push({ id, severity: "medium", title: `הסנכרון של ${name} נכשל`, detail: s.error ?? s.message, cta, amount: null });
    } else if (d === "rejected") {
      out.push({ id, severity: "medium", title: `הנתונים של ${name} נדחו בבדיקה`, detail: s.error ?? s.message, cta, amount: null });
    }
  }
  return out;
}

// --- shared transport ----------------------------------------------------------
// One stream / poll loop for the whole app (header, /syncs and home all subscribe),
// so mounting three components never triples the requests.

const EVENTS_URL = "/api/sync/events";
/** Stream errors without a snapshot in between before we give up on SSE. */
export const MAX_SSE_ERRORS = 3;
export const SSE_RETRY_MS = 60_000;

let doc: SyncStatusDoc | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
let retryTimer: ReturnType<typeof setTimeout> | undefined;
let inFlight = false;
let stream: EventSource | null = null;
let errors = 0;
/** True while S3 polling is the transport (SSE failed). */
let polling = false;
const listeners = new Set<() => void>();
const notificationListeners = new Set<() => void>();

/** Run `fn` whenever the server says an inbox notification changed (SSE `notification` event). */
export function onNotificationEvent(fn: () => void): () => void {
  notificationListeners.add(fn);
  return () => void notificationListeners.delete(fn);
}

async function fetchStatus(): Promise<SyncStatusDoc | null> {
  try {
    const res = await fetch("/data/sync-status.json", { cache: "no-store" });
    // CloudFront answers a missing key with the SPA's index.html, so check the type.
    if (!res.ok || !res.headers.get("content-type")?.includes("json")) return null;
    const body = (await res.json()) as SyncStatusDoc;
    return body && typeof body.sources === "object" ? body : null;
  } catch {
    return null;
  }
}

/** Replace the doc and notify listeners only when it actually changed. */
function setDoc(next: SyncStatusDoc | null) {
  if (JSON.stringify(next) === JSON.stringify(doc)) return;
  doc = next;
  listeners.forEach((l) => l());
}

function schedule() {
  clearTimeout(timer);
  if (!polling || !listeners.size || document.hidden) return;
  timer = setTimeout(tick, pollInterval(doc));
}

async function tick() {
  if (inFlight) return;
  inFlight = true;
  const next = await fetchStatus();
  inFlight = false;
  // SSE may have recovered while the fetch was in flight; its data is fresher.
  if (!polling) return;
  setDoc(next);
  schedule();
}

function closeStream() {
  if (stream) {
    stream.close();
    stream = null;
  }
}

function stopAll() {
  closeStream();
  clearTimeout(timer);
  clearTimeout(retryTimer);
}

function onSnapshot(e: MessageEvent) {
  let body: SyncStatusDoc;
  try {
    body = JSON.parse(e.data) as SyncStatusDoc;
  } catch {
    return;
  }
  if (!body || typeof body.sources !== "object") return;
  errors = 0;
  if (polling) {
    // Back on the stream: stop polling and the retry timer.
    polling = false;
    clearTimeout(timer);
    clearTimeout(retryTimer);
  }
  setDoc(body);
}

function onSource(e: MessageEvent) {
  let msg: { source: string; entry: SourceStatus };
  try {
    msg = JSON.parse(e.data);
  } catch {
    return;
  }
  if (!msg?.source || !msg.entry) return;
  setDoc({
    updated_at: msg.entry.updated_at,
    sources: { ...(doc?.sources ?? {}), [msg.source]: msg.entry },
  });
}

function onStreamError() {
  errors += 1;
  if (stream?.readyState === EventSource.CLOSED || errors >= MAX_SSE_ERRORS) fallBack();
}

/** Give up on SSE for now: poll S3 (once right away) and retry the stream later. */
function fallBack() {
  closeStream();
  clearTimeout(retryTimer);
  if (!listeners.size || document.hidden) return;
  retryTimer = setTimeout(() => {
    if (listeners.size && !document.hidden) openStream();
  }, SSE_RETRY_MS);
  if (!polling) {
    polling = true;
    void tick();
  }
}

function openStream() {
  closeStream();
  errors = 0;
  if (typeof EventSource === "undefined") return fallBack();
  const q = tenantQuery();   // EventSource cannot set X-Tenant-Id
  const es = new EventSource(q ? `${EVENTS_URL}?${q}` : EVENTS_URL, { withCredentials: true });
  stream = es;
  es.addEventListener("snapshot", onSnapshot as EventListener);
  es.addEventListener("source", onSource as EventListener);
  es.addEventListener("notification", () => notificationListeners.forEach((l) => l()));
  es.onerror = onStreamError;
}

function onVisibility() {
  if (!listeners.size) return;
  if (document.hidden) {
    stopAll();
    return;
  }
  // Back on the tab: start over on SSE; a failing stream falls back to polling again.
  polling = false;
  openStream();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (listeners.size === 1) {
    document.addEventListener("visibilitychange", onVisibility);
    polling = false;
    if (!document.hidden) openStream();
  }
  return () => {
    listeners.delete(listener);
    if (!listeners.size) {
      stopAll();
      polling = false;
      document.removeEventListener("visibilitychange", onVisibility);
    }
  };
}

/** Live sync status; null until loaded or when there is no automated sync. */
export function useSyncStatus(): SyncStatusDoc | null {
  return useSyncExternalStore(subscribe, () => doc);
}

/** Test hooks: the store without React, and a reset of all module state. */
export const __store = { subscribe, get: () => doc };

export function __resetSyncStatusForTests() {
  stopAll();
  listeners.clear();
  document.removeEventListener("visibilitychange", onVisibility);
  doc = null;
  inFlight = false;
  errors = 0;
  polling = false;
}
