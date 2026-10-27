import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ChevronDown } from "lucide-react";
import { Card, Section } from "@/components/common";
import BudgetPlan from "@/components/BudgetPlan";
import ExcludedSpendingCard from "@/components/ExcludedSpendingCard";
import HiddenTransactionsSheet from "@/components/HiddenTransactionsSheet";
import { TransactionList, TransactionRow } from "@/components/TransactionRow";
import TransactionEditSheet, {
  type EditTarget,
} from "@/components/TransactionEditSheet";
import { useQuickEdit } from "@/components/QuickEditSheets";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { scrollToSection } from "@/components/cashflow/MonthStats";
import type { BudgetCategory } from "@/lib/budgets";
import { cashflow, num, shekel, useDataVersion } from "@/lib/data";
import { applyOverlay, overlayFor } from "@/lib/ledgerOverlay";
import {
  buildMonthList,
  byMerchant,
  findLine,
  lineTransactions,
  net,
  type ChargeItem,
  type Line,
  type SectionKey,
} from "@/lib/monthList";
import type { SpendingTransaction } from "@/lib/spending";
import { useLedgerApi } from "@/lib/useLedgerApi";
import { cn } from "@/lib/utils";

export type GroupBy = "category" | "merchant" | "none";

/** What the drill-down sheet shows: a title, the transactions, and the plan editor when there is a budget line. */
interface SheetTarget {
  title: string;
  sub?: string;
  txns: SpendingTransaction[];
  budget?: BudgetCategory;
}

const dayMonth = new Intl.DateTimeFormat("he-IL", {
  day: "numeric",
  month: "numeric",
});

/** Thin progress bar; overspend fills it fully in red. */
function Bar({ pct, over }: { pct: number; over?: boolean }) {
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-line">
      <div
        className={cn(
          "h-full rounded-full",
          over ? "bg-bad" : pct >= 90 ? "bg-warn" : "bg-brand",
        )}
        style={{ width: `${Math.min(Math.max(pct, 0), 100)}%` }}
      />
    </div>
  );
}

/** A fixed charge: status (✓ paid / due day / overdue), flags from the "what can I cut?" review. */
function ChargeRow({ c, onOpen }: { c: ChargeItem; onOpen: () => void }) {
  const paid = c.status === "paid";
  const overdue = c.status === "overdue";
  const stale =
    c.last_charged &&
    (Date.now() - new Date(`${c.last_charged}T12:00:00`).getTime()) / 864e5 >
      70;
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full items-center gap-3 py-2 text-start"
    >
      <span className="w-7 shrink-0 text-center text-sm font-semibold tabular-nums text-muted-foreground">
        {c.due_day != null ? num(c.due_day) : "—"}
      </span>
      <div className="flex min-w-0 flex-1 flex-col">
        <span
          className={cn("truncate", paid && "text-muted-foreground")}
          dir="auto"
        >
          {c.name}
        </span>
        <span className="flex flex-wrap gap-x-2 text-xs text-muted-foreground">
          {c.category && <span>{c.category}</span>}
          {overdue && <span className="font-semibold text-warn">באיחור</span>}
          {c.status === "upcoming" && (
            <span>
              {c.due_day != null ? `צפוי ב-${num(c.due_day)}` : "צפוי החודש"}
            </span>
          )}
          {c.estimated && <span>משוער</span>}
          {stale && (
            <span className="text-warn">
              לא חויב מאז{" "}
              {dayMonth.format(new Date(`${c.last_charged}T12:00:00`))} — אולי
              בוטל?
            </span>
          )}
          {c.duplicate && (
            <span className="font-semibold text-warn">
              כפול · {c.duplicate_reason}
            </span>
          )}
        </span>
      </div>
      <strong className="shrink-0 tabular-nums">{shekel(c.amount)}</strong>
      <span
        className={cn(
          "w-4 shrink-0 text-center",
          paid ? "text-good" : "invisible",
        )}
        aria-label={paid ? "שולם" : undefined}
      >
        ✓
      </span>
    </button>
  );
}

/** A category or budget line: amount, and for a planned line its bar (spent of planned) and usual month. */
function CategoryRow({ l, onOpen }: { l: Line; onOpen: () => void }) {
  const b = l.budget;
  const planned = b && b.source !== "unplanned" ? b : null;
  const pct = planned
    ? planned.planned > 0
      ? (planned.spent / planned.planned) * 100
      : 100
    : 0;
  return (
    <button
      type="button"
      onClick={onOpen}
      className="block w-full py-2 text-start"
    >
      <div className="flex items-baseline justify-between gap-3">
        <span className="min-w-0 truncate">
          {l.name}
          {b?.source === "unplanned" && (
            <span className="ms-1.5 text-xs text-muted-foreground">
              לא מתוכנן
            </span>
          )}
        </span>
        <strong
          className={cn(
            "shrink-0 text-sm tabular-nums",
            planned?.over && "text-bad",
          )}
        >
          {planned
            ? `${shekel(planned.spent)} מתוך ${shekel(planned.planned)}`
            : shekel(l.amount)}
        </strong>
      </div>
      {planned && (
        <div className="mt-1.5">
          <Bar pct={pct} over={planned.over} />
        </div>
      )}
      {b && (
        <div className="mt-1 text-xs text-muted-foreground tabular-nums">
          {planned
            ? planned.over
              ? `חריגה ${shekel(-planned.left)}`
              : `${shekel(planned.left)} נותרו`
            : null}
          {b.estimate != null &&
            `${planned ? " · " : ""}בחודש רגיל ${shekel(b.estimate)}`}
        </div>
      )}
    </button>
  );
}

