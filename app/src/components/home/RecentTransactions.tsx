import { useState } from "react";
import { Section } from "@/components/common";
import CategoryTag from "@/components/CategoryTag";
import TransactionEditSheet, { type EditTarget } from "@/components/TransactionEditSheet";
import { cashflow, shekel, transactions } from "@/lib/data";
import { applyOverlay } from "@/lib/ledgerOverlay";
import { useLedgerApi } from "@/lib/useLedgerApi";

interface Row {
  date: string;
  merchant: string;
  category: string;
  overridden?: boolean;
  /** Positive ₪ spent. */
  amount: number;
}

function recent(overlay: ReturnType<typeof useLedgerApi>["overlay"]): Row[] {
  const fromSpending = applyOverlay(cashflow.spending?.months ?? [], overlay)[0]?.transactions;
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
  const { overlay } = useLedgerApi();
  const [editing, setEditing] = useState<EditTarget | null>(null);
  const rows = recent(overlay);
  if (rows.length === 0) return null;
  return (
    <Section title="תנועות אחרונות" to="/spending">
      <div className="overflow-hidden rounded-[20px] border border-line bg-panel shadow-[var(--shadow)]">
        {rows.map((r, i) => (
          <button
            type="button"
            key={`${r.date}-${r.merchant}-${i}`}
            onClick={() => setEditing(r)}
            className="flex w-full items-center gap-3 border-b border-line px-4 py-2.5 text-start last:border-b-0"
          >
            <div className="min-w-0 flex-1">
              <div className="truncate font-semibold">{r.merchant}</div>
              <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
                <CategoryTag name={r.category} />
                <span>{shortDate(r.date)}</span>
              </div>
            </div>
            <strong className="shrink-0 tabular-nums">{shekel(-r.amount)}</strong>
          </button>
        ))}
      </div>
      <TransactionEditSheet tx={editing} onClose={() => setEditing(null)} />
    </Section>
  );
}
