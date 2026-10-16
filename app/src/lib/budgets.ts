/** Mint-style budgets block (data/budgets.py build_budgets); optional in the cashflow doc. */
export interface BudgetCategory {
  name: string;
  planned: number;
  spent: number;
  left: number;
  /** spent / planned, in percent; null when nothing is planned. */
  pct: number | null;
  over: boolean;
  source: "riseup" | "override";
  /** Spend of the last cycles before the current one, oldest first. */
  history?: BudgetHistoryPoint[];
}

export interface BudgetHistoryPoint {
  /** Budget month, YYYY-MM. */
  cycle: string;
  spent: number;
}

export interface Budgets {
  cycle_start: string;
  cycle_end: string;
  days_left: number;
  total_planned: number;
  total_spent: number;
  left: number;
  /** left / days_left; null once nothing is left. */
  per_day: number | null;
  categories: BudgetCategory[];
}
