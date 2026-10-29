// The home band's lenses (docs/home-redesign.md): one big number, a delta that is shown only
// when both ends are measured, and a series ending in a "today" point. Pure functions over
// the digested JSON, so they are testable without fetching it.
import type { History, Pace, Runway, SnapshotTotals } from "./data";

export type LensKey = "spend" | "cash" | "networth" | "savings" | "debt";

/** One point of a lens chart. `actual` is measured (or rebuilt), `projected` is the forecast,
 *  `compare` a reference line (last month). The today point carries both actual and projected
 *  so the two lines meet. */
export interface LensPoint {
  x: string;
  actual?: number;
  projected?: number;
  compare?: number;
  /** Rebuilt from the ledger rather than read from the bank's running balance. */
  estimated?: boolean;
}

export interface Lens {
  key: LensKey;
  label: string;
  value: number;
  /** Change over the period, `good` when it is good news. Null unless both ends are measured. */
  delta: { amount: number; text: string; good: boolean } | null;
  series: LensPoint[];
  todayIndex: number;
  /** "הרחב" target; none when the home's own cards are the detail (net worth, debt). */
  to?: string;
  /** A quiet line under the chart: what the series is, or what is still missing. */
  note?: string;
}

/** Tabs, in reading order (RTL: the first is rightmost). */
export const LENS_ORDER: { key: LensKey; label: string }[] = [
  { key: "spend", label: "הוצאות" },
  { key: "cash", label: "מזומן" },
  { key: "networth", label: "שווי נקי" },
  { key: "savings", label: "חיסכון" },
  { key: "debt", label: "חובות" },
];

const CASH_PAST_DAYS = 30;

function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

function dayMonth(iso: string): string {
  return `${Number(iso.slice(8, 10))}.${Number(iso.slice(5, 7))}`;
}

/**
 * מזומן: the runway pool's last 30 days (history.cash) and the 45-day runway after today.
 * The delta compares today with the end of last month, only when that day was measured
 * from the bank's own running balance.
 */
export function cashLens(
  history: History | undefined,
  runway: Runway | undefined,
): Lens | null {
  if (!runway) return null;
  const today = runway.as_of;
  const measuredFrom = history?.cash.measured_from ?? null;
  const from = addDays(today, -CASH_PAST_DAYS);
  const past = (history?.cash.days ?? []).filter(
    (d) => d.date >= from && d.date < today,
  );
  const series: LensPoint[] = past.map((d) => ({
    x: d.date,
    actual: d.balance,
    estimated: measuredFrom == null || d.date < measuredFrom,
  }));
  const todayIndex = series.length;
  series.push({
    x: today,
    actual: runway.start_balance,
    projected: runway.start_balance,
  });
  for (const d of runway.days)
    if (d.date > today) series.push({ x: d.date, projected: d.balance });

  const monthEnd = addDays(`${today.slice(0, 7)}-01`, -1);
  const then = (history?.cash.days ?? []).find((d) => d.date === monthEnd);
  const measured =
    then != null && measuredFrom != null && monthEnd >= measuredFrom;
  const change = measured ? runway.start_balance - then.balance : null;

  const estimatedDays = past.filter(
    (d) => measuredFrom == null || d.date < measuredFrom,
  );
  return {
    key: "cash",
    label: "מזומן",
    value: runway.start_balance,
    delta:
      change == null
        ? null
        : { amount: change, text: "החודש", good: change >= 0 },
    series,
    todayIndex,
    to: "/monthly?view=forecast",
    note: estimatedDays.length
      ? `עד ${dayMonth(measuredFrom ?? today)} היתרה משוחזרת מהתנועות · משם לפי הבנק`
      : "יתרת העו״ש לפי הבנק · אחרי היום: תחזית",
  };
}

/**
 * הוצאות: this month's cumulative spend against last month's at the same day of the month.
 * Less than last month is the good direction.
 */
export function spendLens(pace: Pace | undefined): Lens | null {
  if (!pace) return null;
  const cur = pace.current.daily_expense;
  const prev = pace.previous.daily_expense;
  const days = Math.max(pace.days_in_month, prev.length);
  const series: LensPoint[] = Array.from({ length: days }, (_, i) => ({
    x: String(i + 1),
    actual: i < cur.length ? cur[i] : undefined,
    compare: i < prev.length ? prev[i] : undefined,
  }));
  const sameDay = prev[Math.min(pace.as_of_day, prev.length) - 1];
  const diff = sameDay != null ? pace.current.expense - sameDay : null;
  return {
    key: "spend",
    label: "הוצאות",
    value: pace.current.expense,
    delta:
      diff == null || Math.round(diff) === 0
        ? null
        : {
            amount: diff,
            text: diff < 0 ? "פחות מבחודש שעבר" : "יותר מבחודש שעבר",
            good: diff < 0,
          },
    series,
    todayIndex: Math.max(cur.length - 1, 0),
    to: "/monthly",
    note: "מצטבר מתחילת החודש · מקווקו: החודש שעבר באותו יום",
  };
}

/**
 * חובות: loan + mortgage principal at each month start, 12 months back (reverse-amortized, so
 * estimated) to 36 ahead on the schedules. No delta: the past is never measured here.
 */
