import { Section } from "@/components/common";
import { cashflow, shekel, transactions } from "@/lib/data";

interface Row {
  date: string;
  merchant: string;
  category: string;
  /** Positive ₪ spent. */
  amount: number;
}

function recent(): Row[] {
  const fromSpending = cashflow.spending?.months?.[0]?.transactions;
  if (fromSpending?.length) return fromSpending.slice(0, 5);
  return transactions.transactions
    .filter((t) => t.amount < 0 && !t.card_bill_payment && !t.internal_transfer && !t.savings)
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, 5)
    .map((t) => ({ date: t.date, merchant: t.description ?? "—", category: t.category ?? "", amount: -t.amount }));
}

function shortDate(iso: string): string {
  return new Intl.DateTimeFormat("he-IL", { day: "numeric", month: "short" }).format(new Date(`${iso.slice(0, 10)}T12:00:00`));
}

/** The last five spending transactions, newest first. */
export default function RecentTransactions() {
  const rows = recent();
  if (rows.length === 0) return null;
  return (
    <Section title="תנועות אחרונות" to="/spending">
      <div className="overflow-hidden rounded-[20px] border border-line bg-panel shadow-[var(--shadow)]">
        {rows.map((r, i) => (
          <div key={`${r.date}-${r.merchant}-${i}`} className="flex items-center gap-3 border-b border-line px-4 py-2.5 last:border-b-0">
            <div className="min-w-0 flex-1">
              <div className="truncate font-semibold">{r.merchant}</div>
              <div className="truncate text-xs text-muted-foreground">
                {[r.category, shortDate(r.date)].filter(Boolean).join(" · ")}
              </div>
            </div>
            <strong className="shrink-0 tabular-nums">{shekel(-r.amount)}</strong>
          </div>
        ))}
      </div>
    </Section>
  );
}
