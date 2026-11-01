import { useSyncExternalStore } from "react";
import type { Horizon } from "./api";

/**
 * Holding placements the API accepted but the digest (`snapshot.holding_assignments`) does not
 * contain yet. Same life cycle as `goalsOverlay`: stamped with the data version it was recorded
 * against and ignored once data has been reloaded past it. In an entry a field that is present
 * was set by the user (`null` = cleared, back to the derived horizon / no goal); an absent field
 * is untouched.
 */

export interface HoldingPlacement {
  horizon?: Horizon | null;
  goalId?: number | null;
}

export interface HoldingsOverlay {
  version: number;
  entries: Record<string, HoldingPlacement>;
}

export const EMPTY_HOLDINGS_OVERLAY: HoldingsOverlay = { version: 0, entries: {} };

/** The digest's shape: `snapshot.holding_assignments`. */
export type DigestAssignments = Record<string, { horizon?: Horizon | null; goal_id?: number | null }>;

/** Record a change; `patch` fields override earlier ones, `null` clears. */
export function overlayAssign(o: HoldingsOverlay, id: string, patch: HoldingPlacement, version: number): HoldingsOverlay {
  const base = o.version < version ? { ...EMPTY_HOLDINGS_OVERLAY, version } : { ...o, version: Math.max(o.version, version) };
  return { ...base, entries: { ...base.entries, [id]: { ...base.entries[id], ...patch } } };
}

/**
 * digest ⊕ overlay as the `manual` map `holdingRows` takes. A field that ends up null is left
 * out, so the holding falls back to its derived horizon (or no goal).
 */
export function manualPlacements(
  digest: DigestAssignments | null | undefined,
  o: HoldingsOverlay,
  version: number,
): Map<string, HoldingPlacement> {
  const out = new Map<string, HoldingPlacement>();
  const set = (id: string, horizon: Horizon | null | undefined, goalId: number | null | undefined) => {
    const p: HoldingPlacement = {};
    if (horizon) p.horizon = horizon;
    if (goalId != null) p.goalId = goalId;
    if (p.horizon !== undefined || p.goalId !== undefined) out.set(id, p);
    else out.delete(id);
  };
  const ids = new Set(Object.keys(digest ?? {}));
  const live = o.version >= version;
  if (live) for (const id of Object.keys(o.entries)) ids.add(id);
  for (const id of ids) {
    const d = digest?.[id];
    const e = live ? o.entries[id] : undefined;
    set(id, e?.horizon !== undefined ? e.horizon : d?.horizon, e?.goalId !== undefined ? e.goalId : d?.goal_id);
  }
  return out;
}

let state: HoldingsOverlay = EMPTY_HOLDINGS_OVERLAY;
const listeners = new Set<() => void>();

export function recordHoldingChange(next: (o: HoldingsOverlay) => HoldingsOverlay): void {
  state = next(state);
  listeners.forEach((l) => l());
}

export function useHoldingsOverlay(): HoldingsOverlay {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => void listeners.delete(cb);
    },
    () => state,
  );
}
