import { useSyncExternalStore } from "react";
import type { GeneralGoalCard, Goals, PersonalGoal } from "./data";

/**
 * Goal edits that the API accepted but the static `goals.json` does not contain yet (the
 * ledger rebuild publishes it a while later). The Goals screen renders digest ⊕ overlay so
 * a create, edit, delete or target change shows at once; figures the digest derives from
 * the changed value (progress, on-track, days left, coverage) are flagged `pending` and
 * shown as "מתעדכן…" instead of a stale number.
 *
 * The overlay is stamped with the data version it was recorded against; once data has been
 * reloaded past that version the digest is the truth and the overlay is ignored.
 */

export type TargetKey = "emergencyFund" | "inheritance" | "retirement";

/** The general card each plan target drives (data/goals.py keys). */
export const TARGET_CARD: Record<TargetKey, string> = {
  emergencyFund: "emergency_fund_coverage",
  inheritance: "inheritance_amount",
  retirement: "retirement_coverage",
};

type Horizon = NonNullable<PersonalGoal["horizon"]>;

/** The goal fields the user can see change right away. */
export interface GoalPatch {
  description?: string;
  amount?: number;
  end_date?: string | null;
  horizon?: Horizon | null;
}

export interface GoalsOverlay {
  /** Data version the changes were recorded against. */
  version: number;
  /** Goals created since the digest, in creation order; ids are the table ids. */
  created: PersonalGoal[];
  /** Patches per table id (applies to digest goals, and to `created` ones via `overlayUpdate`). */
  updated: Record<number, GoalPatch>;
  deleted: number[];
  /** New target per plan target; null = unset. */
  targets: Partial<Record<TargetKey, number | null>>;
}

export const EMPTY_OVERLAY: GoalsOverlay = { version: 0, created: [], updated: {}, deleted: [], targets: {} };

/** Reset the overlay if it was recorded against older data, so records start from a clean base. */
function fresh(o: GoalsOverlay, version: number): GoalsOverlay {
  return o.version < version ? { ...EMPTY_OVERLAY, version } : { ...o, version: Math.max(o.version, version) };
}

export function overlayCreate(o: GoalsOverlay, goal: PersonalGoal, version: number): GoalsOverlay {
  const b = fresh(o, version);
  return { ...b, created: [...b.created, goal] };
}

export function overlayUpdate(o: GoalsOverlay, goalId: number, patch: GoalPatch, version: number): GoalsOverlay {
  const b = fresh(o, version);
  if (b.created.some((g) => g.goal_id === goalId)) {
    return { ...b, created: b.created.map((g) => (g.goal_id === goalId ? { ...g, ...patch } : g)) };
  }
  return { ...b, updated: { ...b.updated, [goalId]: { ...b.updated[goalId], ...patch } } };
}

export function overlayDelete(o: GoalsOverlay, goalId: number, version: number): GoalsOverlay {
  const b = fresh(o, version);
  const { [goalId]: _gone, ...updated } = b.updated;
  return {
    ...b,
    created: b.created.filter((g) => g.goal_id !== goalId),
    updated,
    deleted: b.deleted.includes(goalId) || b.created.some((g) => g.goal_id === goalId) ? b.deleted : [...b.deleted, goalId],
  };
}

export function overlayTargets(o: GoalsOverlay, targets: Partial<Record<TargetKey, number | null>>, version: number): GoalsOverlay {
  const b = fresh(o, version);
  return { ...b, targets: { ...b.targets, ...targets } };
}

/** A personal goal as displayed; `pending` = its derived figures are being recomputed. */
export type DisplayGoal = PersonalGoal & { pending?: boolean };
export type DisplayGeneral = GeneralGoalCard & { pending?: boolean };

export interface DisplayGoals {
  general: DisplayGeneral[];
  personal_goals: DisplayGoal[];
}

/** digest ⊕ overlay. With no overlay (or a stale one) the digest is returned unchanged. */
export function applyGoalsOverlay(goals: Pick<Goals, "general" | "personal_goals">, o: GoalsOverlay, version: number): DisplayGoals {
  if (o.version < version) return { general: goals.general, personal_goals: goals.personal_goals };

  const personal: DisplayGoal[] = [];
  for (const g of goals.personal_goals) {
    if (g.goal_id != null && o.deleted.includes(g.goal_id)) continue;
    const p = g.goal_id != null ? o.updated[g.goal_id] : undefined;
    if (!p) {
      personal.push(g);
      continue;
    }
    // Horizon and description don't feed progress; amount and end date do.
    const derived = p.amount !== undefined || p.end_date !== undefined;
    personal.push({
      ...g,
      ...p,
      ...(derived ? { pending: true, progress_pct: null, on_track: null, days_left: null } : {}),
    });
  }
  for (const g of o.created) personal.push({ ...g, pending: true, progress_pct: null, on_track: null, days_left: null });

  const byCard = new Map(Object.entries(TARGET_CARD).map(([k, card]) => [card, k as TargetKey]));
  const general = goals.general.map((c): DisplayGeneral => {
    const key = byCard.get(c.key);
    if (!key || !(key in o.targets)) return c;
    return { ...c, target: o.targets[key] ?? null, target_derived: false, pending: true };
  });

  return { general, personal_goals: personal };
}

// --- Module-level store (survives leaving the screen) -------------------------------------

let state: GoalsOverlay = EMPTY_OVERLAY;
const listeners = new Set<() => void>();

/** Update the store with one of the pure transitions above. */
export function recordGoalsChange(next: (o: GoalsOverlay) => GoalsOverlay): void {
  state = next(state);
  listeners.forEach((l) => l());
}

/** The current overlay (re-renders on every change). */
export function useGoalsOverlay(): GoalsOverlay {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => void listeners.delete(cb);
    },
    () => state,
  );
}
