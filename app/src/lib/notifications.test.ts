import { describe, expect, it } from "vitest";
import type { HomeAction } from "./data";
import {
  badgeCount,
  categoryOf,
  detailChip,
  fromAction,
  fromApiNode,
  fromGlobalId,
  fromStatic,
  inTab,
  openItems,
  parseTab,
  snoozeUntil,
  tabCategories,
  toGlobalId,
  type ApiNode,
  type LocalState,
} from "./notifications";

const action = (over: Partial<HomeAction> = {}): HomeAction => ({
  id: "limit-breach-2026-10",
  severity: "high",
  title: "חריגה ממסגרת",
  detail: "העו״ש יורד מתחת למינוס",
  cta: { label: "לתחזית", to: "/monthly?view=forecast" },
  amount: -1200,
  ...over,
});

const local = (over: Partial<LocalState> = {}): LocalState => ({ archived: [], read: [], snoozed: {}, ...over });

describe("categoryOf", () => {
  it("defaults old JSON by severity", () => {
    expect(categoryOf({ severity: "critical" })).toBe("PROBLEM");
    expect(categoryOf({ severity: "high" })).toBe("WARNING");
    expect(categoryOf({ severity: "medium" })).toBe("WARNING");
    expect(categoryOf({ severity: "low" })).toBe("SUGGESTION");
  });
  it("prefers the published category", () => {
    expect(categoryOf({ severity: "low", category: "REMINDER" })).toBe("REMINDER");
  });
});

describe("global id", () => {
  it("is base64url of Notification:<id> without padding", () => {
    expect(toGlobalId("a")).toBe("Tm90aWZpY2F0aW9uOmE");
    expect(toGlobalId("sync-cal-failed-r1")).not.toMatch(/[=+/]/);
  });
  it("round-trips, Hebrew included", () => {
    for (const id of ["billOverdue-ארנונה-2026-10", "x", "ab"]) expect(fromGlobalId(toGlobalId(id))).toBe(id);
  });
  it("rejects other types and garbage", () => {
    expect(fromGlobalId(btoa("Transaction:1"))).toBeNull();
    expect(toGlobalId(12, "Goal")).toBe("R29hbDoxMg");
    expect(fromGlobalId(toGlobalId(12, "Goal"), "Goal")).toBe("12");
    expect(fromGlobalId(toGlobalId(12, "Goal"))).toBeNull();
    expect(fromGlobalId("%%%")).toBeNull();
  });
});

describe("fromAction / fromStatic", () => {
  it("maps old JSON with a default category and local state", () => {
    const n = fromAction(action(), local({ read: ["limit-breach-2026-10"] }));
    expect(n).toMatchObject({ category: "WARNING", type: "generic", live: false, subject: null });
    expect(n.readAt).not.toBeNull();
    expect(n.archivedAt).toBeNull();
  });
  it("keeps existing dismissals as archived", () => {
    const n = fromAction(action(), local({ archived: ["limit-breach-2026-10"] }));
    expect(n.archivedAt).not.toBeNull();
  });
  it("maps the subject to a detail chip", () => {
    const n = fromAction(action({ type: "billOverdue", subject: { kind: "bill", billName: "ארנונה", dueDate: "2026-10-10" } }));
    expect(n.subject).toEqual({ kind: "bill", billName: "ארנונה", dueDate: "2026-10-10" });
    expect(detailChip(n)).toContain("ארנונה");
  });
  it("puts live sync alerts first, always as PROBLEM", () => {
    const live = action({ id: "sync-cal-failed-r1", severity: "medium" });
    const list = fromStatic([live], [action({ severity: "low" })], local());
    expect(list.map((n) => [n.id, n.category, n.live])).toEqual([
      ["sync-cal-failed-r1", "PROBLEM", true],
      ["limit-breach-2026-10", "SUGGESTION", false],
    ]);
  });
});

describe("fromApiNode", () => {
  const node: ApiNode = {
    __typename: "SyncNotification",
    id: toGlobalId("staleData-2026-10"),
    type: "staleData",
    category: "WARNING",
    severity: "MEDIUM",
    title: "נתונים לא עדכניים",
    detail: null,
    amount: "12.50",
    cta: null,
    createdAt: "2026-10-26T08:00:00Z",
    readAt: null,
    snoozedUntilAt: null,
    archivedAt: null,
    sources: ["cal", "leumi"],
  };
  it("uses the action id, lowercases severity, parses money and the subtype", () => {
    const n = fromApiNode(node);
    expect(n).toMatchObject({ id: "staleData-2026-10", severity: "medium", amount: 12.5, live: false });
    expect(detailChip(n)).toBe("cal · leumi");
  });
});

describe("tabs", () => {
  const list = [
    fromAction(action({ id: "1", category: "PROBLEM" })),
    fromAction(action({ id: "2", category: "WARNING" })),
    fromAction(action({ id: "3", category: "INFO" })),
    fromAction(action({ id: "4", severity: "low" })),
  ];
  it("filters by category; all includes INFO", () => {
    expect(inTab(list, "problems").map((n) => n.id)).toEqual(["1"]);
    expect(inTab(list, "suggestions").map((n) => n.id)).toEqual(["4"]);
    expect(inTab(list, "all")).toHaveLength(4);
  });
  it("parses ?tab= and falls back to all", () => {
    expect(parseTab("suggestions")).toBe("suggestions");
    expect(parseTab("nope")).toBe("all");
    expect(parseTab(null)).toBe("all");
  });
  it("maps a tab to bulk-mutation categories", () => {
    expect(tabCategories("warnings")).toEqual(["WARNING"]);
    expect(tabCategories("all")).toBeUndefined();
  });
  it("hides archived and snoozed items from the open list", () => {
    const now = Date.parse("2026-10-26T10:00:00Z");
    const items = [
      fromAction(action({ id: "a" }), local({ archived: ["a"] })),
      fromAction(action({ id: "b" }), local({ snoozed: { b: "2026-10-27T08:00:00Z" } })),
      fromAction(action({ id: "c" }), local({ snoozed: { c: "2026-10-25T08:00:00Z" } })),
    ];
    expect(openItems(items, now).map((n) => n.id)).toEqual(["c"]);
  });
});

describe("badgeCount", () => {
  it("counts only unread open PROBLEM and WARNING", () => {
    const list = [
      fromAction(action({ id: "1", category: "PROBLEM" })),
      fromAction(action({ id: "2", category: "WARNING" }), local({ read: ["2"] })),
      fromAction(action({ id: "3", category: "WARNING" }), local({ archived: ["3"] })),
      fromAction(action({ id: "4", category: "REMINDER" })),
      fromAction(action({ id: "5", severity: "medium" })),
    ];
    expect(badgeCount(list)).toBe(2);
  });
});

describe("snoozeUntil", () => {
  const now = new Date(2026, 9, 26, 15, 0);
  it("tomorrow and week land at 08:00", () => {
    expect(new Date(snoozeUntil("tomorrow", now)).getDate()).toBe(27);
    expect(new Date(snoozeUntil("week", now)).getDate()).toBe(2);
    expect(new Date(snoozeUntil("week", now)).getHours()).toBe(8);
  });
  it("payday uses the date, or a week when missing or past", () => {
    expect(new Date(snoozeUntil("payday", now, "2026-11-01")).getDate()).toBe(1);
    expect(snoozeUntil("payday", now, null)).toBe(snoozeUntil("week", now));
    expect(snoozeUntil("payday", now, "2026-10-01")).toBe(snoozeUntil("week", now));
  });
});
