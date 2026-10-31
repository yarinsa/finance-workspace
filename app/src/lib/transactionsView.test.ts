import { describe, expect, it } from "vitest";
import type { Row } from "./api";
import type { Line, SpendCard } from "./monthList";
import {
  accountCounts,
  accountLabel,
  applyView,
  filterByAccount,
  inRange,
  parseAccount,
  parseRange,
  rangeToParams,
  resolveRange,
  totals,
  widgetStats,
  cyclePlans,
  groupRows,
  parseGroup,
  type LedgerRow,
} from "./transactionsView";

// Made-up transactions shaped like the digested ledger (money out negative).
const ledger: LedgerRow[] = [
  { date: "2026-10-29", amount: -184.9, description: "שופרסל דיל", category: "מזון", origin: "cal", card_last4: "1234", kind: "variable" },
  { date: "2026-10-28", amount: 12500, description: "משכורת", category: "הכנסה", origin: "discount" },
  { date: "2026-10-10", amount: -4210.55, description: "כרטיסי אשראי-י", origin: "discount", card_bill_payment: true },
  { date: "2026-10-09", amount: -3000, description: "העברה לחשבון", origin: "discount", internal_transfer: true },
  { date: "2026-10-05", amount: -320, description: "פז סלף", category: "תחבורה", origin: "amex", kind: "variable" },
  { date: "2026-10-05", amount: -89, description: "נטפליקס", category: "מנויים", origin: "cal", kind: "fixed" },
  { date: "2026-09-02", amount: -600, description: "ארוחה משותפת", category: "מסעדות", origin: "max", offset_amount: 300 },
  { date: "2026-11-02", amount: -250, description: "תשלום עתידי", category: "ביטוח", origin: "leumi" },
];

const overlayRow = (over: Partial<Row>): Row => ({
  date: "2026-10-05",
  abs_amount: "320.00",
  amount: -320,
  description: "פז סלף",
  category: "דלק",
  scraped_category: "תחבורה",
  note: null,
  excluded: false,
  overridden: true,
  origin: "amex",
  sources: ["amex"],
  ...over,
});
const overlayOf = (...rows: Row[]) => new Map(rows.map((r) => [`${r.date}/${r.abs_amount}`, r]));

describe("applyView", () => {
  it("hides card-bill payments and internal transfers, keeps income and spending", () => {
    const v = applyView(ledger, new Map());
    expect(v.map((t) => t.description)).not.toContain("כרטיסי אשראי-י");
    expect(v.map((t) => t.description)).not.toContain("העברה לחשבון");
    expect(v.map((t) => t.description)).toContain("משכורת");
    expect(v).toHaveLength(6);
  });

  it("takes the overlay's category and drops rows it excludes", () => {
    const v = applyView(ledger, overlayOf(overlayRow({}), overlayRow({ date: "2026-10-05", abs_amount: "89.00", excluded: true })));
    const fuel = v.find((t) => t.description === "פז סלף")!;
    expect(fuel.category).toBe("דלק");
    expect(fuel.overridden).toBe(true);
    expect(v.find((t) => t.description === "נטפליקס")).toBeUndefined();
  });
});

describe("range", () => {
  it("defaults to 30 days for missing or unknown ?days", () => {
    expect(parseRange({})).toEqual({ kind: "days", days: 30 });
    expect(parseRange({ days: "45" })).toEqual({ kind: "days", days: 30 });
    expect(parseRange({ days: "90" })).toEqual({ kind: "days", days: 90 });
  });

  it("accepts a custom window, swapping a reversed one, and ignores impossible dates", () => {
    expect(parseRange({ from: "2026-10-20", to: "2026-09-01" })).toEqual({ kind: "custom", from: "2026-09-01", to: "2026-10-20" });
    expect(parseRange({ from: "2026-02-30", to: "2026-03-10", days: "60" })).toEqual({ kind: "days", days: 60 });
  });

  it("ends a preset today, inclusive", () => {
    expect(resolveRange({ kind: "days", days: 30 }, "2026-10-31")).toEqual({ from: "2026-10-02", to: "2026-10-31" });
  });

  it("omits the default from the URL", () => {
    expect(rangeToParams({ kind: "days", days: 30 })).toEqual({});
    expect(rangeToParams({ kind: "days", days: 180 })).toEqual({ days: "180" });
    expect(rangeToParams({ kind: "custom", from: "2026-09-01", to: "2026-09-30" })).toEqual({ from: "2026-09-01", to: "2026-09-30" });
  });

  it("keeps the window's rows newest first and leaves future-dated rows out", () => {
    const v = inRange(applyView(ledger, new Map()), resolveRange({ kind: "days", days: 30 }, "2026-10-31"));
    expect(v.map((t) => t.description)).toEqual(["שופרסל דיל", "משכורת", "פז סלף", "נטפליקס"]);
  });
});

describe("accounts", () => {
  const rows = inRange(applyView(ledger, new Map()), { from: "2026-09-01", to: "2026-10-31" });

  it("counts rows per origin, most first", () => {
    expect(accountCounts(rows)).toEqual([
      { key: "cal", count: 2 },
      { key: "amex", count: 1 },
      { key: "discount", count: 1 },
      { key: "max", count: 1 },
    ]);
  });

  it("filters to one origin, or all with null", () => {
    expect(filterByAccount(rows, "amex").map((t) => t.description)).toEqual(["פז סלף"]);
    expect(filterByAccount(rows, null)).toHaveLength(5);
  });

  it("falls back to הכל for an account not in range", () => {
    expect(parseAccount("leumi", ["cal", "amex"])).toBeNull();
    expect(parseAccount("cal", ["cal", "amex"])).toBe("cal");
    expect(accountLabel("other", (s) => s)).toBe("אחר");
  });
});

