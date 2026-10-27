import { describe, expect, it } from "vitest";
import type { History, Pace, Runway } from "./data";
import { cashLens, defaultLens, readSignalMode, signalValue, spendLens } from "./lenses";

// The 2026-10-27 digest: Discount + Leumi checking, Discount's chain measured from 10-05.
const HISTORY: History = {
  cash: {
    as_of: "2026-10-27",
    measured_from: "2026-10-05",
    days: [
      { date: "2026-09-28", balance: 4049.46 },
      { date: "2026-09-29", balance: 6559.54 },
      { date: "2026-09-30", balance: 6389.36 },
      { date: "2026-10-01", balance: 5682.76 },
      { date: "2026-10-05", balance: 2569.93 },
      { date: "2026-10-26", balance: 2936.59 },
      { date: "2026-10-27", balance: 2936.59 },
    ],
  },
  debt: [],
  positions: [],
};
const RUNWAY = {
  as_of: "2026-10-27",
  start_balance: 2936.59,
  safe_to_spend: 421.89,
  days: [
    { date: "2026-10-27", balance: 2936.59 },
    { date: "2026-10-28", balance: 2936.59 },
    { date: "2026-11-02", balance: -2400.0 },
  ],
} as unknown as Runway;

// October to day 26 against September, real cumulative spend.
const PACE = {
  as_of_day: 26,
  days_in_month: 31,
  current: { month: "2026-10", income: 31774.46, expense: 35209.5, net: -3435.04, month_expense: 35209.5,
             daily_expense: [834.61, 4860.46, 35209.5] },
  previous: { month: "2026-09", income: 27895.96, expense: 39563.56, net: -11667.6, month_expense: 42421.74,
              daily_expense: Array.from({ length: 30 }, (_, i) => (i === 25 ? 39563.56 : i * 1000)) },
} as unknown as Pace;

describe("cash lens", () => {
  it("ends the measured line on today's balance and continues it as the runway", () => {
    const l = cashLens(HISTORY, RUNWAY)!;
    expect(l.value).toBe(2936.59);
    const today = l.series[l.todayIndex];
    expect(today).toMatchObject({ x: "2026-10-27", actual: 2936.59, projected: 2936.59 });
    expect(l.series.at(-1)).toEqual({ x: "2026-11-02", projected: -2400.0 });
    expect(l.series.find((p) => p.x === "2026-10-01")?.estimated).toBe(true);
    expect(l.series.find((p) => p.x === "2026-10-05")?.estimated).toBe(false);
  });

  it("shows no 'this month' change when the end of last month was only rebuilt from the ledger", () => {
    // 09-30 is before Discount's chain starts (10-05): estimated, so no delta.
    expect(cashLens(HISTORY, RUNWAY)!.delta).toBeNull();
    const measured = { ...HISTORY, cash: { ...HISTORY.cash, measured_from: "2026-09-01" } };
    expect(cashLens(measured, RUNWAY)!.delta).toMatchObject({ amount: 2936.59 - 6389.36, good: false });
  });

  it("works on data published before history existed", () => {
    const l = cashLens(undefined, RUNWAY)!;
    expect(l.series[0].x).toBe("2026-10-27");
    expect(l.delta).toBeNull();
  });
});

describe("spend lens", () => {
  it("compares this month with last month at the same day", () => {
    const l = spendLens(PACE)!;
    expect(l.value).toBe(35209.5);
    expect(l.delta).toMatchObject({ text: "פחות מבחודש שעבר", good: true });
    expect(Math.round(l.delta!.amount)).toBe(-4354);
    expect(l.series).toHaveLength(31);
    expect(l.series[2]).toMatchObject({ actual: 35209.5 });
    expect(l.series[3].actual).toBeUndefined();
    expect(l.todayIndex).toBe(2);
  });
});

describe("corner signal", () => {
  it("is spent/income by default and safe-to-spend when chosen", () => {
    expect(readSignalMode(undefined)).toBe("ratio");
    expect(readSignalMode({ getItem: () => "safe" })).toBe("safe");
    const ratio = signalValue("ratio", PACE, RUNWAY)!;
    expect(Math.round(ratio.value)).toBe(111);
    expect(ratio.good).toBe(false);
    expect(signalValue("safe", PACE, RUNWAY)).toMatchObject({ value: 421.89, unit: "₪", good: true });
  });
});

describe("default lens", () => {
  it("opens on cash until a property value exists, and honours a pinned lens", () => {
    expect(defaultLens(["spend", "cash"], { property_value: null }, null)).toBe("cash");
    expect(defaultLens(["spend", "cash", "networth"], { property_value: 2_400_000 }, null)).toBe("networth");
    expect(defaultLens(["spend", "cash"], { property_value: 2_400_000 }, null)).toBe("cash");
    expect(defaultLens(["spend", "cash"], undefined, "spend")).toBe("spend");
    expect(defaultLens(["spend", "cash"], undefined, "debt")).toBe("cash");   // pinned but not shipped yet
  });
});
