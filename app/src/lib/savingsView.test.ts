import { describe, expect, it } from "vitest";
import type { Row } from "./api";
import type { PersonalGoal, Savings } from "./data";
import {
  deriveHorizon,
  groupSavings,
  holdingRows,
  movementRows,
  movementsInRange,
  parseSavingsGroup,
  savingsStats,
} from "./savingsView";
import type { LedgerRow } from "./transactionsView";

const TODAY = "2026-11-01";

// The funds as scraped (snapshot.savings, 2026-10-31).
const funds: Savings[] = [
  { institution: "analyst", kind: "provident_fund", balance: 76992, currency: "ILS", label: "Analyst קופת גמל 5036 (עצמאי)", topic_id: "5036-000-011143707", liquidity_date: "2057-11-23", as_of: "2026-09-30" },
  { institution: "harel", kind: "pension", balance: 392606, currency: "ILS", label: "קרנות פנסיה", topic_id: "70" },
  { institution: "harel", kind: "study_fund", balance: 154189, currency: "ILS", label: "השתלמות", topic_id: "62" },
  { institution: "more", kind: "study_fund", balance: 25219.64, currency: "ILS", label: "More קרן השתלמות 1251996 (עצמאי)", topic_id: "1251996", liquidity_date: "2031-01-31", as_of: "2026-09-30" },
  { institution: "more", kind: "study_fund", balance: 25.24, currency: "ILS", label: "More קרן השתלמות 902775", topic_id: "902775", liquidity_date: "2029-03-31", as_of: "2026-09-30" },
];

const ledger: LedgerRow[] = [
  { date: "2026-10-26", amount: 4000, description: "אקסלנס ניה", category: "השקעה וחיסכון", origin: "discount" },
  { date: "2026-10-11", amount: -250, description: "הראל פנסיה חיוב", category: "השקעה וחיסכון", origin: "discount-business", horizon: "future" } as LedgerRow,
  { date: "2026-10-13", amount: -0.03, description: "תשלום מס על רווח מפיקדון", category: "השקעה וחיסכון", origin: "discount", horizon: "near" } as LedgerRow,
  { date: "2026-10-12", amount: -184.9, description: "שופרסל דיל", category: "מזון", origin: "cal" },
];

describe("deriveHorizon", () => {
  it("puts liquid money and imminent dates in current", () => {
    expect(deriveHorizon({ liquid: true }, TODAY)).toBe("current");
    expect(deriveHorizon({ liquidity_date: "2026-12-01" }, TODAY)).toBe("current");
    expect(deriveHorizon({ liquidity_date: "2020-01-01" }, TODAY)).toBe("current");
  });
  it("splits the rest at five years", () => {
    expect(deriveHorizon({ liquidity_date: "2029-03-31" }, TODAY)).toBe("near");
    expect(deriveHorizon({ liquidity_date: "2031-01-31" }, TODAY)).toBe("near");
    expect(deriveHorizon({ liquidity_date: "2057-11-23" }, TODAY)).toBe("future");
  });
  it("does not guess a horizon without a date", () => {
    expect(deriveHorizon({}, TODAY)).toBeNull();
  });
});

describe("holdingRows", () => {
  it("leaves the Harel funds unassigned until the user picks a horizon", () => {
    const rows = holdingRows(funds, TODAY);
    expect(rows.find((r) => r.label === "קרנות פנסיה")).toMatchObject({ horizon: null, horizonSource: null });
    expect(rows.find((r) => r.institution === "analyst")).toMatchObject({ horizon: "future", horizonSource: "derived" });
  });
  it("lets a manual assignment win over the derived one", () => {
    const manual = new Map([["harel:70", { horizon: "future" as const }], ["more:1251996", { horizon: "current" as const }]]);
    const rows = holdingRows(funds, TODAY, manual);
    expect(rows.find((r) => r.id === "harel:70")).toMatchObject({ horizon: "future", horizonSource: "manual" });
    expect(rows.find((r) => r.id === "more:1251996")).toMatchObject({ horizon: "current", horizonSource: "manual" });
  });
});

