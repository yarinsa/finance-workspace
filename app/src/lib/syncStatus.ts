import { useSyncExternalStore } from "react";
import type { HomeAction } from "./data";

/**
 * Live state of the automated (Temporal) sync, read from data/sync-status.json.
 *
 * The worker on the Mac rewrites that file on every workflow status change
 * (sync/activities.py publish_status). Unlike the other data files it is polled,
 * not loaded once: fast while a run is active, slow when idle, paused while the
 * tab is hidden. A missing file just means "no automated sync" (null).
 */

export type SyncState =
  | "starting"
  | "checking_session"
  | "waiting_for_login"
  | "scraping"
  | "digesting"
  | "publishing"
  | "done"
  | "needs_login"
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
  /** One-line root cause when status is `failed`. */
  error: string | null;
}

export interface SyncStatusDoc {
  updated_at: string;
  sources: Record<string, SourceStatus>;
}

/** States where the workflow is still moving on its own. */
const RUNNING: ReadonlySet<SyncState> = new Set(["starting", "checking_session", "scraping", "digesting", "publishing"]);
/** States that need the human (or a look at the Temporal UI). */
const ATTENTION: ReadonlySet<SyncState> = new Set(["waiting_for_login", "needs_login", "failed"]);

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
  return Object.values(doc.sources).some((s) => isRunning(displayState(s, now))) ? POLL_ACTIVE_MS : POLL_IDLE_MS;
}

export const STATE_PILL: Record<Display, { text: string; cls: string }> = {
  starting: { text: "מתחיל", cls: "pill-run" },
  checking_session: { text: "בודק חיבור", cls: "pill-run" },
  scraping: { text: "מוריד נתונים", cls: "pill-run" },
  digesting: { text: "מעבד", cls: "pill-run" },
  publishing: { text: "מפרסם", cls: "pill-run" },
  waiting_for_login: { text: "ממתין להתחברות", cls: "pill-warn" },
  needs_login: { text: "נדרשת התחברות", cls: "pill-bad" },
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

const LOGIN_LABEL: Record<string, string> = { amex: "אמריקן אקספרס" };

/** Home "לטיפול" items: one per source that is waiting for (or gave up on) a login, or failed. */
export function syncActions(doc: SyncStatusDoc | null, now = Date.now()): HomeAction[] {
  if (!doc) return [];
  const out: HomeAction[] = [];
  for (const [source, s] of Object.entries(doc.sources)) {
    const d = displayState(s, now);
    const name = LOGIN_LABEL[source] ?? source;
    // Keyed by run so dismissing one run's alert doesn't hide the next run's.
    const id = `sync-${source}-${d}-${s.run_id}`;
    const cta = { label: "לסנכרונים", to: "/syncs" };
    if (d === "waiting_for_login" || d === "needs_login") {
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
    }
  }
  return out;
}

// --- shared poller ------------------------------------------------------------
// One fetch loop for the whole app (header, /syncs and home all subscribe), so
// mounting three components never triples the requests.

let doc: SyncStatusDoc | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
let inFlight = false;
const listeners = new Set<() => void>();

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

function schedule() {
  clearTimeout(timer);
  if (!listeners.size || document.hidden) return;
  timer = setTimeout(tick, pollInterval(doc));
}

async function tick() {
  if (inFlight) return;
  inFlight = true;
  const next = await fetchStatus();
  inFlight = false;
  if (JSON.stringify(next) !== JSON.stringify(doc)) {
    doc = next;
    listeners.forEach((l) => l());
  }
  schedule();
}

function onVisibility() {
  if (document.hidden) clearTimeout(timer);
  else void tick(); // back on the tab: refresh right away
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (listeners.size === 1) {
    document.addEventListener("visibilitychange", onVisibility);
    void tick();
  }
  return () => {
    listeners.delete(listener);
    if (!listeners.size) {
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    }
  };
}

/** Live sync-status.json; null until loaded or when there is no automated sync. */
export function useSyncStatus(): SyncStatusDoc | null {
  return useSyncExternalStore(subscribe, () => doc);
}
