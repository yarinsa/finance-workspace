import { useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { Card, Page } from "@/components/common";
import { TransactionList, TransactionRow } from "@/components/TransactionRow";
import TransactionEditSheet, { type EditTarget } from "@/components/TransactionEditSheet";
import { useQuickEdit } from "@/components/QuickEditSheets";
import WidgetsCarousel from "@/components/transactions/WidgetsCarousel";
import TransactionGroups, { type GroupPlan } from "@/components/transactions/TransactionGroups";
import BudgetPlan from "@/components/BudgetPlan";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import type { BudgetCategory } from "@/lib/budgets";
import { applyOverlay } from "@/lib/ledgerOverlay";
import { buildCards, buildMonthList } from "@/lib/monthList";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cashflow, sourceLabel, transactions } from "@/lib/data";
import { useLedgerApi } from "@/lib/useLedgerApi";
import { cn } from "@/lib/utils";
import {
  PAGE_SIZE,
  PRESET_DAYS,
  accountCounts,
  cyclePlans,
  groupRows,
  parseGroup,
  type GroupBy,
  type ViewRow,
  accountLabel,
  applyView,
  filterByAccount,
  filterKey,
  inRange,
  parseAccount,
  parseRange,
  rangeToParams,
  resolveRange,
  todayIso,
  widgetStats,
  type LedgerRow,
  type RangeSpec,
} from "@/lib/transactionsView";

/** One filter chip; the selected one is tinted. */
function Chip({ selected, onClick, children }: { selected: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={cn(
        "shrink-0 rounded-full border px-3 py-1 text-xs tabular-nums",
        selected ? "border-brand bg-brand/15 font-semibold" : "border-line",
      )}
    >
      {children}
    </button>
  );
}

const GROUP_CHIPS: { key: GroupBy; label: string }[] = [
  { key: "none", label: "לפי תאריך" },
  { key: "category", label: "לפי קטגוריה" },
  { key: "kind", label: "קבוע ומשתנה" },
];

const CHIP_ROW = "-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-0.5";

/**
 * "תנועות": every transaction in a time window, newest first, filterable by account.
 * Card-bill payments and internal transfers are hidden (they duplicate the card rows);
 * live edits from the ledger API apply immediately. State lives in the URL:
 * ?days=30|60|90|180|360, ?from=&to= (custom) or ?range=cycle (the budget cycle), ?account=<origin>
 * and ?group=category|kind. Plans, expected charges and the plan editor show only for the cycle
 * across all accounts: they are the household's budget, not a slice of it.
 */