/**
 * The month's list: grouped by section → category group → line (`category`), by merchant,
 * or flat by date (`none`). A line opens a sheet with its transactions and, for a budget line,
 * the plan editor. `current` adds the cycle's budget bars and bill statuses; other months use
 * only their own transactions. Honours `?category=` (opens that line) and `?section=` (scrolls).
 */
export default function MonthList({
  month,
  current,
}: {
  month: string;
  current: boolean;
}) {
  useDataVersion(); // re-render when a published rebuild is re-fetched
  const { overlay } = useLedgerApi();
  const [params, setParams] = useSearchParams();
  const groupBy: GroupBy =
    (["merchant", "none"] as const).find((g) => g === params.get("group")) ??
    "category";
  const months = useMemo(
    () => applyOverlay(cashflow.spending?.months ?? [], overlay),
    [overlay],
  );
  const m = months.find((x) => x.month === month);

  const sections = useMemo(
    () =>
      buildMonthList({
        month: m,
        budgets:
          current && cashflow.budgets?.cycle_start.startsWith(month)
            ? cashflow.budgets
            : null,
        bills:
          current && cashflow.bills?.month === month ? cashflow.bills : null,
        fixed:
          current && cashflow.fixed_expenses?.month === month
            ? cashflow.fixed_expenses
            : null,
      }),
    [m, month, current],
  );

  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const [sheet, setSheet] = useState<SheetTarget | null>(null);
  const [editing, setEditing] = useState<EditTarget | null>(null);
  const [hiddenOpen, setHiddenOpen] = useState(false);
  const [query, setQuery] = useState("");
  const { swipeProps, sheets } = useQuickEdit();

  const setParam = (k: string, v: string | null) =>
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        if (v == null) p.delete(k);
        else p.set(k, v);
        return p;
      },
      { replace: true },
    );

  const openLine = (l: Line) =>
    setSheet({
      title: l.name,
      sub: l.charge
        ? `${l.charge.category ?? ""} · ${shekel(l.charge.amount)}`
        : undefined,
      txns: lineTransactions(m, l),
      budget: l.budget,
    });

  // Deep links: ?category=<name> opens its group and sheet; ?section=<key> scrolls to it.
  const linkCategory = params.get("category");
  const linkSection = params.get("section") as SectionKey | null;
  useEffect(() => {
    if (!linkCategory) return;
    const hit = findLine(sections, linkCategory);
    if (!hit) return;
    setOpen((prev) => new Set(prev).add(`${hit.section}|${hit.group}`));
    openLine(hit.line);
    requestAnimationFrame(() => scrollToSection(hit.section));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linkCategory, month]);
  useEffect(() => {
    if (linkSection) requestAnimationFrame(() => scrollToSection(linkSection));
  }, [linkSection, month]);

  const isOpen = (key: string, alert: boolean) => open.has(key) !== alert; // alert groups start open
  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  const txRow = (t: SpendingTransaction, i: number, withCategory = true) => (
    <TransactionRow
      key={`${t.date}-${t.amount}-${i}`}
      merchant={t.merchant}
      amount={-t.amount}
      date={t.date}
      category={withCategory ? t.category : undefined}
      tags={t.tags}
      edited={t.overridden || overlayFor(overlay, t)?.overridden}
      offset={t.offset}
      onClick={() => setEditing(t)}
      {...swipeProps(t, -t.amount)}
    />
  );

  const q = query.trim().toLowerCase();
  const flat = (m?.transactions ?? [])
    .filter(
      (t) =>
        !q ||
        t.merchant.toLowerCase().includes(q) ||
        String(t.amount).includes(q.replace(/[^\d.]/g, "") || "\0"),
    )
    .sort((a, b) => b.date.localeCompare(a.date));

  return (
    <>
      <div className="flex items-center justify-between gap-3">
        <Tabs
          value={groupBy}
          onValueChange={(v) => setParam("group", v === "category" ? null : v)}
          dir="rtl"
          className="flex-1"
        >
          <TabsList className="w-full">
            <TabsTrigger value="category">קטגוריה</TabsTrigger>
            <TabsTrigger value="merchant">בית עסק</TabsTrigger>
            <TabsTrigger value="none">ללא</TabsTrigger>
          </TabsList>
        </Tabs>
        <button
          type="button"
          className="shrink-0 text-xs text-muted-foreground underline"
          onClick={() => setHiddenOpen(true)}
        >
          מוסתרות
        </button>
      </div>

      {!m ? (
        <Card>
          <div className="text-sm text-muted-foreground">
            אין תנועות לחודש הזה.
          </div>
        </Card>
      ) : groupBy === "category" ? (
        sections.map((s) => (
          <div key={s.key} id={`sec-${s.key}`} className="scroll-mt-20">
            <Section title={`${s.label} · ${shekel(s.total)}`}>
              <Card className="!py-1">
                <ul className="divide-y divide-line">
                  {s.groups.map((g) => {
                    const key = `${s.key}|${g.name}`;
                    const expanded = isOpen(key, g.alert);
                    return (
                      <li key={key}>
                        <button
                          type="button"
                          aria-expanded={expanded}
                          onClick={() => toggle(key)}
                          className="flex w-full items-center gap-2 py-2.5 text-start"
                        >
                          <ChevronDown
                            className={cn(
                              "size-4 shrink-0 text-muted-foreground transition-transform",
                              !expanded && "rotate-90",
                            )}
                          />
                          <span className="min-w-0 flex-1 truncate font-semibold">
                            {g.name}
                          </span>
                          {g.alert && (
                            <span className="pill pill-warn whitespace-nowrap">
                              דורש תשומת לב
                            </span>
                          )}
                          <strong className="shrink-0 tabular-nums">
                            {shekel(g.total)}
                          </strong>
                        </button>
                        {expanded && (
                          <div className="divide-y divide-line pb-1 ps-6">
                            {g.lines.map((l) =>
                              l.charge ? (
                                <ChargeRow
                                  key={l.key}
                                  c={l.charge}
                                  onOpen={() => openLine(l)}
                                />
                              ) : (
                                <CategoryRow
                                  key={l.key}
                                  l={l}
                                  onOpen={() => openLine(l)}
                                />
                              ),
                            )}
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </Card>
            </Section>
          </div>
        ))
      ) : groupBy === "merchant" ? (
        <Card className="!py-1">
          <ul className="divide-y divide-line">
            {byMerchant(m).map((x) => (
              <li key={x.name}>
                <button
                  type="button"
                  className="flex w-full items-baseline justify-between gap-3 py-2.5 text-start"
                  onClick={() =>
                    setSheet({
                      title: x.name,
                      txns: m.transactions
                        .filter((t) => t.merchant === x.name)
                        .sort((a, b) => b.date.localeCompare(a.date)),
                    })
                  }
                >
                  <span className="min-w-0 truncate" dir="auto">
                    {x.name}
                    {x.count > 1 && (
                      <span className="ms-1 text-xs text-muted-foreground">
                        ×{x.count}
                      </span>
                    )}
                  </span>
                  <strong className="shrink-0 tabular-nums">
                    {shekel(x.amount)}
                  </strong>
                </button>
              </li>
            ))}
          </ul>
        </Card>
      ) : (
        <Card>
          <Input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="חיפוש בית עסק או סכום"
            aria-label="חיפוש תנועות"
            className="mb-2"
          />
          {flat.length === 0 ? (
            <div className="py-3 text-muted-foreground">אין תנועות.</div>
          ) : (
            <TransactionList>{flat.map((t, i) => txRow(t, i))}</TransactionList>
          )}
        </Card>
      )}

      {m && <ExcludedSpendingCard excluded={m.excluded} />}

      <Sheet
        open={sheet != null}
        onOpenChange={(o) => {
          if (o) return;
          setSheet(null);
          if (linkCategory) setParam("category", null);
        }}
      >
        <SheetContent
          side="bottom"
          className="max-h-[90dvh] overflow-y-auto"
          dir="rtl"
        >
          {sheet && (
            <>
              <SheetHeader>
                <SheetTitle className="text-lg font-bold">
                  {sheet.title}
                </SheetTitle>
                <SheetDescription className="tabular-nums">
                  {sheet.sub ??
                    `${shekel(sheet.txns.reduce((s, t) => s + net(t), 0))} · ${num(sheet.txns.length)} תנועות`}
                </SheetDescription>
              </SheetHeader>
              <div className="px-4 pb-4">
                {sheet.txns.length ? (
                  <TransactionList>
                    {sheet.txns.map((t, i) => txRow(t, i, false))}
                  </TransactionList>
                ) : (
                  <div className="py-2 text-sm text-muted-foreground">
                    אין תנועות החודש.
                  </div>
                )}
                {sheet.budget && (
                  <div className="mt-4 border-t border-line pt-3">
                    <div className="mb-1 font-semibold">תקציב</div>
                    <BudgetPlan key={sheet.budget.name} c={sheet.budget} />
                  </div>
                )}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
      <TransactionEditSheet tx={editing} onClose={() => setEditing(null)} />
      {sheets}
      <HiddenTransactionsSheet
        open={hiddenOpen}
        onClose={() => setHiddenOpen(false)}
      />
    </>
  );
}
