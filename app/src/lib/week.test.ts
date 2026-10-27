import { describe, expect, it } from "vitest";
import { initialDay, nextBeyond, weekDays } from "./week";

// The runway on Tuesday 2026-10-27: loans on Sunday 11-01, the Leumi loan on Monday 11-02.
const RUNWAY = {
  as_of: "2026-10-27",
  events: [
    { date: "2026-11-01", name: "פרעון הלוואה", amount: -1844.42, kind: "loan", confidence: "inferred", balance_after: 1092.17 },
    { date: "2026-11-01", name: "פירעון הלוואה 4", amount: -666.72, kind: "loan", confidence: "inferred", balance_after: 425.45 },
    { date: "2026-11-02", name: "פירעון הלוואה 15500316168", amount: -306.47, kind: "loan", confidence: "inferred", balance_after: 118.98 },
    { date: "2026-11-10", name: "משכנתא", amount: -5817.26, kind: "loan", confidence: "inferred", balance_after: -5698.28 },
  ],
} as never;

describe("week strip", () => {
  it("starts today with Hebrew weekdays and groups each day's debits", () => {
    const days = weekDays(RUNWAY);
    expect(days).toHaveLength(7);
    expect(days[0]).toMatchObject({ date: "2026-10-27", dow: "ג׳", day: 27, today: true, events: [] });
    expect(days[5]).toMatchObject({ date: "2026-11-01", dow: "א׳", day: 1 });
    expect(days[5].events).toHaveLength(2);
    expect(initialDay(days)).toBe("2026-11-01");
  });

  it("names what comes after a quiet week", () => {
    const days = weekDays(RUNWAY);
    expect(nextBeyond(RUNWAY, days)?.name).toBe("משכנתא");
    expect(initialDay(weekDays({ as_of: "2026-11-03", events: [] }))).toBe("2026-11-03");
  });
});
