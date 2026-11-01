// Single source of truth for the digested pipeline outputs. They are fetched at
// runtime from /data/*.json — never bundled — so the app bundle carries no
// financial data and can be built and deployed by CI, while the data itself is
// published separately from the machine that ran `python3 data/digest.py`
// (`infra/deploy.sh --data-only`). In dev/preview, vite.config.ts serves
// /data/* straight from ../data/digested.

import { useSyncExternalStore } from "react";
import { setAppStatus } from "./appStatus";
import { FRESH_HEADER } from "./swRoutes";
import { dataUrl } from "./tenant";
import {
  SessionExpiredError,
  isExpiredNetworkError,
  isSessionExpired,
} from "./dataFetch";

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
  /** Top spending categories to date, "אחר" last. */
  by_category?: { name: string; amount: number }[];
}

/** Mean of the trailing months the ledger covers, each cut at the same day. */
export interface PaceAverage {
  months: number;
  income: number;
  expense: number;
  month_expense: number;
  daily_expense: number[];
}

/** Month-to-date vs. the previous month cut at the same day (cashflow.build_pace). */
export interface Pace {
  as_of_day: number;
  days_in_month: number;
  current: PaceSide;
  previous: PaceSide;
  average?: PaceAverage | null;
  /** Full-month expectation from forecast.py's budget envelopes; null when stale/missing. */
  expected?: {
    income: number;
    expense: number;
    net: number;
    source: string;
  } | null;
}

export interface FixedItem {
  name: string;
  category?: string | null;
  group?: string | null;
  /** "debt_savings" for loans and the mortgage. */
  block?: "fixed" | "debt_savings";
  amount: number;
  /** A monthly charge that has not hit yet this month (seen the two months before). */
  expected?: boolean;
  duplicate: boolean;
  duplicate_reason?: string | null;
  /** Latest matching ledger charge (YYYY-MM-DD), null when none was found. */
  last_charged?: string | null;
}

/** This month's fixed expenses (ledger kind "fixed") grouped for a "what can I cut?" review (cashflow.fixed_expenses). */
export interface FixedExpenses {
  month: string;
  total: number;
  /** Fees + subscriptions — the low-effort ceiling. */
  cuttable_total: number;
  groups: {
    key: string;
    label: string;
    ease: "trivial" | "easy" | "moderate" | "wait" | "committed";
    lever: string;
    total: number;
    items: FixedItem[];
  }[];
}

/** Day-by-day projection of the combined checking balance (cashflow.runway). */
export interface Runway {
  as_of: string;
  horizon_end: string;
  currency: string;
  start_balance: number;
  overdraft_limit: number;
  floor: number;
  accounts: {
    institution: string;
    balance: number;
    overdraft_limit?: number;
  }[];
  liquid_buffer: { label: string; balance: number }[];
  next_payday: { date: string; amount: number; name: string } | null;
  events: {
    date: string;
    name: string;
    amount: number;
    kind: "income" | "loan" | "card" | "housing" | "bill";
    category?: string | null;
    confidence: "known" | "inferred";
    balance_after: number;
  }[];
  days: { date: string; balance: number }[];
  low_point: { date: string; balance: number };
  low_before_payday: { date: string; balance: number } | null;
  first_floor_breach: string | null;
  first_limit_breach: string | null;
  days_to_payday: number | null;
  safe_to_spend: number | null;
  safe_per_day: number | null;
  headroom_to_limit: number | null;
  note: string;
}

/** One prioritised to-do for the home screen (cashflow.actions, built by the pipeline). */
export interface HomeAction {
  id: string;
  severity: "critical" | "high" | "medium" | "low";
  title: string;
  detail: string;
  cta: { label: string; to: string } | null;
  amount: number | null;
  /** Inbox bucket; absent in data published before categories existed (see `categoryOf`). */
  category?: "PROBLEM" | "WARNING" | "REMINDER" | "SUGGESTION" | "INFO";
  /** Which rule produced it (limitBreach, billOverdue, ...). */
  type?: string;
  /** What the item is about; `kind` picks the detail chip. */
  subject?:
    | ({
        kind:
          "cashflow" | "budget" | "bill" | "service" | "sync" | "transaction";
      } & Record<string, unknown>)
    | null;
}

