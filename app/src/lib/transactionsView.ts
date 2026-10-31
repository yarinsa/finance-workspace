import type { BudgetCategory } from "./budgets";
import { overlayFor, type Overlay } from "./ledgerOverlay";
import type { ChargeItem, SpendCard } from "./monthList";

/** A digested-ledger row, as far as the "תנועות" screen reads it (money out negative). */
export interface LedgerRow {
  date: string;
  amount: number;
  merchant?: string;
  description?: string;
  category?: string;
  tags?: string[];
  origin?: string;
  card_last4?: string;
  account_id?: string;
  kind?: string;
  card_bill_payment?: boolean;
  internal_transfer?: boolean;
  /** ₪ paid back (קיזוז). */
  offset_amount?: number;
  overridden?: boolean;
}

/** A ledger row after the live edit overlay: the effective category, tags and edited flag. */
export interface ViewRow extends LedgerRow {
  category: string;
  tags: string[];
  overridden: boolean;
}

export const PRESET_DAYS = [30, 60, 90, 180, 360] as const;
export const DEFAULT_DAYS = 30;

/** `cycle` is the current budget cycle (budgets.cycle_start .. cycle_end): the only range with plans and bill statuses. */
export type RangeSpec =
  | { kind: "days"; days: number }
  | { kind: "custom"; from: string; to: string }
  | { kind: "cycle" };

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

