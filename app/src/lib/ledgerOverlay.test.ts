import { describe, expect, it } from "vitest";
import type { Row } from "./api";
import { applyOverlay } from "./ledgerOverlay";
import type { SpendingMonth } from "./spending";

// Made-up transactions only.
const month: SpendingMonth = {
  month: "2026-01",
  total: 300,
  vs_prev: null,
  partial: false,
  by_category: [
    { name: "מסעדות", amount: 200, pct: 66.7, count: 2 },
    { name: "תחבורה", amount: 100, pct: 33.3, count: 1 },
  ],
  by_merchant: [
    { name: "קפה לדוגמה", amount: 120, count: 1 },
    { name: "מסעדה לדוגמה", amount: 80, count: 1 },
    { name: "חניון לדוגמה", amount: 100, count: 1 },
  ],
  transactions: [
    { date: "2026-01-10", merchant: "קפה לדוגמה", amount: 120, category: "מסעדות" },
    { date: "2026-01-09", merchant: "מסעדה לדוגמה", amount: 80, category: "מסעדות" },
    { date: "2026-01-08", merchant: "חניון לדוגמה", amount: 100, category: "תחבורה" },
  ],
  excluded: {
    card_bills: { amount: 0, count: 0 },
    transfers: { amount: 0, count: 0 },
    savings: { amount: 0, count: 0 },
    income: { amount: 0, count: 0 },
  },
};

const row = (over: Partial<Row>): Row => ({
  date: "2026-01-10",
  abs_amount: "120.00",
  amount: -120,
  description: "קפה לדוגמה",
  category: "מסעדות",
  scraped_category: "מסעדות",
  note: null,
  excluded: false,
  overridden: true,
  origin: "cal",
  sources: ["cal"],
  ...over,
});

const overlayOf = (...rows: Row[]) => new Map(rows.map((r) => [`${r.date}/${r.abs_amount}`, r]));

describe("applyOverlay", () => {
  it("returns the input untouched with an empty overlay", () => {
    const months = [month];
    expect(applyOverlay(months, new Map())).toBe(months);
  });

  it("removes an excluded row from the list, totals, category and merchant", () => {
    const [m] = applyOverlay([month], overlayOf(row({ excluded: true })));
    expect(m.transactions.map((t) => t.merchant)).toEqual(["מסעדה לדוגמה", "חניון לדוגמה"]);
    expect(m.total).toBe(180);
    expect(m.by_category.find((c) => c.name === "מסעדות")).toMatchObject({ amount: 80, count: 1 });
    expect(m.by_merchant.map((x) => x.name)).not.toContain("קפה לדוגמה");
    expect(m.by_category.reduce((s, c) => s + c.pct, 0)).toBeCloseTo(100);
  });

  it("drops a category that becomes empty", () => {
    const [m] = applyOverlay([month], overlayOf(row({ date: "2026-01-08", abs_amount: "100.00", excluded: true })));
    expect(m.by_category.map((c) => c.name)).toEqual(["מסעדות"]);
  });

  it("moves the amount when the category changes", () => {
    const [m] = applyOverlay([month], overlayOf(row({ category: "קפה" })));
    expect(m.transactions[0].category).toBe("קפה");
    expect(m.total).toBe(300);
    expect(m.by_category.find((c) => c.name === "קפה")).toMatchObject({ amount: 120, count: 1 });
    expect(m.by_category.find((c) => c.name === "מסעדות")?.amount).toBe(80);
  });

  it("does not mutate the input", () => {
    applyOverlay([month], overlayOf(row({ excluded: true })));
    expect(month.total).toBe(300);
    expect(month.transactions).toHaveLength(3);
  });

  it("shows tags saved this session, and an emptied set clears them", () => {
    const [tagged] = applyOverlay([month], overlayOf(row({ tags: ["טיול"] })));
    expect(tagged.transactions[0].tags).toEqual(["טיול"]);
    expect(tagged.total).toBe(300);
    const before = { ...month, transactions: [{ ...month.transactions[0], tags: ["טיול"] }, ...month.transactions.slice(1)] };
    const [cleared] = applyOverlay([before], overlayOf(row({ tags: [] })));
    expect(cleared.transactions[0].tags).toEqual([]);
  });
});