export interface Cashflow {
  generated_at: string;
  currency: string;
  current_month: string;
  note?: string;
  metrics: Metric[];
  today: Today;
  pace?: Pace;
  fixed_expenses?: FixedExpenses | null;
  runway?: Runway;
  /** "לטיפול" list on the home screen; absent until the pipeline emits it. */
  actions?: HomeAction[];
  bills?: import("./bills").Bills | null;
  budgets?: import("./budgets").Budgets | null;
  spending?: import("./spending").SpendingData;
  charts?: Record<string, unknown>;
  projection?: Projection;
  months?: unknown[];
  /** Month-by-month cashflow (past actuals, current month, projected months); absent until the pipeline emits it. */
  months_view?: MonthsView;
  /** Net income split across current / near-future / future me (data/horizons.py); absent until emitted. */
  horizons?: Horizons;
  /** How the money got here (data/history.py), for the home lenses; absent in older data. */
  history?: History;
}

/** End-of-day pool balance; days before `measured_from` are rebuilt from the ledger (estimated). */
export interface CashHistory {
  as_of: string;
  days: { date: string; balance: number }[];
  measured_from: string | null;
}

export interface DebtPoint {
  month: string; // "2026-10"
  mortgage: number;
  consumer: number;
  total: number;
  kind: "estimated" | "actual" | "projected";
}

/** One recorded day of the household's position (Postgres position_snapshots). */
export interface PositionPoint {
  date: string;
  cash: number;
  /** null before 2026-10-28: those days used another source for card debt (history.py). */
  card_debt: number | null;
  consumer_loans: number;
  mortgage: number;
  savings: number;
  property: number | null;
  net_worth: number | null;
}

export interface History {
  cash: CashHistory;
  debt: DebtPoint[];
  positions: PositionPoint[];
}

export interface HorizonBucket {
  amount: number;
  /** Share of the month's net income, in percent; null while the month has no income yet. */
  pct: number | null;
  /** pct minus target_pct, in percentage points; null when pct is. */
  gap_pts: number | null;
  count: number;
  /** The target share of income for this horizon (the `horizons` table), in percent. */
  target_pct?: number;
  /** `amount` is the real charge (the row key); `offset` is the ₪ paid back and netted out of `amount` totals. */
  top: {
    date: string;
    description: string;
    amount: number;
    category?: string | null;
    overridden: boolean;
    tags?: string[];
    goal?: string | null;
    offset?: number;
  }[];
}

/** A goal as listed under the horizon it is assigned to. */
export interface HorizonGoal {
  id: number | string;
  description: string;
  amount: number;
  end_date?: string | null;
}

export interface Horizons {
  target_pct: number;
  horizons: ("current" | "near" | "future")[];
  /** Labels from the `horizons` table; empty without the database. */
  names?: Partial<Record<"current" | "near" | "future", string>>;
  targets?: Record<"current" | "near" | "future", number>;
  /** Goals assigned to each horizon. */
  goals?: Record<"current" | "near" | "future", HorizonGoal[]>;
  /** Newest first. */
  months: {
    month: string;
    income: number;
    buckets: Record<"current" | "near" | "future", HorizonBucket>;
    unallocated: { amount: number; pct: number | null };
  }[];
}

export interface MonthGroup {
  key: "income" | "fixed" | "variable" | "debt_savings";
  label: string;
  expected: number | null;
  actual: number | null;
}

export interface MonthViewRow {
  month: string; // "2026-10"
  kind: "actual" | "current" | "projected";
  /** Positive magnitudes; net = income − expense. */
  income: number;
  expense: number;
  net: number;
  /** Current month only: where the month is expected to land. */
  projected_end: { income: number; expense: number; net: number } | null;
  groups: MonthGroup[];
  /** Empty for projected months. */
  categories: { name: string; amount: number; count: number }[];
}

export interface MonthsView {
  current: string;
  /** Oldest → newest. */
  months: MonthViewRow[];
}

