// Single source of truth for the digested pipeline outputs. These are imported
// statically (Vite resolves `@digested` to ../data/digested) so the app always
// renders whatever the last `python3 data/digest.py` produced.
import cashflowJson from "@digested/cashflow.json";
import snapshotJson from "@digested/snapshot.json";
import transactionsJson from "@digested/transactions.json";
import goalsJson from "@digested/goals.json";

export type Rank = "good" | "bad" | "warning" | null;

export interface Metric {
  key: string;
  name: string;
  value: number;
  units: "₪" | "%" | "" | string;
  rank: Rank;
  higher_is_better: boolean;
  description: string;
}

export interface Today {
  income: number;
  expense: number;
  net: number;
}

export interface FocalPoint {
  date?: string;
  age?: number;
  name?: string;
  asset_val?: number;
  loan_val?: number;
  net_val?: number;
}

export interface Projection {
  config?: Record<string, unknown>;
  net_worth_today?: number;
  net_worth_at_retirement?: number;
  total_loan_balance_today?: number;
  loans_modeled?: unknown[];
  focal_points?: FocalPoint[];
}

export interface PaceSide {
  month: string;
  income: number;
  expense: number;
  net: number;
  /** Whole-month spend (for the previous month: where it ended up). */
  month_expense: number;
  /** Cumulative spend per day-of-month. */
  daily_expense: number[];
}

/** Month-to-date vs. the previous month cut at the same day (cashflow.build_pace). */
export interface Pace {
  as_of_day: number;
  current: PaceSide;
  previous: PaceSide;
}

export interface Cashflow {
  generated_at: string;
  currency: string;
  current_month: string;
  note?: string;
  metrics: Metric[];
  today: Today;
  pace?: Pace;
  charts?: Record<string, unknown>;
  projection?: Projection;
  months?: unknown[];
}

export interface Loan {
  name?: string;
  balance?: number;
  rate?: number;
  monthly_payment?: number;
  [k: string]: unknown;
}

/**
 * A long-term savings vehicle (pension / study fund). These are assets, not
 * cashflow — they carry no transactions, so they never appear in the ledger.
 * `management_fee` / `yield_ytd` are null until the per-policy detail is
 * captured (see the harel-refresh skill's "known gap").
 */
export interface Savings {
  institution: string;
  kind: "pension" | "study_fund" | "provident_fund" | "savings" | "bank_deposit";
  /** Withdrawable today (e.g. a daily deposit) vs. locked until liquidity date. */
  liquid?: boolean;
  label: string;
  section?: string | null;
  policies_count?: number | null;
  balance: number;
  currency: string;
  management_fee?: number | null;
  yield_ytd?: number | null;
}

export interface SnapshotTotals {
  bank_balances_sum: number;
  credit_card_debt: number;
  mortgage_balance: number;
  consumer_loan_balance: number;
  total_debt: number;
  /** Liquid position vs debt — deliberately EXCLUDES long-term savings. */
  tracked_net_position: number;
  long_term_savings?: number;
  /** tracked_net_position + long_term_savings. */
  net_position_with_savings?: number;
  monthly_loan_service: number;
  detected_monthly_salary: number;
}

export interface Snapshot {
  generated_at: string;
  currency: string;
  note?: string;
  bank_accounts: unknown[];
  credit_cards: unknown[];
  loans: Loan[];
  savings?: Savings[];
  income?: unknown;
  transactions_count?: number;
  totals: SnapshotTotals;
  spending?: unknown;
}

export interface TxSummary {
  transactions: number;
  total_spent: number;
  total_income: number;
  by_category: Record<string, number>;
  by_origin: Record<string, number>;
}

export interface Transaction {
  date: string;
  amount: number;
  description?: string;
  category?: string;
  origin?: string;
  sources?: string[];
  [k: string]: unknown;
}

export interface Transactions {
  generated_at: string;
  currency: string;
  note?: string;
  summary: TxSummary;
  transactions: Transaction[];
}

export interface GeneralGoalCard {
  key: string;
  name: string;
  units: "%" | "₪" | string;
  value: number | null;
  status: "ok" | "needs_input";
  description: string;
  shortfall?: number | null;
  meets_target?: boolean | null;
  target?: number | null;
  target_derived?: boolean;
}

export interface PersonalGoal {
  id?: string;
  description: string;
  amount: number;
  end_date?: string | null;
  days_left?: number | null;
  progress_pct: number | null;
  on_track: boolean | null;
}

