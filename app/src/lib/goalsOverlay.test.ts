import { describe, expect, it } from "vitest";
import type { GeneralGoalCard, PersonalGoal } from "./data";
import { applyGoalsOverlay, EMPTY_OVERLAY, overlayCreate, overlayDelete, overlayTargets, overlayUpdate } from "./goalsOverlay";

const vacation: PersonalGoal = { goal_id: 1, description: "חופשה", amount: 5000, end_date: "2027-06-01", days_left: 200, progress_pct: 40, on_track: true, horizon: "near" };
const car: PersonalGoal = { goal_id: 2, description: "רכב", amount: 30000, progress_pct: 10, on_track: false };
const card = (key: string, over: Partial<GeneralGoalCard> = {}): GeneralGoalCard => ({
  key, name: key, units: "%", value: 80, status: "ok", description: "", target: 100000, target_derived: true, ...over,
});
const digest = { general: [card("emergency_fund_coverage"), card("retirement_coverage"), card("inheritance_amount")], personal_goals: [vacation, car] };

describe("applyGoalsOverlay", () => {
  it("returns the digest untouched with an empty or stale overlay", () => {
    expect(applyGoalsOverlay(digest, EMPTY_OVERLAY, 0).personal_goals).toEqual([vacation, car]);
    const o = overlayDelete(EMPTY_OVERLAY, 1, 3);
    // data reloaded to version 4: the digest already reflects the delete
    expect(applyGoalsOverlay(digest, o, 4).personal_goals).toEqual([vacation, car]);
  });

  it("shows a created goal at once with unknown derived fields", () => {
    const created: PersonalGoal = { goal_id: 9, description: "דירה", amount: 100, end_date: null, horizon: null, progress_pct: null, on_track: null };
    const out = applyGoalsOverlay(digest, overlayCreate(EMPTY_OVERLAY, created, 0), 0).personal_goals;
    expect(out).toHaveLength(3);
    expect(out[2]).toMatchObject({ description: "דירה", pending: true, progress_pct: null, on_track: null, days_left: null });
  });

  it("shows edited amount/end date immediately and marks derived fields pending", () => {
    const o = overlayUpdate(EMPTY_OVERLAY, 1, { amount: 8000, end_date: "2028-01-01", description: "טיול" }, 0);
    const g = applyGoalsOverlay(digest, o, 0).personal_goals[0];
    expect(g).toMatchObject({ description: "טיול", amount: 8000, end_date: "2028-01-01", pending: true, progress_pct: null, on_track: null, days_left: null });
  });

  it("a description- or horizon-only edit keeps the real progress", () => {
    const o = overlayUpdate(EMPTY_OVERLAY, 1, { description: "טיול", horizon: null }, 0);
    const g = applyGoalsOverlay(digest, o, 0).personal_goals[0];
    expect(g).toMatchObject({ description: "טיול", horizon: null, progress_pct: 40, on_track: true });
    expect(g.pending).toBeUndefined();
  });

  it("drops a deleted goal; deleting a pending create removes it without a server delete record", () => {
    const o = overlayDelete(EMPTY_OVERLAY, 2, 0);
    expect(applyGoalsOverlay(digest, o, 0).personal_goals.map((g) => g.goal_id)).toEqual([1]);

    const created: PersonalGoal = { goal_id: 9, description: "דירה", amount: 100, progress_pct: null, on_track: null };
    const o2 = overlayDelete(overlayCreate(EMPTY_OVERLAY, created, 0), 9, 0);
    expect(o2.created).toEqual([]);
    expect(o2.deleted).toEqual([]);
  });

  it("editing a pending create updates the created entry", () => {
    const created: PersonalGoal = { goal_id: 9, description: "דירה", amount: 100, progress_pct: null, on_track: null };
    const o = overlayUpdate(overlayCreate(EMPTY_OVERLAY, created, 0), 9, { amount: 250 }, 0);
    expect(applyGoalsOverlay(digest, o, 0).personal_goals[2]).toMatchObject({ amount: 250, pending: true });
  });

  it("shows a changed target on its card, pending; an unset target is null", () => {
    const o = overlayTargets(EMPTY_OVERLAY, { retirement: 2_000_000, emergencyFund: null }, 0);
    const { general } = applyGoalsOverlay(digest, o, 0);
    expect(general[1]).toMatchObject({ key: "retirement_coverage", target: 2_000_000, pending: true });
    expect(general[0]).toMatchObject({ key: "emergency_fund_coverage", target: null, pending: true });
    expect(general[2].pending).toBeUndefined();
  });

  it("starts from a clean overlay when recording against newer data", () => {
    const old = overlayDelete(EMPTY_OVERLAY, 1, 0);
    const next = overlayDelete(old, 2, 1);
    expect(next.deleted).toEqual([2]);
  });
});
