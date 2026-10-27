import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { getHealth, getRebuild, keyId, type RebuildStatus, type Row } from "./api";
import { reloadData } from "./data";
import type { Overlay } from "./ledgerOverlay";

const HEALTH_POLL_MS = 60_000;
const REBUILD_POLL_MS = 5_000;

export interface LedgerApi {
  /** null until the first health check answers. */
  online: boolean | null;
  /** The API runs with its dev auth bypass: show a banner. */
  dev: boolean;
  rebuild: RebuildStatus;
  /** True while an edit is waiting to be published (pending/running). */
  updating: boolean;
  /** Latest API row per edited transaction, applied over the static data until published. */
  overlay: Overlay;
  /** Record a PATCH/DELETE response: updates the overlay and starts watching the rebuild. */
  recordEdit: (row: Row) => void;
  /** A write that has no transaction row (goals, plan targets) succeeded: watch the rebuild and reload data when it publishes. */
  markDirty: () => void;
  /** Mark the API unreachable (a call failed with ApiOffline) without waiting for the next poll. */
  markOffline: () => void;
}

const IDLE: RebuildStatus = { state: "idle", last_published_at: null, last_error: null };

const Ctx = createContext<LedgerApi | null>(null);

/**
 * Owns the ledger API's shared state so every screen sees one poll loop:
 * - reachability: `/api/health` every 60 s and whenever the window regains focus
 * - rebuild status: `/api/rebuild` every 5 s, but only while a rebuild is pending/running
 * - the optimistic overlay: after an edit the PATCH response is kept per transaction and
 *   applied over the static JSON. Once the rebuild goes back to idle with a newer
 *   `last_published_at`, the static `/data/*.json` is re-fetched and the overlay cleared,
 *   because the published data now contains the edits.
 */
export function LedgerApiProvider({ children }: { children: ReactNode }) {
  const [online, setOnline] = useState<boolean | null>(null);
  const [dev, setDev] = useState(false);
  const [rebuild, setRebuild] = useState<RebuildStatus>(IDLE);
  const [overlay, setOverlay] = useState<Map<string, Row>>(() => new Map());

  /** last_published_at we have seen; a change while dirty means our edits are live. */
  const published = useRef<string | null | undefined>(undefined);
  const dirty = useRef(false);

  const pollRebuild = useCallback(async () => {
    try {
      const r = await getRebuild();
      setRebuild(r);
      const seen = published.current;
      published.current = r.last_published_at;
      if (r.state === "idle" && dirty.current && seen !== undefined && r.last_published_at !== seen) {
        try {
          await reloadData();
          dirty.current = false;
          setOverlay(new Map());
        } catch {
          /* keep the overlay; the next poll/focus retries */
        }
      }
    } catch {
      setOnline(false);
    }
  }, []);

  const checkHealth = useCallback(async () => {
    try {
      const h = await getHealth();
      setOnline(h.ok);
      setDev(h.dev === true);
      if (h.ok) await pollRebuild();
    } catch {
      setOnline(false);
    }
  }, [pollRebuild]);

  useEffect(() => {
    void checkHealth();
    const id = setInterval(() => void checkHealth(), HEALTH_POLL_MS);
    const onFocus = () => void checkHealth();
    // Raised by code outside React state (e.g. an error boundary) when a call hit ApiOffline.
    const onOffline = () => setOnline(false);
    window.addEventListener("focus", onFocus);
    window.addEventListener("ledger-api-offline", onOffline);
    return () => {
      clearInterval(id);
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("ledger-api-offline", onOffline);
    };
  }, [checkHealth]);

  const busy = rebuild.state !== "idle";
  useEffect(() => {
    if (!busy) return;
    const id = setInterval(() => void pollRebuild(), REBUILD_POLL_MS);
    return () => clearInterval(id);
  }, [busy, pollRebuild]);

  const recordEdit = useCallback((row: Row) => {
    dirty.current = true;
    setOnline(true);
    setOverlay((prev) => new Map(prev).set(keyId(row), row));
    setRebuild((r) => (r.state === "idle" ? { ...r, state: "pending", last_error: null } : r));
  }, []);

  const markDirty = useCallback(() => {
    dirty.current = true;
    setOnline(true);
    setRebuild((r) => (r.state === "idle" ? { ...r, state: "pending", last_error: null } : r));
  }, []);

  const markOffline = useCallback(() => setOnline(false), []);

  const value = useMemo<LedgerApi>(
    () => ({ online, dev, rebuild, updating: busy, overlay, recordEdit, markDirty, markOffline }),
    [online, dev, rebuild, busy, overlay, recordEdit, markDirty, markOffline],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** Shared ledger-API state; must be used under `LedgerApiProvider`. */
export function useLedgerApi(): LedgerApi {
  const v = useContext(Ctx);
  if (!v) throw new Error("useLedgerApi must be used inside <LedgerApiProvider>");
  return v;
}
