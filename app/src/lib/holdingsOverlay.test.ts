import { describe, expect, it } from "vitest";
import { EMPTY_HOLDINGS_OVERLAY, manualPlacements, overlayAssign } from "./holdingsOverlay";
import { groupSavings, holdingId, holdingRows } from "./savingsView";

const harel = { institution: "harel", topic_id: "123", kind: "pension" as const, label: "פנסיה", balance: 1000, currency: "ILS" };

describe("holding id", () => {
  it("is institution:topic_id, else the label", () => {
    expect(holdingId(harel)).toBe("harel:123");
    expect(holdingId({ institution: "more", label: "השתלמות" })).toBe("more:השתלמות");
  });
});

describe("manualPlacements", () => {
  it("uses the digest when the overlay is empty", () => {
    const m = manualPlacements({ "harel:123": { horizon: "near", goal_id: 4 } }, EMPTY_HOLDINGS_OVERLAY, 1);
    expect(m.get("harel:123")).toEqual({ horizon: "near", goalId: 4 });
  });
  it("overlay wins, and a cleared horizon falls back to derived", () => {
    const o = overlayAssign(EMPTY_HOLDINGS_OVERLAY, "harel:123", { horizon: null }, 1);
    const m = manualPlacements({ "harel:123": { horizon: "near", goal_id: 4 } }, o, 1);
    expect(m.get("harel:123")).toEqual({ goalId: 4 });
    const rows = holdingRows([harel], "2026-11-01", m);
    expect(rows[0].horizonSource).toBe(null);
  });
  it("clearing both fields removes the entry", () => {
    const o = overlayAssign(overlayAssign(EMPTY_HOLDINGS_OVERLAY, "a:1", { horizon: "future" }, 1), "a:1", { horizon: null, goalId: null }, 1);
    expect(manualPlacements({}, o, 1).has("a:1")).toBe(false);
  });
  it("ignores an overlay recorded against older data", () => {
    const o = overlayAssign(EMPTY_HOLDINGS_OVERLAY, "harel:123", { horizon: "future" }, 1);
    expect(manualPlacements({}, o, 2).size).toBe(0);
  });
  it("an assignment moves the holding between horizon groups", () => {
    const m = manualPlacements({}, overlayAssign(EMPTY_HOLDINGS_OVERLAY, "harel:123", { horizon: "future" }, 1), 1);
    const g = groupSavings(holdingRows([harel], "2026-11-01", m), [], "horizon");
    expect(g.find((x) => x.key === "future")?.holdings).toHaveLength(1);
    expect(g.find((x) => x.key === "none")).toBeUndefined();
    expect(holdingRows([harel], "2026-11-01", m)[0].horizonSource).toBe("manual");
  });
});
