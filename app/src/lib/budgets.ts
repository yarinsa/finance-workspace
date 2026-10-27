/** Mint-style budgets block (data/budgets.py build_budgets); optional in the cashflow doc. */
export interface BudgetCategory {
  /** A category of finance/categories.py, or a whole group (`scope: "group"`, e.g. תחבורה). */
  name: string;
  scope?: "category" | "group";
  /** The line's category group (the name itself for a group line). */
  group?: string | null;
  planned: number;
  spent: number;
  left: number;
  /** spent / planned, in percent; null when nothing is planned. */
  pct: number | null;
  over: boolean;
  /** override = the household's own plan (seeded from RiseUp by `budgets.py seed`);
   * unplanned = a variable category with spending but no plan yet (planned 0). */
  source: "riseup" | "override" | "unplanned";
  /** Median variable spend of the last 3–6 cycles; null with too little history. */
  estimate?: number | null;
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
  summary?: BudgetSummary;
}

/** One block of the month: what happened so far and what it is expected to reach. */
export interface BudgetBlock {
  actual: number;
  /** Forecast income / actual + still-expected recurring fixed charges; null when unknown. */
  expected?: number | null;
  /** The figure `left` uses: max(actual, expected or estimate). */
  value: number;
}

/** The cycle in three blocks — fixed, variable, what is left (data/budgets.py build_summary). */
export interface BudgetSummary {
  income: BudgetBlock;
  fixed: BudgetBlock;
  variable: BudgetBlock & {
    /** Σ per-category median of the last 3–6 cycles; null with too little history. */
    estimate: number | null;
    /** The budget lines' total: what is planned for variable spending this cycle. */
    planned?: number | null;
    /** actual + estimate × the share of the cycle still ahead. */
    projected?: number | null;
    days_left?: number;
    categories: { name: string; actual: number; estimate: number | null }[];
  };
  /** Loans, the mortgage and savings deposits. */
  debt_savings: BudgetBlock;
  /** Free money: income − fixed − debt_savings − the variable plan. Aim for ~0. */
  left: number;
  /** Where the cycle is heading: the same with variable at `projected`. */
  projected_end?: number | null;
  estimate_cycles: number;
}
