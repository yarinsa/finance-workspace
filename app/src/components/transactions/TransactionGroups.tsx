import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { Card, StackedBar, StatusPill } from "@/components/common";
import { BillStatus } from "@/components/cashflow/MonthList";
import { TransactionList } from "@/components/TransactionRow";
import { Button } from "@/components/ui/button";
import type { BudgetCategory } from "@/lib/budgets";
import { num, shekel, shekelSigned } from "@/lib/data";
import { PAGE_SIZE, type CyclePlan, type RowGroup, type ViewRow } from "@/lib/transactionsView";
import { cn } from "@/lib/utils";

/** The plan a group header compares against: a card's cycle plan, or a bare figure (קבוע / משתנה). */
export type GroupPlan = Pick<CyclePlan, "planned"> & Partial<Omit<CyclePlan, "planned">>;

function GroupCard({
  g,
  plan,
  renderRow,
  onPlan,
}: {
  g: RowGroup;
  plan?: GroupPlan;
  renderRow: (t: ViewRow, i: number) => ReactNode;
  onPlan: (b: BudgetCategory) => void;
}) {
  const planned = plan?.planned ?? null;
  const over = planned != null && g.out > planned + 0.5;
  const overdue = plan?.pending?.some((c) => c.status === "overdue") || plan?.bill?.status === "overdue";
  const [open, setOpen] = useState(over || !!overdue);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const incomeOnly = g.out < 0.005;
  const sub = [`${num(g.rows.length)} תנועות`, !incomeOnly && g.in > 0.005 && `נכנס ${shekel(g.in)}`].filter(Boolean).join(" · ");
  return (
    <Card className="!px-4 !py-3">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="block w-full text-start">
        <div className="flex items-baseline gap-2">
          <ChevronDown className={cn("size-4 shrink-0 self-center text-muted-foreground transition-transform", !open && "rotate-90")} />
          <span className="min-w-0 flex-1 truncate font-semibold">{g.label}</span>
          <strong className={cn("shrink-0 text-sm tabular-nums", over && "text-bad", incomeOnly && "text-good")}>
            {incomeOnly ? shekelSigned(g.in) : planned != null ? `${shekel(g.out)} מתוך ${shekel(planned)}` : shekel(g.out)}
          </strong>
        </div>
        {!incomeOnly && <StackedBar className="mt-2" fixed={g.fixed} variable={g.variable} total={planned ?? g.out} />}
        <div className="mt-1.5 flex flex-wrap justify-between gap-x-3 text-xs text-muted-foreground tabular-nums">
          <span>{sub}</span>
          {planned != null && (
            <span className={cn(over && "text-bad")}>
              {over ? `${shekel(g.out - planned)} מעל התכנון` : `${shekel(planned - g.out)} נותרו`}
            </span>
          )}
        </div>
      </button>
      {open && (
        <div className="mt-1">
          {plan?.pending?.map((c) => (
            <div key={c.name} className="flex items-center gap-2 py-1.5 text-xs text-muted-foreground tabular-nums">
              <span className="min-w-0 flex-1 truncate" dir="auto">{c.name}</span>
              {c.status === "overdue" ? (
                <StatusPill tone="warn">עוד לא חויב</StatusPill>
              ) : (
                <span>{c.due_day != null ? `צפוי ב-${num(c.due_day)}` : "צפוי החודש"}</span>
              )}
              <span className="text-foreground">{shekel(c.amount)}</span>
            </div>
          ))}
          {plan?.bill && <BillStatus c={plan.bill} />}
          <TransactionList>{g.rows.slice(0, limit).map(renderRow)}</TransactionList>
          {g.rows.length > limit && (
            <Button variant="secondary" size="sm" className="mt-2" onClick={() => setLimit(limit + PAGE_SIZE)}>
              הצג עוד
            </Button>
          )}
          {plan?.budget && (
            <button
              type="button"
              onClick={() => onPlan(plan.budget!)}
              className="mt-2 flex w-full items-baseline justify-between text-xs text-muted-foreground tabular-nums"
            >
              <span>{plan.budget.estimate != null && `בחודש רגיל ${shekel(plan.budget.estimate)}`}</span>
              <span className="font-semibold text-brand">תכנון ›</span>
            </button>
          )}
        </div>
      )}
    </Card>
  );
}

/**
 * The grouped list: one collapsible card per group with its total and a fixed/variable bar.
 * With `plans` (the current cycle, all accounts) a header reads "spent of planned", lists the
 * charges still expected and opens the plan editor; without, it shows only what happened.
 */
export default function TransactionGroups({
  groups,
  planOf,
  renderRow,
  onPlan,
}: {
  groups: RowGroup[];
  planOf?: (g: RowGroup) => GroupPlan | undefined;
  renderRow: (t: ViewRow, i: number) => ReactNode;
  onPlan: (b: BudgetCategory) => void;
}) {
  return (
    <div className="flex flex-col gap-2.5">
      {groups.map((g) => (
        <GroupCard key={g.key} g={g} plan={planOf?.(g)} renderRow={renderRow} onPlan={onPlan} />
      ))}
    </div>
  );
}
