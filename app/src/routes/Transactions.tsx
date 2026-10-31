import { useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { Card, Page } from "@/components/common";
import { TransactionList, TransactionRow } from "@/components/TransactionRow";
import TransactionEditSheet, { type EditTarget } from "@/components/TransactionEditSheet";
import { useQuickEdit } from "@/components/QuickEditSheets";
import WidgetsCarousel from "@/components/transactions/WidgetsCarousel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cashflow, sourceLabel, transactions } from "@/lib/data";
import { useLedgerApi } from "@/lib/useLedgerApi";
import { cn } from "@/lib/utils";
import {
  PAGE_SIZE,
  PRESET_DAYS,
  accountCounts,
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

const CHIP_ROW = "-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-0.5";

/**
 * "תנועות": every transaction in a time window, newest first, filterable by account.
 * Card-bill payments and internal transfers are hidden (they duplicate the card rows);
 * live edits from the ledger API apply immediately. State lives in the URL:
 * ?days=30|60|90|180|360 or ?from=&to= (custom), and ?account=<origin>.
 */
export default function Transactions() {
  const [params, setParams] = useSearchParams();
  const { overlay } = useLedgerApi();
  const [editing, setEditing] = useState<EditTarget | null>(null);
  const { swipeProps, sheets } = useQuickEdit();

  const spec = parseRange({ days: params.get("days"), from: params.get("from"), to: params.get("to") });
  const today = todayIso();
  const range = resolveRange(spec, today);

  const visible = useMemo(() => applyView(transactions.transactions as LedgerRow[], overlay), [overlay]);
  const windowed = useMemo(() => inRange(visible, range), [visible, range.from, range.to]); // eslint-disable-line react-hooks/exhaustive-deps
  const accounts = accountCounts(windowed);
  const account = parseAccount(params.get("account"), accounts.map((a) => a.key));
  const rows = filterByAccount(windowed, account);
  const stats = widgetStats(rows);

  // Paging resets whenever the filter changes.
  const key = filterKey(range, account);
  const [paging, setPaging] = useState({ key, limit: PAGE_SIZE });
  const limit = paging.key === key ? paging.limit : PAGE_SIZE;

  /** Writes the range and account together, so neither drops the other. */
  const write = (next: { spec?: RangeSpec; account?: string | null }) =>
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        if (next.spec) {
          for (const k of ["days", "from", "to"]) p.delete(k);
          for (const [k, v] of Object.entries(rangeToParams(next.spec))) p.set(k, v);
        }
        if (next.account !== undefined) {
          if (next.account) p.set("account", next.account);
          else p.delete("account");
        }
        return p;
      },
      { replace: true },
    );

  const custom = spec.kind === "custom";
  const setCustom = (from: string, to: string) => {
    if (from && to) write({ spec: { kind: "custom", from, to } });
  };

  return (
    <Page title="תנועות">
      <div className="flex flex-col gap-3">
        <div className={CHIP_ROW} role="group" aria-label="טווח זמן">
          {PRESET_DAYS.map((d) => (
            <Chip key={d} selected={!custom && spec.days === d} onClick={() => write({ spec: { kind: "days", days: d } })}>
              {d} יום
            </Chip>
          ))}
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
      </div>

      {rows.length === 0 ? (
        <Card>
          <div className="text-muted-foreground">אין תנועות בטווח הזה.</div>
        </Card>
      ) : (
        <div className="flex flex-col gap-2">
          <WidgetsCarousel w={stats} cycle={account === null ? (cashflow.budgets?.summary ?? null) : null} />
          <p className="mt-2 text-sm text-muted-foreground tabular-nums">{rows.length} תנועות</p>
          <div className="overflow-hidden surface">
            <TransactionList inset>
              {rows.slice(0, limit).map((t, i) => {
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
              })}
            </TransactionList>
          </div>
          {rows.length > limit && (
            <Button variant="secondary" className="self-center" onClick={() => setPaging({ key, limit: limit + PAGE_SIZE })}>
              הצג עוד
            </Button>
          )}
        </div>
      )}
      <TransactionEditSheet tx={editing} onClose={() => setEditing(null)} />
      {sheets}
    </Page>
  );
}
