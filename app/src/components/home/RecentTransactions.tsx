import { useState } from "react";
import { Section } from "@/components/common";
import { TransactionList, TransactionRow } from "@/components/TransactionRow";
import TransactionEditSheet, { type EditTarget } from "@/components/TransactionEditSheet";
import { useQuickEdit } from "@/components/QuickEditSheets";
import { cashflow, transactions } from "@/lib/data";
import { applyOverlay } from "@/lib/ledgerOverlay";
import { useLedgerApi } from "@/lib/useLedgerApi";

interface Row {
  date: string;
  merchant: string;
  category: string;
  overridden?: boolean;
  tags?: string[];
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
    .map((t) => ({ date: t.date, merchant: t.description ?? "—", category: t.category ?? "", tags: t.tags, amount: -t.amount }));
}

/** The last five spending transactions, newest first. */
export default function RecentTransactions() {
  const { overlay } = useLedgerApi();
  const [editing, setEditing] = useState<EditTarget | null>(null);
  const { swipeProps, sheets } = useQuickEdit();
  const rows = recent(overlay);
  if (rows.length === 0) return null;
  return (
    <Section title="תנועות אחרונות" to="/monthly?group=none">
      <div className="overflow-hidden rounded-[20px] border border-line bg-panel shadow-[var(--shadow)]">
        <TransactionList inset>
          {rows.map((r, i) => (
            <TransactionRow
              key={`${r.date}-${r.merchant}-${i}`}
              merchant={r.merchant}
              amount={-r.amount}
              date={r.date}
              category={r.category}
              tags={r.tags}
              edited={r.overridden}
              onClick={() => setEditing(r)}
              {...swipeProps(r, -r.amount)}
            />
          ))}
        </TransactionList>
      </div>
      <TransactionEditSheet tx={editing} onClose={() => setEditing(null)} />
      {sheets}
    </Section>
  );
}