describe("totals", () => {
  it("sums money out and in after offsets", () => {
    const rows = inRange(applyView(ledger, new Map()), { from: "2026-09-01", to: "2026-10-31" });
    // out: 184.9 + 320 + 89 + (600 - 300 offset) = 893.9
    expect(totals(rows)).toEqual({ count: 5, out: 893.9, in: 12500 });
  });
});

describe("widgetStats", () => {
  const rows = inRange(applyView(ledger, new Map()), { from: "2026-09-01", to: "2026-10-31" });

  it("splits money out by kind, kindless rows into other", () => {
    const w = widgetStats(rows);
    expect(w.split).toEqual({ fixed: 89, variable: 504.9, other: 300 });
    expect(w.net).toBeCloseTo(12500 - 893.9);
  });

  it("ranks the largest spending categories, after offsets", () => {
    expect(widgetStats(rows, 2).topCategories).toEqual([
      { name: "תחבורה", amount: 320 },
      { name: "מסעדות", amount: 300 },
    ]);
  });

  it("follows the account filter and the overlay's category", () => {
    const overlay = overlayOf(overlayRow({}));
    const amex = filterByAccount(inRange(applyView(ledger, overlay), { from: "2026-09-01", to: "2026-10-31" }), "amex");
    expect(widgetStats(amex).topCategories).toEqual([{ name: "דלק", amount: 320 }]);
    expect(widgetStats(amex).in).toBe(0);
  });
});

describe("cycle range", () => {
  it("round-trips ?range=cycle and uses the budget's bounds", () => {
    expect(parseRange({ range: "cycle", days: "90" })).toEqual({ kind: "cycle" });
    expect(rangeToParams({ kind: "cycle" })).toEqual({ range: "cycle" });
    expect(resolveRange({ kind: "cycle" }, "2026-10-31", { from: "2026-10-10", to: "2026-11-09" })).toEqual({ from: "2026-10-10", to: "2026-11-09" });
  });

  it("falls back to 30 days with no budget", () => {
    expect(resolveRange({ kind: "cycle" }, "2026-10-31", null)).toEqual({ from: "2026-10-02", to: "2026-10-31" });
  });
});

describe("groupRows", () => {
  const rows = inRange(applyView(ledger, new Map()), { from: "2026-09-01", to: "2026-10-31" });

  it("parses ?group, defaulting to the flat list", () => {
    expect(parseGroup("kind")).toBe("kind");
    expect(parseGroup("merchant")).toBe("none");
  });

  it("by kind: fixed, variable, other, then income, rows kept newest first", () => {
    const g = groupRows(rows, "kind");
    expect(g.map((x) => [x.label, x.out, x.in])).toEqual([
      ["קבוע", 89, 0],
      ["משתנה", 504.9, 0],
      ["אחר", 300, 0],
      ["הכנסות", 0, 12500],
    ]);
    expect(g[1].rows.map((t) => t.description)).toEqual(["שופרסל דיל", "פז סלף"]);
  });

  it("by category: biggest spend first, income-only last, the overlay's category wins", () => {
    const view = inRange(applyView(ledger, overlayOf(overlayRow({}))), { from: "2026-09-01", to: "2026-10-31" });
    expect(groupRows(view, "category").map((x) => x.label)).toEqual(["דלק", "מסעדות", "מזון", "מנויים", "הכנסה"]);
  });

  it("folds a group-scope budget line's categories into its card", () => {
    const g = groupRows(rows, "category", new Map([["תחבורה", "רכב ותחבורה"], ["מזון", "רכב ותחבורה"]]));
    expect(g[0]).toMatchObject({ label: "רכב ותחבורה", out: 504.9, variable: 504.9 });
  });
});

describe("cyclePlans", () => {
  const line = (over: Partial<Line>): Line => ({ key: "k", section: "variable", group: "רכב", name: "x", category: "x", scope: "category", amount: 0, ...over });
  const card = (over: Partial<SpendCard>): SpendCard => ({
    name: "תחבורה", category: true, fixedLines: [], variableLines: [], fixed: 0, variable: 0,
    fixedPending: 0, variablePlan: 0, planned: null, actual: 0, over: false, alert: false, ...over,
  });
  const budget = { name: "תחבורה", scope: "group" as const, planned: 900, spent: 320, left: 580, pct: 35.6, over: false, source: "override" as const };

  it("keys the plan by card, aliases a group line's parts and lists unpaid charges", () => {
    const { plans, alias } = cyclePlans([
      card({
        planned: 2100,
        variableLines: [line({ name: "תחבורה", category: "תחבורה", scope: "group", budget, parts: ["דלק", "רכב"] })],
        fixedLines: [
          line({ section: "fixed", charge: { name: "מטרו מוטור", category: "רכב", amount: 1200, status: "upcoming", due_day: 10 } }),
          line({ section: "fixed", charge: { name: "ביטוח רכב", category: "רכב", amount: 310, status: "paid" } }),
        ],
      }),
    ]);
    expect(alias).toEqual(new Map([["דלק", "תחבורה"], ["רכב", "תחבורה"]]));
    const p = plans.get("תחבורה")!;
    expect(p.planned).toBe(2100);
    expect(p.budget?.planned).toBe(900);
    expect(p.pending.map((c) => c.name)).toEqual(["מטרו מוטור"]);
  });
});
