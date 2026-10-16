/** Shape of the `spending` block in cashflow.json (built by data/spending.py). */
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
  /** True when a manual override exists for this transaction (ledger API). */
  overridden?: boolean;
  /** Tag names from the DB `transaction_tags` table, sorted; absent when untagged. */
  tags?: string[];
}

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
