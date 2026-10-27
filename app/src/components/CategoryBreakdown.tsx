import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, ChevronLeft } from "lucide-react";
import { Card, CardLabel } from "@/components/common";
import { TransactionList, TransactionRow } from "@/components/TransactionRow";
import TransactionEditSheet, { type EditTarget } from "@/components/TransactionEditSheet";
import { useQuickEdit } from "@/components/QuickEditSheets";
import { cashflow, shekel, useDataVersion } from "@/lib/data";
import { applyOverlay, overlayFor } from "@/lib/ledgerOverlay";
import { useLedgerApi } from "@/lib/useLedgerApi";
import { cn } from "@/lib/utils";

/**
 * "לאן הלך הכסף": the month's spending by category, biggest first. Each category
 * collapses to name + total and expands to its transactions (newest first) in the same
 * rows, and the same edit sheet, as /spending. Several can be open at once.
 * Reads cashflow.spending through the ledger overlay, so excluded buckets and
 * unpublished edits behave exactly like the explorer. Renders nothing for a month with no data.
 */
export default function CategoryBreakdown({ month }: { month: string }) {
  useDataVersion(); // re-render when a published rebuild is re-fetched
  const { overlay } = useLedgerApi();
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const [editing, setEditing] = useState<EditTarget | null>(null);
  const { swipeProps, sheets } = useQuickEdit();
  const months = useMemo(() => applyOverlay(cashflow.spending?.months ?? [], overlay), [overlay]);
  const m = months.find((x) => x.month === month);
  if (!m || !m.by_category.length) return null;

  const toggle = (name: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (!next.delete(name)) next.add(name);
      return next;
    });

  return (
    <Card>
      <CardLabel>לאן הלך הכסף</CardLabel>
      <div className="-mt-1 mb-2 font-display text-[36px] leading-[1.15] font-medium tabular-nums">
        {shekel(m.total)}
        {m.partial && <span className="text-sm font-semibold text-muted-foreground"> עד היום</span>}
      </div>
      {m.excluded.savings.amount > 0 && (
        <div className="-mt-1 mb-2 text-xs text-muted-foreground">
          לא כולל חיסכון והפקדות {shekel(m.excluded.savings.amount)} (נספרים בהלוואות וחיסכון למעלה)
        </div>
      )}
      <ul className="divide-y divide-line">
        {m.by_category.map((c) => {
          const isOpen = open.has(c.name);
          const txs = m.transactions
            .filter((t) => t.category === c.name)
            .sort((a, b) => b.date.localeCompare(a.date));
          return (
            <li key={c.name}>
              <button
                type="button"
                aria-expanded={isOpen}
                onClick={() => toggle(c.name)}
                className="flex w-full items-center gap-3 py-2.5 text-start"
              >
                <ChevronDown
                  className={cn("size-4 shrink-0 text-muted-foreground transition-transform", !isOpen && "rotate-90")}
                />
                <span className="min-w-0 flex-1 truncate font-medium">{c.name}</span>
                <strong className="shrink-0 tabular-nums">{shekel(c.amount)}</strong>
              </button>
              {isOpen && (
                <div className="pb-1 ps-7">
                  {txs.length === 0 ? (
                    <div className="py-2 text-sm text-muted-foreground">אין תנועות להצגה.</div>
                  ) : (
                    <TransactionList>
                      {txs.map((t, i) => (
                        <TransactionRow
                          key={`${t.date}-${i}`}
                          merchant={t.merchant}
                          amount={-t.amount}
                          date={t.date}
                          tags={t.tags}
                          edited={t.overridden || overlayFor(overlay, t)?.overridden}
                          offset={t.offset}
                          onClick={() => setEditing(t)}
                          {...swipeProps(t, -t.amount)}
                        />
                      ))}
                    </TransactionList>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <Link
        to={`/spending?month=${m.month}`}
        className="mt-1 flex items-center justify-between gap-3 border-t border-line pt-3 font-semibold text-brand"
      >
        לכל ההוצאות
        <ChevronLeft className="size-4" />
      </Link>
      <TransactionEditSheet tx={editing} onClose={() => setEditing(null)} />
      {sheets}
    </Card>
  );
}
