import { overlayFor, type Overlay } from "./ledgerOverlay";

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

export type RangeSpec = { kind: "days"; days: number } | { kind: "custom"; from: string; to: string };

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
export function parseRange(p: { days?: string | null; from?: string | null; to?: string | null }): RangeSpec {
  if (isRealDay(p.from) && isRealDay(p.to)) {
    return p.from <= p.to ? { kind: "custom", from: p.from, to: p.to } : { kind: "custom", from: p.to, to: p.from };
  }
  const days = Number(p.days);
  return { kind: "days", days: (PRESET_DAYS as readonly number[]).includes(days) ? days : DEFAULT_DAYS };
}

/** The inclusive day window. Presets end today (future-dated rows fall outside); custom is taken as given. */
export function resolveRange(spec: RangeSpec, today: string): { from: string; to: string } {
  if (spec.kind === "custom") return { from: spec.from, to: spec.to };
  return { from: addDays(today, -(spec.days - 1)), to: today };
}

/** Range -> URL params; the default (30 days) is omitted so the bare URL stays clean. */
export function rangeToParams(spec: RangeSpec): Record<string, string> {
  if (spec.kind === "custom") return { from: spec.from, to: spec.to };
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