export default function Transactions() {
  const [params, setParams] = useSearchParams();
  const { overlay } = useLedgerApi();
  const [editing, setEditing] = useState<EditTarget | null>(null);
  const { swipeProps, sheets } = useQuickEdit();

  const [planning, setPlanning] = useState<BudgetCategory | null>(null);

  const budgets = cashflow.budgets ?? null;
  const cycle = budgets ? { from: budgets.cycle_start, to: budgets.cycle_end } : null;
  const spec = parseRange({ days: params.get("days"), from: params.get("from"), to: params.get("to"), range: params.get("range") });
  const today = todayIso();
  const range = resolveRange(spec, today, cycle);
  const groupBy = parseGroup(params.get("group"));

  // The cycle's cards, built exactly as /monthly builds them, for plans and the category alias.
  const plans = useMemo(() => {
    if (!budgets) return null;
    const month = budgets.cycle_start.slice(0, 7);
    const m = applyOverlay(cashflow.spending?.months ?? [], overlay).find((x) => x.month === month);
    const sections = buildMonthList({
      month: m,
      budgets,
      bills: cashflow.bills?.month === month ? cashflow.bills : null,
      fixed: cashflow.fixed_expenses?.month === month ? cashflow.fixed_expenses : null,
    });
    return cyclePlans(buildCards(sections));
  }, [budgets, overlay]);

  const visible = useMemo(() => applyView(transactions.transactions as LedgerRow[], overlay), [overlay]);
  const windowed = useMemo(() => inRange(visible, range), [visible, range.from, range.to]); // eslint-disable-line react-hooks/exhaustive-deps
  const accounts = accountCounts(windowed);
  const account = parseAccount(params.get("account"), accounts.map((a) => a.key));
  const rows = filterByAccount(windowed, account);
  const stats = widgetStats(rows);
  const groups = groupBy === "none" ? [] : groupRows(rows, groupBy, plans?.alias);

  const withPlans = spec.kind === "cycle" && account === null && !!budgets;
  const summary = budgets?.summary;
  const planOf = !withPlans
    ? undefined
    : (g: { key: string }): GroupPlan | undefined => {
        if (groupBy === "category") return plans?.plans.get(g.key);
        if (g.key === "fixed") return { planned: summary?.fixed.expected ?? null };
        if (g.key === "variable") return { planned: summary?.variable.planned ?? summary?.variable.estimate ?? null };
        return undefined;
      };

  // Paging resets whenever the filter changes.
  const key = filterKey(range, account);
  const [paging, setPaging] = useState({ key, limit: PAGE_SIZE });
  const limit = paging.key === key ? paging.limit : PAGE_SIZE;

  /** Writes the range and account together, so neither drops the other. */
  const write = (next: { spec?: RangeSpec; account?: string | null; group?: GroupBy }) =>
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        if (next.spec) {
          for (const k of ["days", "from", "to", "range"]) p.delete(k);
          for (const [k, v] of Object.entries(rangeToParams(next.spec))) p.set(k, v);
        }
        if (next.account !== undefined) {
          if (next.account) p.set("account", next.account);
          else p.delete("account");
        }
        if (next.group) {
          if (next.group === "none") p.delete("group");
          else p.set("group", next.group);
        }
        return p;
      },
      { replace: true },
    );

  const renderRow = (t: ViewRow, i: number) => {
    const target: EditTarget = {
      date: t.date,
      amount: t.amount,
      merchant: t.description ?? t.merchant ?? "—",
      category: t.category,
      overridden: t.overridden,
      tags: t.tags,
    };
    return (
      <TransactionRow
        key={`${t.date}-${t.amount}-${i}`}
        merchant={target.merchant}
        amount={t.amount}
        date={t.date}
        category={t.category}
        tags={t.tags}
        edited={t.overridden}
        offset={t.offset_amount}
        meta={account ? undefined : accountLabel(t.origin || "other", sourceLabel)}
        onClick={() => setEditing(target)}
        {...swipeProps(target, t.amount)}
      />
    );
  };

  const custom = spec.kind === "custom";
  const setCustom = (from: string, to: string) => {
    if (from && to) write({ spec: { kind: "custom", from, to } });
  };

  return (
    <Page title="תנועות">
      <div className="flex flex-col gap-3">
        <div className={CHIP_ROW} role="group" aria-label="טווח זמן">
          {PRESET_DAYS.map((d) => (
            <Chip key={d} selected={spec.kind === "days" && spec.days === d} onClick={() => write({ spec: { kind: "days", days: d } })}>
              {d} יום
            </Chip>
          ))}
          {cycle && (
            <Chip selected={spec.kind === "cycle"} onClick={() => write({ spec: { kind: "cycle" } })}>
              המחזור
            </Chip>
          )}
          <Chip selected={custom} onClick={() => !custom && write({ spec: { kind: "custom", ...range } })}>
            טווח אחר
          </Chip>
        </div>
        {custom && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <label className="flex flex-1 items-center gap-2">
              מ־
              <Input type="date" value={range.from} max={range.to} onChange={(e) => setCustom(e.target.value, range.to)} />
            </label>
            <label className="flex flex-1 items-center gap-2">
              עד
              <Input type="date" value={range.to} min={range.from} onChange={(e) => setCustom(range.from, e.target.value)} />
            </label>
          </div>
        )}
        {accounts.length > 1 && (
          <div className={CHIP_ROW} role="group" aria-label="חשבון">
            <Chip selected={account === null} onClick={() => write({ account: null })}>
              הכל · {windowed.length}
            </Chip>
            {accounts.map((a) => (
              <Chip key={a.key} selected={account === a.key} onClick={() => write({ account: a.key })}>
                {accountLabel(a.key, sourceLabel)} · {a.count}
              </Chip>
            ))}
          </div>
        )}
        <div className={CHIP_ROW} role="group" aria-label="קיבוץ">
          {GROUP_CHIPS.map((c) => (
            <Chip key={c.key} selected={groupBy === c.key} onClick={() => write({ group: c.key })}>
              {c.label}
            </Chip>
          ))}
        </div>
      </div>

      {rows.length === 0 ? (
        <Card>
          <div className="text-muted-foreground">אין תנועות בטווח הזה.</div>
        </Card>
      ) : (
        <div className="flex flex-col gap-2">
          <WidgetsCarousel w={stats} cycle={account === null ? (cashflow.budgets?.summary ?? null) : null} />
          <p className="mt-2 text-sm text-muted-foreground tabular-nums">{rows.length} תנועות</p>
          {groupBy === "none" ? (
            <>
              <div className="overflow-hidden surface">
                <TransactionList inset>{rows.slice(0, limit).map(renderRow)}</TransactionList>
              </div>
              {rows.length > limit && (
                <Button variant="secondary" className="self-center" onClick={() => setPaging({ key, limit: limit + PAGE_SIZE })}>
                  הצג עוד
                </Button>
              )}
            </>
          ) : (
            <TransactionGroups key={key + groupBy} groups={groups} planOf={planOf} renderRow={renderRow} onPlan={setPlanning} />
          )}
        </div>
      )}
      <Sheet open={planning != null} onOpenChange={(o) => !o && setPlanning(null)}>
        <SheetContent side="bottom" className="max-h-[90dvh] overflow-y-auto" dir="rtl">
          {planning && (
            <>
              <SheetHeader>
                <SheetTitle className="font-display text-xl font-medium">{planning.name}</SheetTitle>
              </SheetHeader>
              <div className="px-4 pb-4">
                <BudgetPlan key={planning.name} c={planning} />
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
      <TransactionEditSheet tx={editing} onClose={() => setEditing(null)} />
      {sheets}
    </Page>
  );
}
