/** Shape of the `spending` block in cashflow.json (built by data/spending.py), read by /monthly. */
export interface SpendingCategory {
  name: string;
  amount: number;
  /** Share of the month's spending, 0-100. */
  pct: number;
  count: number;
}

export interface SpendingMerchant {
  name: string;
  amount: number;
  count: number;
}

export interface SpendingTransaction {
  date: string;
  merchant: string;
  /** Positive ₪ spent. */
  amount: number;
  category: string;
  /** The ledger's category_group (דיור, אוכל, …); null when the category has none. */
  group?: string | null;
  /** The ledger's kind (household edits win); absent for kindless rows. */
  kind?: "fixed" | "variable";
  /** The month screen's section: loans/mortgage and kindless rows are debt_savings (spending.block). */
  block?: "fixed" | "variable" | "debt_savings";
  /** True when a manual override exists for this transaction (ledger API). */
  overridden?: boolean;
  /** Tag names from the DB `transaction_tags` table, sorted; absent when untagged. */
  tags?: string[];
  /** ₪ paid back (קיזוז) and netted out of the month's totals; `amount` stays the real charge. */
  offset?: number;
  /** The paybacks behind `offset`. */
  offsets?: {
    date: string;
    description: string | null;
    amount: number;
    kind: OffsetKind;
  }[];
}

/** How a payback came to be netted against an expense (finance/offsets.py). */
export type OffsetKind = "refund" | "rule" | "manual";

export const OFFSET_KIND_LABEL: Record<OffsetKind, string> = {
  refund: "זיכוי אוטומטי",
  rule: "כלל קבוע",
  manual: "ידני",
};

export interface ExcludedBucket {
  amount: number;
  count: number;
}

export interface SpendingMonth {
  /** YYYY-MM */
  month: string;
  total: number;
  /** Change vs. the previous calendar month in ₪ (null when that month has no data). */
  vs_prev: number | null;
  /** Current calendar month — still accruing, so `vs_prev` compares part to whole. */
  partial: boolean;
  by_category: SpendingCategory[];
  by_merchant: SpendingMerchant[];
  /** Spend per section, category group and category (spending.py by_line). */
  by_line?: {
    block: "fixed" | "variable" | "debt_savings";
    group: string | null;
    category: string;
    amount: number;
    count: number;
  }[];
  /** Spending only, newest first, capped. */
  transactions: SpendingTransaction[];
  excluded: {
    card_bills: ExcludedBucket;
    transfers: ExcludedBucket;
    savings: ExcludedBucket;
    income: ExcludedBucket;
  };
}

export interface SpendingData {
  /** Newest first. */
  months: SpendingMonth[];
}
