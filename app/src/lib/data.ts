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

export interface SnapshotTotals {
  bank_balances_sum: number;
  credit_card_debt: number;
  mortgage_balance: number;
  consumer_loan_balance: number;
  total_debt: number;
  tracked_net_position: number;
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

export const cashflow = cashflowJson as unknown as Cashflow;
export const snapshot = snapshotJson as unknown as Snapshot;
export const transactions = transactionsJson as unknown as Transactions;
export const goals = goalsJson as unknown as Goals;

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