export interface Loan {
  lender?: string;
  name?: string;
  category?: "mortgage" | "consumer" | string;
  balance?: number;
  rate_pct?: number;
  rate_type?: "fixed" | "variable" | string;
  index_linked?: boolean;
  monthly_payment?: number;
  payments_remaining?: number;
  payments_total?: number;
  original_amount?: number | null;
  loan_id?: string;
  /** '20530810' (Discount) or '2028-12-02' (Leumi). */
  final_date?: string;
  [k: string]: unknown;
}

/**
 * A long-term savings vehicle (pension / study fund). These are assets, not
 * cashflow — they carry no transactions, so they never appear in the ledger.
 * `management_fee` / `yield_ytd` are null until the per-policy detail is
 * captured (see the refresh skill's references/harel.md "known gap").
 */
/** A debt-bearing card in the snapshot (RiseUp's, with the issuers' roster names by last4). */
export interface CreditCard {
  issuer: string;
  last4: string;
  name?: string | null;
  holder?: string | null;
  /** What the card will charge next, from the issuer's own rows (RiseUp's balance only for a card
   *  no issuer dump covers). */
  owed: number;
  /** The day that charge is billed, ISO; absent for a RiseUp-only card. */
  next_charge_date?: string | null;
  currency: string;
}

/** A checking account in the snapshot (direct scrape wins over RiseUp's copy). */
export interface BankAccount {
  institution: string;
  /** Usually the account number; the business account carries its holder's name. */
  account_id: string;
  kind: string;
  label?: string;
  balance: number;
  currency: string;
  available_balance?: number | null;
  overdraft_limit?: number | null;
}

export interface Savings {
  institution: string;
  kind:
    "pension" | "study_fund" | "provident_fund" | "savings" | "bank_deposit";
  /** Withdrawable today (e.g. a daily deposit) vs. locked until liquidity date. */
  liquid?: boolean;
  label: string;
  section?: string | null;
  policies_count?: number | null;
  /** "עצמאי" / "שכיר" on self-employed vs salaried funds (More, Analyst). */
  work_state?: string | null;
  /** The vendor's id for the fund; with `institution` it identifies a holding. */
  topic_id?: string | null;
  /** When a locked fund can be withdrawn; absent for Harel's funds. */
  liquidity_date?: string | null;
  /** The date the balance was read. */
  as_of?: string | null;
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
  /** Withdrawable deposits (e.g. נזיל יומי+), part of long_term_savings. */
  liquid_savings?: number;
  /** tracked_net_position + long_term_savings. */
  net_position_with_savings?: number;
  /** The apartment's hand-typed value (assets table); null until entered. */
  property_value?: number | null;
  /** net_position_with_savings + property_value; null without a property value. */
  net_worth_with_property?: number | null;
  monthly_loan_service: number;
  detected_monthly_salary: number;
}

export interface SnapshotAsset {
  id: number;
  kind: "property";
  label: string;
  value: number;
  valued_at: string;
  valuation_source: "manual" | "estimate";
}

export interface Snapshot {
  generated_at: string;
  currency: string;
  note?: string;
  /** Hand-typed assets (the apartment); null/absent without the database. */
  assets?: SnapshotAsset[] | null;
  bank_accounts: BankAccount[];
  credit_cards: CreditCard[];
  loans: Loan[];
  savings?: Savings[];
  /** Where the user placed each holding (holdingId -> horizon / goal), written by the digest. */
  holding_assignments?: Record<string, { horizon: "current" | "near" | "future" | null; goal_id: number | null }>;
  income?: unknown;
  transactions_count?: number;
  totals: SnapshotTotals;
  spending?: unknown;
  syncs?: SourceSync[];
  /** Each sync source's self-declaration (data/<source>/manifest.json). */
  source_manifests?: Record<string, SourceManifest>;
}

/** What a source says about itself: its label, the kinds of account it holds, the entities it provides. */
export interface SourceManifest {
  name: string;
  label: string;
  account_types: string[];
  capabilities: string[];
  /** JSON Schema of the connection form; `x-env` names the .env variable behind a field. */
  connection: Record<string, unknown>;
}

