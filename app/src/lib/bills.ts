/** The `bills` block of cashflow.json (data/bills.py). */
export interface BillItem {
  name: string;
  /** Our category (finance/categories.py) and its group. */
  category: string | null;
  group?: string | null;
  kind: "bill" | "subscription" | "loan";
  amount: number;
  due_day: number | null;
  due_date: string | null;
  status: "paid" | "upcoming" | "overdue";
  paid_on: string | null;
  /** A utility not charged yet this cycle: the amount is the median of its last bills. */
  estimated?: boolean;
  /** A utility's billing cadence in months (water and gas: 2). */
  cadence_months?: number;
}

export interface Bills {
  month: string;
  cycle_start: string;
  cycle_end: string;
  paid_total: number;
  upcoming_total: number;
  overdue_total: number;
  items: BillItem[];
}