describe("movementRows", () => {
  it("keeps only savings rows and reverses the sign so deposits are positive", () => {
    const rows = movementRows(ledger, new Map());
    expect(rows).toHaveLength(3);
    expect(rows.find((r) => r.description === "הראל פנסיה חיוב")).toMatchObject({ flow: 250, horizon: "future" });
    expect(rows.find((r) => r.description === "אקסלנס ניה")).toMatchObject({ flow: -4000, horizon: null });
  });
  it("applies the overlay's horizon and goal, and drops excluded rows", () => {
    const key = "2026-10-26/4000.00";
    const overlay = new Map([[key, { horizon: "near", goal_id: 2, excluded: false, overridden: true, category: "השקעה וחיסכון" } as Row]]);
    const rows = movementRows(ledger, overlay);
    expect(rows.find((r) => r.description === "אקסלנס ניה")).toMatchObject({ horizon: "near", goalId: 2, edited: true });
    const gone = new Map([[key, { excluded: true } as Row]]);
    expect(movementRows(ledger, gone)).toHaveLength(2);
  });
  it("windows movements, newest first", () => {
    const rows = movementsInRange(movementRows(ledger, new Map()), { from: "2026-10-12", to: "2026-10-31" });
    expect(rows.map((r) => r.date)).toEqual(["2026-10-26", "2026-10-13"]);
  });
});

describe("groupSavings", () => {
  const holdings = holdingRows(funds, TODAY);
  const movements = movementRows(ledger, new Map());

  it("groups by horizon with לא משויך last and every horizon present", () => {
    const g = groupSavings(holdings, movements, "horizon");
    expect(g.map((x) => x.key)).toEqual(["current", "near", "future", "none"]);
    expect(g.find((x) => x.key === "near")!.balance).toBeCloseTo(25244.88);
    expect(g.find((x) => x.key === "none")!.balance).toBe(392606 + 154189);
  });
  it("reports balance and flow side by side without adding them", () => {
    const future = groupSavings(holdings, movements, "horizon").find((x) => x.key === "future")!;
    expect(future.balance).toBe(76992);
    expect(future.flow).toBe(250);
  });
  it("groups by kind and institution", () => {
    const kinds = groupSavings(holdings, movements, "kind");
    expect(kinds.find((x) => x.key === "study_fund")).toMatchObject({ label: "קרן השתלמות" });
    const inst = groupSavings(holdings, movements, "institution", { institutionLabel: (s) => s.toUpperCase() });
    expect(inst.find((x) => x.key === "harel")!.balance).toBe(392606 + 154189);
  });
  it("groups by goal, keeping goals without rows and unassigned rows apart", () => {
    const goal = { goal_id: 2, description: "חופשות", amount: 30000, progress_pct: 8.6, on_track: false } as PersonalGoal;
    const g = groupSavings(holdings, movementRows(ledger, new Map([["2026-10-11/250.00", { goal_id: 2, excluded: false, overridden: true, category: "השקעה וחיסכון" } as Row]])), "goal", { goals: [goal] });
    expect(g[0]).toMatchObject({ key: "2", label: "חופשות", flow: 250 });
    expect(g[0].goal).toBe(goal);
    expect(g[g.length - 1].key).toBe("none");
  });
});

describe("savingsStats", () => {
  it("totals the stock, the next unlock and the flow separately", () => {
    const s = savingsStats(holdingRows(funds, TODAY), movementRows(ledger, new Map()));
    expect(s.balance).toBeCloseTo(649032, 0);
    expect(s.liquid).toBe(0);
    expect(s.nextUnlock).toEqual({ date: "2029-03-31", amount: 25.24 });
    expect(s.asOf).toBe("2026-09-30");
    expect(s.flow).toBeCloseTo(-3749.97, 2);
  });
});

describe("parseSavingsGroup", () => {
  it("defaults to horizon", () => {
    expect(parseSavingsGroup(null)).toBe("horizon");
    expect(parseSavingsGroup("kind")).toBe("kind");
    expect(parseSavingsGroup("bogus")).toBe("horizon");
  });
});