/** A source's Hebrew label from its manifest; the id itself when it has none (e.g. RiseUp). */
export function sourceLabel(source: string): string {
  return snapshot.source_manifests?.[source]?.label ?? source;
}

/** Per-source data freshness (digest.source_syncs). */
export interface SourceSync {
  source: string;
  label?: string;
  account_types?: string[];
  capabilities?: string[];
  /** Newest raw-dump mtime — when the scraper last wrote, not when digest ran. */
  last_synced: string;
  raw_files: number;
  /** Record count per normalized entity. */
  entities: Record<string, number>;
  /** Newest transaction the source carries; null for savings/loan-only sources. */
  latest_txn_date: string | null;
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
  /** Id in the DB `categories` table (RiseUp-seeded); absent when uncategorised. */
  category_id?: number;
  /** Tag names from the DB `transaction_tags` table, sorted; absent when untagged. */
  tags?: string[];
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
  /** The `goals` table id (editable through the API); absent when read from the JSON store. */
  goal_id?: number | null;
  horizon?: "current" | "near" | "future" | null;
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

/** One month of forecast.py's projection (RiseUp envelopes; month 1 high-confidence). */
export interface ForecastMonth {
  forecast_month: string;
  confidence: "high" | "carry-forward" | string;
  projected_net: number;
  income: { total: number };
  expenses: { total: number; fixed_total: number; discretionary_total: number };
}

export interface Forecast {
  generated_for?: string;
  horizon_months: number;
  months: ForecastMonth[];
}

/**
 * When the data was last fetched, and whether the service worker answered from its cache
 * (no network) instead — `cachedAt` is then when that copy was saved.
 */
export const dataMeta: {
  fetchedAt: number;
  fromCache: boolean;
  cachedAt: number | null;
} = {
  fetchedAt: Date.now(),
  fromCache: false,
  cachedAt: null,
};

async function loadDigested<T>(name: string, fresh = false): Promise<T> {
  let res: Response;
  try {
    res = await fetch(dataUrl(name), {
      cache: "no-store",
      headers: fresh ? { [FRESH_HEADER]: "1" } : undefined,
    });
  } catch (err) {
    if (isExpiredNetworkError(err, navigator.onLine)) {
      void clearCachedData();
      throw new SessionExpiredError();
    }
    throw err;
  }
  if (
    isSessionExpired({
      status: res.status,
      redirected: res.redirected,
      type: res.type,
      contentType: res.headers.get("content-type"),
    })
  ) {
    void clearCachedData();
    throw new SessionExpiredError();
  }
  // A missing key comes back as the SPA's index.html (CloudFront maps S3's
  // 403/404 to it), so check the content type, not just the status.
  if (!res.ok || !res.headers.get("content-type")?.includes("json")) {
    throw new Error(
      `data/${name}.json not available — run python3 data/digest.py and publish it`,
    );
  }
  if (res.headers.get("x-sw-from-cache")) {
    dataMeta.fromCache = true;
    dataMeta.cachedAt = Number(res.headers.get("x-sw-cached-at")) || null;
  }
  return (await res.json()) as T;
}

/** Ask the service worker to drop its copy of the financial JSON (expired session). */
async function clearCachedData(): Promise<void> {
  (await navigator.serviceWorker?.getRegistration())?.active?.postMessage({
    type: "CLEAR_DATA",
  });
}

/** forecast.json is a nice-to-have: pages that read it render without it. */
async function loadOptional<T>(name: string, fresh = false): Promise<T | null> {
  try {
    return await loadDigested<T>(name, fresh);
  } catch {
    return null;
  }
}

/**
 * `fresh: false` (boot) lets the service worker answer from its cache instantly; `reloadData`
 * always goes to the network.
 */
async function loadAll(fresh = false) {
  const before = { ...dataMeta };
  dataMeta.fromCache = false;
  dataMeta.cachedAt = null;
  let all;
  try {
    all = await Promise.all([
      loadDigested<Cashflow>("cashflow", fresh),
      loadDigested<Snapshot>("snapshot", fresh),
      loadDigested<Transactions>("transactions", fresh),
      loadDigested<Goals>("goals", fresh),
      loadOptional<Forecast>("forecast", fresh),
    ]);
  } catch (err) {
    Object.assign(dataMeta, before); // a failed refresh leaves the old data, and its provenance, on screen
    throw err;
  }
  dataMeta.fetchedAt = Date.now();
  setAppStatus({ sessionExpired: false });
  return all;
}

// `let` exports are live bindings: importers see the new value after reloadData().
export let [cashflow, snapshot, transactions, goals, forecast] =
  await loadAll();

let dataVersion = 0;
const dataListeners = new Set<() => void>();

/**
 * Re-fetch every digested JSON and swap the exported bindings (used after the ledger
 * API's rebuild publishes new data). On failure the old data stays. Components that
 * call `useDataVersion()` re-render; pages that cache values at module level keep the
 * old ones until a full reload.
 */
export async function reloadData(): Promise<void> {
  let next;
  try {
    next = await loadAll(true);
  } catch (err) {
    // Keep showing the old data, but tell the user why it isn't refreshing.
    if (err instanceof SessionExpiredError)
      setAppStatus({ sessionExpired: true });
    throw err;
  }
  [cashflow, snapshot, transactions, goals, forecast] = next;
  dataVersion += 1;
  dataListeners.forEach((l) => l());
}

/** The current reload counter, for code outside React (stamps optimistic overlays). */
export const getDataVersion = (): number => dataVersion;

/** Subscribe a component to `reloadData()`; returns a counter that bumps on every reload. */
export function useDataVersion(): number {
  return useSyncExternalStore(
    (cb) => {
      dataListeners.add(cb);
      return () => void dataListeners.delete(cb);
    },
    () => dataVersion,
  );
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
  return fmt({
    style: "currency",
    currency: "ILS",
    maximumFractionDigits: opts.decimals ?? 0,
  }).format(n);
}

/** Signed ₪ for deltas: +₪1,200 / -₪300 (zero stays unsigned). */
export function shekelSigned(n: number): string {
  return fmt({
    style: "currency",
    currency: "ILS",
    maximumFractionDigits: 0,
    signDisplay: "exceptZero",
  }).format(n);
}

/** Compact ₪ for axes/large figures (₪2.6M). */
export function shekelCompact(n: number): string {
  return fmt({
    style: "currency",
    currency: "ILS",
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(n);
}

/** Format a cashflow metric by its unit; `null` (not computable yet) renders as "—". */
export function formatMetric(value: number | null, units: string): string {
  if (value == null) return "—";
  if (units === "₪") return shekel(value);
  if (units === "%") return pct(value, 1);
  return num(value, 1);
}

/** Short form of `formatMetric` for narrow tiles (₪1.6M); non-₪ units are already short. */
export function formatMetricCompact(
  value: number | null,
  units: string,
): string {
  if (value != null && units === "₪") return shekelCompact(value);
  return formatMetric(value, units);
}

/** Percent from a 0–100 figure (the pipeline's convention): pct(66.6, 1) → "66.6%". */
export function pct(n: number, decimals = 0): string {
  return fmt({ style: "percent", maximumFractionDigits: decimals }).format(
    n / 100,
  );
}

/** Compact plain number for chart axes: 1,540,121 → "1.5M". */
export function numCompact(n: number): string {
  return fmt({ notation: "compact", maximumFractionDigits: 1 }).format(n);
}

/** Plain grouped number: 2316 → "2,316". */
export function num(n: number, decimals = 0): string {
  return fmt({ maximumFractionDigits: decimals }).format(n);
}

/** Month + year for a loan end date, e.g. "אוג׳ 2053". */
export function monthYear(iso: string): string {
  return new Intl.DateTimeFormat(LOCALE, {
    month: "short",
    year: "numeric",
  }).format(new Date(`${iso.slice(0, 10)}T12:00:00`));
}

/** A pipeline Metric's value in its own units. */
export function metricValue(m: Pick<Metric, "value" | "units">): string {
  return formatMetric(m.value, m.units);
}

/** Days since an ISO timestamp — used for the stale-data nudge. */
export function daysSince(iso: string): number {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return Infinity;
  return Math.floor((Date.now() - then) / 86_400_000);
}