export function debtLens(history: History | undefined): Lens | null {
  const pts = history?.debt ?? [];
  const i = pts.findIndex((p) => p.kind === "actual");
  if (i < 0) return null;
  const series: LensPoint[] = pts.map((p, k) => ({
    x: p.month,
    actual: k <= i ? p.total : undefined,
    projected: k >= i ? p.total : undefined,
    estimated: p.kind === "estimated",
  }));
  return {
    key: "debt",
    label: "חובות",
    value: pts[i].total,
    delta: null,
    series,
    todayIndex: i,
    note: "קרן ההלוואות והמשכנתא · לפני היום משוער, אחרי לפי לוח הסילוקין",
  };
}

/** The recorded days (history.positions), with the apartment held at its latest valuation on
 *  days recorded before it was typed in: the property is one manual value, so a jump on the
 *  day it was entered would be bookkeeping, not money. */
function positionDays(history: History | undefined) {
  const pts = history?.positions ?? [];
  const latest = [...pts].reverse().find((p) => p.property != null)?.property ?? null;
  return {
    latest,
    days: pts.map((p) => ({
      ...p,
      net_worth: p.net_worth != null && p.property == null && latest != null ? p.net_worth + latest : p.net_worth,
    })),
  };
}

/** A lens over the recorded days, ending at today. The change is measured against the first
 *  recorded day: both ends are the digest's own totals. */
function recordedLens(
  key: "networth" | "savings",
  label: string,
  days: { date: string; value: number }[],
  note: string,
): Lens | null {
  if (days.length < 2) return null;
  const first = days[0];
  const last = days.at(-1)!;
  const change = last.value - first.value;
  return {
    key,
    label,
    value: last.value,
    delta:
      Math.round(change) === 0
        ? null
        : { amount: change, text: `מאז ${dayMonth(first.date)}`, good: change > 0 },
    series: days.map((d) => ({ x: d.date, actual: d.value })),
    todayIndex: days.length - 1,
    to: key === "savings" ? "/overview?lens=savings&holdings=1" : undefined,
    note,
  };
}

/**
 * שווי נקי: cash + savings + the apartment − cards, loans and mortgage, one point per recorded
 * day. Without a property value it is the liquid-and-savings position (−₪900k), which is why
 * it only opens by default once the apartment is typed in (defaultLens).
 */
export function networthLens(history: History | undefined): Lens | null {
  const { latest, days } = positionDays(history);
  return recordedLens(
    "networth",
    "שווי נקי",
    days.flatMap((d) => (d.net_worth == null ? [] : [{ date: d.date, value: d.net_worth }])),
    latest == null
      ? "בלי שווי הדירה · יום אחד לכל עדכון נתונים"
      : "כולל הדירה לפי ההערכה האחרונה · יום אחד לכל עדכון נתונים",
  );
}

/** חיסכון: pension, study funds and provident funds, one point per recorded day. The funds
 *  report monthly, so the line moves in steps. */
export function savingsLens(history: History | undefined): Lens | null {
  const { days } = positionDays(history);
  return recordedLens(
    "savings",
    "חיסכון",
    days.map((d) => ({ date: d.date, value: d.savings })),
    "פנסיה, השתלמות וגמל · הקופות מדווחות פעם בחודש",
  );
}

// ---- the corner signal --------------------------------------------------------------

export type SignalMode = "ratio" | "safe";
export const SIGNAL_KEY = "home.signal";

/** The two faces of the corner signal: spent / income this month, and safe to spend until payday. */
export function signalValue(
  mode: SignalMode,
  pace: Pace | undefined,
  runway: Runway | undefined,
) {
  if (mode === "safe") {
    const safe = runway?.safe_to_spend;
    return safe == null
      ? null
      : {
          label: "בטוח להוציא עד המשכורת",
          value: safe,
          unit: "₪" as const,
          good: safe > 0,
        };
  }
  const income = pace?.current.income ?? 0;
  const expense = pace?.current.expense;
  if (expense == null || income <= 0) return null;
  const ratio = (expense / income) * 100;
  return {
    label: "הוצאות מתוך ההכנסה",
    value: ratio,
    unit: "%" as const,
    good: ratio <= 100,
  };
}

/** The stored face, "ratio" by default (decision 3). */
export function readSignalMode(
  storage: Pick<Storage, "getItem"> | undefined,
): SignalMode {
  return storage?.getItem(SIGNAL_KEY) === "safe" ? "safe" : "ratio";
}

// ---- default lens -------------------------------------------------------------------

export const LENS_KEY = "home.lens";

/**
 * Which lens opens (decision 4): a lens the household pinned, if it is available; else net
 * worth once a property value exists; else cash (−₪900k without the apartment would be a
 * misleading first number).
 */
export function defaultLens(
  available: LensKey[],
  totals: Pick<SnapshotTotals, "property_value"> | undefined,
  pinned: string | null,
): LensKey {
  if (pinned && available.includes(pinned as LensKey)) return pinned as LensKey;
  if (totals?.property_value != null && available.includes("networth"))
    return "networth";
  if (available.includes("cash")) return "cash";
  return available[0] ?? "cash";
}