/** Add whole days to an ISO day (UTC arithmetic, so DST never shifts a day). */
export function addDays(iso: string, n: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

/** Today's date in the viewer's local time zone, as YYYY-MM-DD. */
export function todayIso(now: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}`;
}

const isRealDay = (s: string | null | undefined): s is string =>
  !!s && ISO_DAY.test(s) && addDays(s, 0) === s;

/** URL params -> range. Unknown or malformed values fall back to the 30-day default. */
export function parseRange(p: { days?: string | null; from?: string | null; to?: string | null; range?: string | null }): RangeSpec {
  if (p.range === "cycle") return { kind: "cycle" };
  if (isRealDay(p.from) && isRealDay(p.to)) {
    return p.from <= p.to ? { kind: "custom", from: p.from, to: p.to } : { kind: "custom", from: p.to, to: p.from };
  }
  const days = Number(p.days);
  return { kind: "days", days: (PRESET_DAYS as readonly number[]).includes(days) ? days : DEFAULT_DAYS };
}

/**
 * The inclusive day window. Presets end today (future-dated rows fall outside); custom is taken
 * as given; the cycle is the budget's own bounds, or the 30-day default when there is no budget.
 */
export function resolveRange(spec: RangeSpec, today: string, cycle?: { from: string; to: string } | null): { from: string; to: string } {
  if (spec.kind === "custom") return { from: spec.from, to: spec.to };
  if (spec.kind === "cycle") return cycle ?? resolveRange({ kind: "days", days: DEFAULT_DAYS }, today);
  return { from: addDays(today, -(spec.days - 1)), to: today };
}

/** Range -> URL params; the default (30 days) is omitted so the bare URL stays clean. */
export function rangeToParams(spec: RangeSpec): Record<string, string> {
  if (spec.kind === "custom") return { from: spec.from, to: spec.to };
  if (spec.kind === "cycle") return { range: "cycle" };
  return spec.days === DEFAULT_DAYS ? {} : { days: String(spec.days) };
}

/**
 * The account a row belongs to. Today that is the institution (`origin`); step 4 (limit
 * bars per card) will refine it with `card_last4` / `account_id`, which is why it is one function.
 */
export function accountKey(t: Pick<LedgerRow, "origin">): string {
  return t.origin || "other";
}

export function accountLabel(key: string, labelOf: (source: string) => string): string {
  return key === "other" ? "אחר" : labelOf(key);
}

/**
 * The visible rows: card-bill payments and internal transfers are hidden (they duplicate the
 * card rows), rows the overlay excludes are dropped, and the overlay's category / tags win.
 */
export function applyView(rows: readonly LedgerRow[], overlay: Overlay): ViewRow[] {
  const out: ViewRow[] = [];
  for (const t of rows) {
    if (t.card_bill_payment || t.internal_transfer) continue;
    const o = overlayFor(overlay, t);
    if (o?.excluded) continue;
    out.push({
      ...t,
      category: o?.category || t.category || "",
      tags: o?.tags ?? t.tags ?? [],
      overridden: o ? o.overridden : !!t.overridden,
    });
  }
  return out;
}

/** Rows whose date falls in the inclusive window, newest first (stable for equal dates). */
export function inRange<T extends Pick<LedgerRow, "date">>(rows: readonly T[], range: { from: string; to: string }): T[] {
  return rows
    .filter((t) => {
      const d = t.date.slice(0, 10);
      return d >= range.from && d <= range.to;
    })
    .map((t, i) => ({ t, i }))
    .sort((a, b) => b.t.date.slice(0, 10).localeCompare(a.t.date.slice(0, 10)) || a.i - b.i)
    .map((x) => x.t);
}

/** Per-account row counts for the chips, most rows first. */
export function accountCounts(rows: readonly LedgerRow[]): { key: string; count: number }[] {
  const m = new Map<string, number>();
  for (const t of rows) m.set(accountKey(t), (m.get(accountKey(t)) ?? 0) + 1);
  return [...m].map(([key, count]) => ({ key, count })).sort((a, b) => b.count - a.count || a.key.localeCompare(b.key));
}

export function filterByAccount<T extends LedgerRow>(rows: readonly T[], account: string | null): T[] {
  return account ? rows.filter((t) => accountKey(t) === account) : [...rows];
}

/** What a row is worth after its offset (קיזוז), signed like the ledger. */
export function netAmount(t: Pick<LedgerRow, "amount" | "offset_amount">): number {
  const off = t.offset_amount ?? 0;
  return t.amount < 0 ? t.amount + off : t.amount - off;
}

/** Count, total out (positive ₪) and total in for a set of rows, after offsets. */
export function totals(rows: readonly LedgerRow[]): { count: number; out: number; in: number } {
  let out = 0;
  let inn = 0;
  for (const t of rows) {
    const n = netAmount(t);
    if (n < 0) out -= n;
    else inn += n;
  }
  return { count: rows.length, out, in: inn };
}

/** Stable key of the current filter, to reset paging when it changes. */
export const filterKey = (range: { from: string; to: string }, account: string | null): string =>
  `${range.from}|${range.to}|${account ?? ""}`;

/** Rows shown before "הצג עוד", and how many each tap adds. */
export const PAGE_SIZE = 100;

/** ?account= -> the selected account, or null ("הכל") when absent or not among the chips. */
export function parseAccount(raw: string | null | undefined, keys: readonly string[]): string | null {
  return raw && keys.includes(raw) ? raw : null;
}

export interface WidgetStats {
  /** Positive ₪ out / in, after offsets. */
  out: number;
  in: number;
  net: number;
  /** Money out by the ledger's `kind`; rows with no kind (loans, pension, untyped) land in `other`. */
  split: { fixed: number; variable: number; other: number };
  /** The largest spending categories, positive ₪, at most `top`. */
  topCategories: { name: string; amount: number }[];
}

/** Figures for the widgets carousel, computed from the filtered rows so they follow every filter. */
export function widgetStats(rows: readonly LedgerRow[], top = 3): WidgetStats {
  const { out, in: inn } = totals(rows);
  const split = { fixed: 0, variable: 0, other: 0 };
  const byCat = new Map<string, number>();
  for (const t of rows) {
    const n = netAmount(t);
    if (n >= 0) continue;
    const k = t.kind === "fixed" || t.kind === "variable" ? t.kind : "other";
    split[k] -= n;
    const name = t.category || "ללא קטגוריה";
    byCat.set(name, (byCat.get(name) ?? 0) - n);
  }
  const topCategories = [...byCat]
    .map(([name, amount]) => ({ name, amount }))
    .sort((a, b) => b.amount - a.amount || a.name.localeCompare(b.name))
    .slice(0, top);
  return { out, in: inn, net: inn - out, split, topCategories };
}

export type GroupBy = "none" | "category" | "kind";

export function parseGroup(raw: string | null | undefined): GroupBy {
  return raw === "category" || raw === "kind" ? raw : "none";
}

/** The current cycle's plan for one spending card, as the group header reads it. */
export interface CyclePlan {
  /** fixed paid + fixed still expected + the variable plan; null when nothing is planned. */
  planned: number | null;
  /** The variable budget line, for the plan editor. */
  budget?: BudgetCategory;
  /** Fixed charges not charged yet this cycle (upcoming or overdue). */
  pending: ChargeItem[];
  /** A utility's bill status. */
  bill?: ChargeItem;
}

/**
 * The cycle's plans keyed by card name (`buildCards`), plus `alias`: a row category -> the
 * card that holds it when a group-scope budget line covers several (רכב, דלק -> תחבורה).
 */
export function cyclePlans(cards: readonly SpendCard[]): { plans: Map<string, CyclePlan>; alias: Map<string, string> } {
  const plans = new Map<string, CyclePlan>();
  const alias = new Map<string, string>();
  for (const c of cards) {
    const lines = [...c.fixedLines, ...c.variableLines];
    for (const l of c.variableLines) for (const part of l.parts ?? []) if (part !== c.name) alias.set(part, c.name);
    plans.set(c.name, {
      planned: c.planned,
      budget: c.variableLines.find((l) => l.budget)?.budget,
      pending: c.fixedLines.flatMap((l) => (l.charge && l.charge.status !== "paid" ? [l.charge] : [])),
      bill: lines.find((l) => l.bill)?.bill,
    });
  }
  return { plans, alias };
}

/** One group of the list: its rows (newest first, as given) and its money, positive ₪. */
export interface RowGroup {
  key: string;
  label: string;
  rows: ViewRow[];
  out: number;
  in: number;
  /** Money out by kind, for the header's StackedBar. */
  fixed: number;
  variable: number;
}

export const KIND_GROUPS = [
  { key: "fixed", label: "קבוע" },
  { key: "variable", label: "משתנה" },
  { key: "other", label: "אחר" },
  { key: "income", label: "הכנסות" },
] as const;

const UNCATEGORISED = "ללא קטגוריה";

/**
 * Split rows into groups. `category`: by the row's (overlay) category, folded into its card via
 * `alias`, biggest spend first and income-only groups last. `kind`: money out by the ledger's
 * kind (kindless -> אחר), money in as הכנסות, in that fixed order. Empty groups are dropped.
 */
export function groupRows(rows: readonly ViewRow[], by: Exclude<GroupBy, "none">, alias: ReadonlyMap<string, string> = new Map()): RowGroup[] {
  const groups = new Map<string, RowGroup>();
  const keyOf = (t: ViewRow, n: number): [string, string] => {
    if (by === "kind") {
      const k = n > 0 ? "income" : t.kind === "fixed" || t.kind === "variable" ? t.kind : "other";
      return [k, KIND_GROUPS.find((g) => g.key === k)!.label];
    }
    const name = alias.get(t.category) ?? (t.category || UNCATEGORISED);
    return [name, name];
  };
  for (const t of rows) {
    const n = netAmount(t);
    const [key, label] = keyOf(t, n);
    const g = groups.get(key) ?? { key, label, rows: [], out: 0, in: 0, fixed: 0, variable: 0 };
    g.rows.push(t);
    if (n < 0) {
      g.out -= n;
      if (t.kind === "fixed") g.fixed -= n;
      else if (t.kind === "variable") g.variable -= n;
    } else g.in += n;
    groups.set(key, g);
  }
  const list = [...groups.values()];
  if (by === "kind") return KIND_GROUPS.flatMap((k) => list.filter((g) => g.key === k.key));
  return list.sort((a, b) => b.out - a.out || b.in - a.in || a.label.localeCompare(b.label));
}
