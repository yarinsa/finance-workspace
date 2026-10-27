import { describe, expect, it } from "vitest";
import {
  buildMonthList,
  chargeHint,
  findLine,
  mergeCharges,
} from "./monthList";
import type { SpendingMonth } from "./spending";
import type { Budgets } from "./budgets";
import type { Bills } from "./bills";

// Real October 2026 rows: rent and the mortgage (fixed), groceries (variable), a pension debit.
const OCT: SpendingMonth = {
  month: "2026-10",
  total: 13117.25,
  vs_prev: null,
  partial: true,
  by_category: [],
  by_merchant: [],
  transactions: [
    {
      date: "2026-10-11",
      merchant: 'הו"ק לעיין ניהול נכסי',
      amount: 6800,
      category: "שכר דירה",
      group: "דיור",
      kind: "fixed",
      block: "fixed",
    },
    {
      date: "2026-10-11",
      merchant: "דסק-משכנתא",
      amount: 5817.25,
      category: "משכנתא",
      group: "פיננסים",
      kind: "fixed",
      block: "debt_savings",
    },
    {
      date: "2026-10-14",
      merchant: "שופרסל דיל",
      amount: 250,
      category: "כלכלה",
      group: "אוכל",
      kind: "variable",
      block: "variable",
    },
    {
      date: "2026-10-10",
      merchant: "הראל פנסיה חיוב",
      amount: 250,
      category: "השקעה וחיסכון",
      group: "הכנסות וחיסכון",
      block: "debt_savings",
    },
  ],
  excluded: {
    card_bills: { amount: 0, count: 0 },
    transfers: { amount: 0, count: 0 },
    savings: { amount: 900, count: 1 },
    income: { amount: 0, count: 0 },
  },
};

const BUDGETS = {
  cycle_start: "2026-10-01",
  categories: [
    {
      name: "כלכלה",
      scope: "category",
      group: "אוכל",
      planned: 1533.98,
      spent: 2085.41,
      left: -551.43,
      pct: 135.9,
      over: true,
      source: "override",
      estimate: 2684.54,
    },
    {
      name: "גינה",
      scope: "category",
      group: "בית",
      planned: 0,
      spent: 225.12,
      left: -225.12,
      pct: null,
      over: false,
      source: "unplanned",
      estimate: 0,
    },
  ],
} as unknown as Budgets;

const BILLS = {
  month: "2026-10",
  items: [
    {
      name: 'הו"ק לעיין ניהול נכסי',
      category: "שכר דירה",
      group: "דיור",
      kind: "bill",
      amount: 6800,
      due_day: 11,
      due_date: "2026-10-11",
      status: "paid",
      paid_on: "2026-10-11",
    },
    {
      name: "YES",
      category: "תקשורת",
      group: "חשבונות",
      kind: "bill",
      amount: 264.9,
      due_day: 28,
      due_date: "2026-10-28",
      status: "upcoming",
      paid_on: null,
    },
    {
      name: "קרן הוכשטיין",
      category: "הלוואה",
      group: "פיננסים",
      kind: "loan",
      amount: 500,
      due_day: 5,
      due_date: "2026-10-05",
      status: "overdue",
      paid_on: null,
    },
  ],
} as unknown as Bills;

describe("buildMonthList", () => {
  it("past month: plain category lines per section, savings as its own line", () => {
    const s = buildMonthList({ month: OCT });
    expect(s.map((x) => x.key)).toEqual(["fixed", "variable", "debt_savings"]);
    expect(s[0].groups[0]).toMatchObject({
      name: "דיור",
      total: 6800,
      alert: false,
    });
    const debt = s[2].groups.flatMap((g) => g.lines.map((l) => l.name));
    expect(debt).toEqual(
      expect.arrayContaining(["משכנתא", "השקעה וחיסכון", "חיסכון והפקדות"]),
    );
    expect(s[1].groups[0].lines[0].budget).toBeUndefined();
  });

  it("current cycle: budget bars for variable, bill statuses for fixed, loans under debt", () => {
    const s = buildMonthList({ month: OCT, budgets: BUDGETS, bills: BILLS });
    const variable = s.find((x) => x.key === "variable")!;
    const food = variable.groups.find((g) => g.name === "אוכל")!;
    expect(food.alert).toBe(true); // over budget: open by default
    expect(food.lines[0].budget?.planned).toBe(1533.98);
    const fixed = s.find((x) => x.key === "fixed")!;
    expect(
      fixed.groups.flatMap((g) => g.lines.map((l) => l.charge?.status)),
    ).toEqual(expect.arrayContaining(["paid", "upcoming"]));
    const debt = s.find((x) => x.key === "debt_savings")!;
    expect(debt.groups.some((g) => g.alert)).toBe(true); // the overdue loan
  });

  it("a deep link finds the budget line", () => {
    const s = buildMonthList({ month: OCT, budgets: BUDGETS, bills: BILLS });
    expect(findLine(s, "כלכלה")?.line.budget?.name).toBe("כלכלה");
    expect(findLine(s, "אין כזו")).toBeNull();
  });
});

describe("mergeCharges", () => {
  it("pairs a fixed item with its bill and keeps bill-only upcoming charges", () => {
    const out = mergeCharges(
      [
        {
          name: 'הו"ק לעיין ניהול נכסי',
          category: "שכר דירה",
          group: "דיור",
          block: "fixed",
          amount: 6800,
          duplicate: false,
        },
      ],
      BILLS.items,
    );
    expect(out).toHaveLength(3);
    expect(out[0]).toMatchObject({ status: "paid", due_day: 11, loan: false });
    expect(out.find((c) => c.name === "קרן הוכשטיין")?.loan).toBe(true);
  });
});

describe("chargeHint", () => {
  const today = new Date("2026-10-27T12:00:00");
  it("flags the second international-call plan as a duplicate", () => {
    expect(
      chargeHint(
        {
          name: 'אקספון 018 בע"מ',
          category: "תקשורת",
          amount: 34.9,
          duplicate: true,
          duplicate_reason: "שיחות לחו״ל",
          lever_key: "bills",
        },
        today,
      ),
    ).toBe("כפול · שיחות לחו״ל — לבדוק אם אפשר לבטל אחד");
  });
  it("a card fee gets the fee lever, a rent payment gets nothing", () => {
    expect(
      chargeHint(
        {
          name: "דמי כרטיס /הנפקה",
          category: "עמלות",
          amount: 102.38,
          last_charged: "2026-10-23",
          lever_key: "fees",
          lever: "לבקש ויתור מהבנק / חברת האשראי",
        },
        today,
      ),
    ).toBe("לבקש ויתור מהבנק / חברת האשראי");
    expect(
      chargeHint(
        {
          name: 'הו"ק לעיין ניהול נכסי',
          category: "שכר דירה",
          amount: 6800,
          last_charged: "2026-10-11",
          lever_key: "committed",
          lever: "x",
        },
        today,
      ),
    ).toBeNull();
  });
  it("a service not charged for over 70 days looks cancelled", () => {
    expect(
      chargeHint(
        {
          name: "MEDIUM MONTHLY",
          category: "הוצאות עסק",
          amount: 15.34,
          last_charged: "2026-07-01",
        },
        today,
      ),
    ).toMatch(/^לא חויב מאז/);
  });
});
