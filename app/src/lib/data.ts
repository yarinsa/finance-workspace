// Single source of truth for the digested pipeline outputs. They are fetched at
// runtime from /data/*.json — never bundled — so the app bundle carries no
// financial data and can be built and deployed by CI, while the data itself is
// published separately from the machine that ran `python3 data/digest.py`
// (`infra/deploy.sh --data-only`). In dev/preview, vite.config.ts serves
// /data/* straight from ../data/digested.

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

export interface Cashflow {
  generated_at: string;
  currency: string;
  current_month: string;
  note?: string;
  metrics: Metric[];
  today: Today;
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
  kind: "pension" | "study_fund" | "savings";
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

async function loadDigested<T>(name: string): Promise<T> {
  const res = await fetch(`/data/${name}.json`, { cache: "no-store" });
  // A missing key comes back as the SPA's index.html (CloudFront maps S3's
  // 403/404 to it), so check the content type, not just the status.
  if (!res.ok || !res.headers.get("content-type")?.includes("json")) {
    throw new Error(`data/${name}.json not available — run python3 data/digest.py and publish it`);
  }
  return (await res.json()) as T;
}

export const [cashflow, snapshot, transactions, goals] = await Promise.all([
  loadDigested<Cashflow>("cashflow"),
  loadDigested<Snapshot>("snapshot"),
  loadDigested<Transactions>("transactions"),
  loadDigested<Goals>("goals"),
]);

/** ₪ formatter — ILS, no decimals, RTL-safe. */
export function shekel(n: number, opts: { decimals?: number } = {}): string {
  return new Intl.NumberFormat("he-IL", {
    style: "currency",
    currency: "ILS",
    maximumFractionDigits: opts.decimals ?? 0,
  }).format(n);
}

/** Compact ₪ for axes/large figures (₪2.6M). */
export function shekelCompact(n: number): string {
  return new Intl.NumberFormat("he-IL", {
    style: "currency",
    currency: "ILS",
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(n);
}

export function pct(n: number, decimals = 0): string {
  return `${n.toFixed(decimals)}%`;
}

/** Days since an ISO timestamp — used for the stale-data nudge. */
export function daysSince(iso: string): number {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return Infinity;
  return Math.floor((Date.now() - then) / 86_400_000);
}
