/** The `bills` block of cashflow.json (data/bills.py). */
export interface BillItem {
  name: string;
  category: string | null;
  kind: "bill" | "subscription" | "loan";
  amount: number;
  due_day: number | null;
  due_date: string | null;
  status: "paid" | "upcoming" | "overdue";
  paid_on: string | null;
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
