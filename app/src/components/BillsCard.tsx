import { Card, CardLabel } from "@/components/common";
import { cashflow, num, shekel } from "@/lib/data";
import type { BillItem } from "@/lib/bills";
import { cn } from "@/lib/utils";

const KIND: Record<BillItem["kind"], { text: string; cls: string }> = {
  bill: { text: "חשבון", cls: "pill-muted" },
  subscription: { text: "מנוי", cls: "pill-good" },
  loan: { text: "הלוואה", cls: "pill-muted" },
};

/**
 * This cycle's bills and subscriptions, ordered by day: ✓ on paid rows,
 * amber "באיחור" on overdue ones, and a paid-vs-left bar on top.
 */
export default function BillsCard() {
  const bills = cashflow.bills;
  if (!bills || !bills.items.length) return null;

  const left = bills.upcoming_total + bills.overdue_total;
  const total = left + bills.paid_total;
  const pct = total > 0 ? Math.round((bills.paid_total / total) * 100) : 0;

  return (
    <Card>
      <CardLabel>חשבונות ומנויים החודש</CardLabel>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-[28px] leading-tight font-extrabold tabular-nums">
          {shekel(left)}
          <span className="text-sm font-semibold text-muted-foreground"> נותר לשלם</span>
        </div>
        <span className="text-sm text-muted-foreground tabular-nums">{shekel(bills.paid_total)} שולם</span>
      </div>
      <div
        className="mt-2 h-2 overflow-hidden rounded-full bg-panel-2"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className="h-full rounded-full bg-good" style={{ width: `${pct}%` }} />
      </div>

      <ul className="m-0 mt-3 list-none p-0">
        {bills.items.map((it, i) => {
          const paid = it.status === "paid";
          const overdue = it.status === "overdue";
          return (
            <li
              key={i}
              className={cn(
                "flex items-center gap-3 border-t border-line py-2",
                paid && "text-muted-foreground",
              )}
            >
              <span className="w-7 shrink-0 text-center text-sm font-semibold tabular-nums">
                {it.due_day != null ? num(it.due_day) : "—"}
              </span>
              <div className="flex min-w-0 flex-1 flex-col">
                <span className="truncate" dir="auto">{it.name}</span>
                <span className="flex flex-wrap items-center gap-x-2 text-xs">
                  <span className={cn("pill whitespace-nowrap", KIND[it.kind].cls)}>{KIND[it.kind].text}</span>
                  {overdue && <span className="font-semibold text-warn">באיחור</span>}
                </span>
              </div>
              <strong className="shrink-0 tabular-nums">{shekel(it.amount)}</strong>
              <span
                className={cn("w-4 shrink-0 text-center", paid ? "text-good" : "invisible")}
                aria-label={paid ? "שולם" : undefined}
              >
                ✓
              </span>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