export interface Goals {
  generated_at: string;
  currency: string;
  note?: string;
  general: GeneralGoalCard[];
  personal_goals: PersonalGoal[];
  missing_piece: number;
  liquid_buffer: number;
}

/**
 * In dev these come from the Vite `@digested` alias — edit-reload still picks up
 * a fresh `python3 data/digest.py` with no copy step.
 *
 * In a production build they must NOT be bundled: the deployed artifact would
 * then contain every transaction and account number as readable static JS, which
 * no amount of auth in front of it can walk back. Instead `loadData()` fetches
 * them at runtime from /data/*.json in the private bucket, which CloudFront only
 * serves once the edge auth gate has validated a session.
 */
const BUNDLED = import.meta.env.DEV;

export let cashflow = (BUNDLED ? cashflowJson : {}) as unknown as Cashflow;
export let snapshot = (BUNDLED ? snapshotJson : {}) as unknown as Snapshot;
export let transactions = (BUNDLED ? transactionsJson : {}) as unknown as Transactions;
export let goals = (BUNDLED ? goalsJson : {}) as unknown as Goals;

/**
 * Populate the exports above before the app renders. Called from main.tsx and
 * awaited, so every route can keep importing the data synchronously.
 *
 * A failure here is surfaced, never swallowed: rendering a financial dashboard
 * against silently-empty data would show a plausible-looking ₪0 net worth.
 */
export async function loadData(): Promise<void> {
  if (BUNDLED) return;

  const get = async (name: string) => {
    const res = await fetch(`/data/${name}.json`, { credentials: "same-origin" });
    if (!res.ok) throw new Error(`${name}.json → HTTP ${res.status}`);
    return res.json();
  };

  const [c, s, t, g] = await Promise.all([
    get("cashflow"),
    get("snapshot"),
    get("transactions"),
    get("goals"),
  ]);

  cashflow = c as Cashflow;
  snapshot = s as Snapshot;
  transactions = t as Transactions;
  goals = g as Goals;
}

// --- Number formatting ------------------------------------------------------
// Every figure on screen goes through Intl.NumberFormat (he-IL) so separators,
// the ₪ position and the minus sign stay consistent. Instances are cached —
// constructing a formatter per render is the slow part.

const LOCALE = "he-IL";
const fmtCache = new Map<string, Intl.NumberFormat>();
function fmt(opts: Intl.NumberFormatOptions): Intl.NumberFormat {
  const key = JSON.stringify(opts);
  let f = fmtCache.get(key);
  if (!f) fmtCache.set(key, (f = new Intl.NumberFormat(LOCALE, opts)));
  return f;
}

/** ₪ formatter — ILS, no decimals, RTL-safe. */
export function shekel(n: number, opts: { decimals?: number } = {}): string {
  return fmt({ style: "currency", currency: "ILS", maximumFractionDigits: opts.decimals ?? 0 }).format(n);
}

/** Signed ₪ for deltas: +₪1,200 / -₪300 (zero stays unsigned). */
export function shekelSigned(n: number): string {
  return fmt({ style: "currency", currency: "ILS", maximumFractionDigits: 0, signDisplay: "exceptZero" }).format(n);
}

/** Compact ₪ for axes/large figures (₪2.6M). */
export function shekelCompact(n: number): string {
  return fmt({ style: "currency", currency: "ILS", notation: "compact", maximumFractionDigits: 1 }).format(n);
}

/** Percent from a 0–100 figure (the pipeline's convention): pct(66.6, 1) → "66.6%". */
export function pct(n: number, decimals = 0): string {
  return fmt({ style: "percent", maximumFractionDigits: decimals }).format(n / 100);
}

/** Plain grouped number: 2316 → "2,316". */
export function num(n: number, decimals = 0): string {
  return fmt({ maximumFractionDigits: decimals }).format(n);
}

/** A pipeline Metric's value in its own units. */
export function metricValue(m: Pick<Metric, "value" | "units">): string {
  if (m.units === "₪") return shekel(m.value);
  if (m.units === "%") return pct(m.value, 1);
  return num(m.value, 1);
}

/** Days since an ISO timestamp — used for the stale-data nudge. */
export function daysSince(iso: string): number {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return Infinity;
  return Math.floor((Date.now() - then) / 86_400_000);
}
