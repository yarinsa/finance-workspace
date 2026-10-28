import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ChevronDown } from "lucide-react";
import {
  Card,
  ProgressBar,
  Section,
  SectionLabel,
  StackedBar,
  StatusPill,
} from "@/components/common";
import BudgetPlan from "@/components/BudgetPlan";
import CategoryMergeSheet from "@/components/CategoryMergeSheet";
import ExcludedSpendingCard from "@/components/ExcludedSpendingCard";
import HiddenTransactionsSheet from "@/components/HiddenTransactionsSheet";
import { TransactionList, TransactionRow } from "@/components/TransactionRow";
import TransactionEditSheet, {
  type EditTarget,
} from "@/components/TransactionEditSheet";
import { useQuickEdit } from "@/components/QuickEditSheets";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { scrollToSection } from "@/components/cashflow/MonthStats";
import type { BudgetCategory } from "@/lib/budgets";
import { cashflow, num, shekel, useDataVersion } from "@/lib/data";
import { applyOverlay, overlayFor } from "@/lib/ledgerOverlay";
import {
  buildCards,
  buildMonthList,
  unassignedTransactions,
  chargeHint,
  findLine,
  lineTransactions,
  net,
  type ChargeItem,
  type Line,
  type SectionKey,
  type SpendCard,
} from "@/lib/monthList";
import type { SpendingTransaction } from "@/lib/spending";
import { useLedgerApi } from "@/lib/useLedgerApi";
import { cn } from "@/lib/utils";

/** What the drill-down sheet shows: a title, the transactions, and the plan editor when there is a budget line. */
interface SheetTarget {
  title: string;
  sub?: string;
  /** A fixed charge's saving hint (chargeHint). */
  hint?: string | null;
  txns: SpendingTransaction[];
  budget?: BudgetCategory;
}

/** The calm bar stays forest; the amount carries the verdict: terracotta over, ochre nearly spent. */
function amountTone(pct: number, over: boolean): string {
  return over ? "text-bad" : pct >= 90 ? "text-warn" : "";
}

/** A fixed charge: status (✓ paid / due day / overdue), flags from the "what can I cut?" review. */
function ChargeRow({
  c,
  onOpen,
  withCategory = false,
}: {
  c: ChargeItem;
  onOpen: () => void;
  /** Say its category: only outside a category card (the loans list). */
  withCategory?: boolean;
}) {
  const paid = c.status === "paid";
  const overdue = c.status === "overdue";
  const hint = chargeHint(c);
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
          {withCategory && c.category && <span>{c.category}</span>}
          {overdue && <StatusPill tone="warn">עוד לא חויב</StatusPill>}
          {c.status === "upcoming" && (
            <span>
              {c.due_day != null ? `צפוי ב-${num(c.due_day)}` : "צפוי החודש"}
            </span>
          )}
          {c.estimated && <span>משוער</span>}
        </span>
        {hint && (
          <span className="mt-0.5 text-xs text-muted-foreground">{hint}</span>
        )}
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
/** A utility's bill on its variable row: "חשבון" + paid / due / overdue (/ estimated). */
function BillStatus({ c }: { c: ChargeItem }) {
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground tabular-nums">
      <span className="font-semibold">חשבון</span>
      {c.status === "paid" && <span>שולם ✓</span>}
      {c.status === "overdue" && (
        <StatusPill tone="warn">עוד לא חויב</StatusPill>
      )}
      {c.status === "upcoming" && (
        <span>
          {c.due_day != null ? `צפוי ב-${num(c.due_day)}` : "צפוי החודש"} ·{" "}
          {shekel(c.amount)}
        </span>
      )}
      {c.estimated && <span>משוער</span>}
    </div>
  );
}

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
          {l.scope === "group" ? l.parts?.join(", ") || "משתנה" : l.name}
          {b?.source === "unplanned" && !l.bill && (
            <span className="ms-1.5 text-xs text-muted-foreground">
              לא מתוכנן
            </span>
          )}
        </span>
        <strong
          className={cn(
            "shrink-0 text-sm tabular-nums",
            planned && amountTone(pct, planned.over),
          )}
        >
          {planned
            ? `${shekel(planned.spent)} מתוך ${shekel(planned.planned)}`
            : shekel(l.amount)}
        </strong>
      </div>
      {planned && (
        <div className="mt-1.5">
          <ProgressBar value={pct / 100} />
        </div>
      )}
      {l.bill && <BillStatus c={l.bill} />}
      {b && (
        <div className="mt-1 text-xs text-muted-foreground tabular-nums">
          {planned
            ? planned.over
              ? `${shekel(-planned.left)} מעל התקציב`
              : `${shekel(planned.left)} נותרו`
            : null}
          {b.estimate != null &&
            `${planned ? " · " : ""}בחודש רגיל ${shekel(b.estimate)}`}
        </div>
      )}
    </button>
  );
}

function LineRow({
  l,
  onOpen,
  withCategory,
}: {
  l: Line;
  onOpen: () => void;
  withCategory?: boolean;
}) {
  return l.charge ? (
    <ChargeRow c={l.charge} onOpen={onOpen} withCategory={withCategory} />
  ) : (
    <CategoryRow l={l} onOpen={onOpen} />
  );
}

/**
 * A category group's card: actual of planned with a bar split into its fixed and
 * variable parts; tapping it lists the fixed charges and the variable lines. An alert
 * card starts open and its rows say what to check, so the card itself carries no pill.
 */
function SpendCardView({
  c,
  expanded,
  onToggle,
  onOpen,
  onMerge,
}: {
  c: SpendCard;
  expanded: boolean;
  onToggle: () => void;
  onOpen: (l: Line) => void;
  /** A top-level category: merge it into another one. */
  onMerge?: () => void;
}) {
  const plan = c.planned;
  const pct = plan ? (c.actual / plan) * 100 : c.actual > 0 ? 100 : 0;
  const both = c.fixedLines.length > 0 && c.variableLines.length > 0;
  // A category card that is just its own budget line: the card already is that line.
  const self =
    c.fixedLines.length === 0 &&
    c.variableLines.length === 1 &&
    c.variableLines[0].category === c.name
      ? c.variableLines[0]
      : null;
  const parts = [
    c.fixed + c.fixedPending > 0 &&
      `קבוע ${shekel(c.fixed)}${c.fixedPending > 0.005 ? ` + ${shekel(c.fixedPending)} צפוי` : ""}`,
    c.variableLines.length > 0 &&
      `משתנה ${shekel(c.variable)}${c.variablePlan > 0 ? ` מתוך ${shekel(c.variablePlan)}` : ""}`,
  ].filter(Boolean);
  return (
    <Card className="!px-4 !py-3">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={onToggle}
        className="block w-full text-start"
      >
        <div className="flex items-baseline gap-2">
          <ChevronDown
            className={cn(
              "size-4 shrink-0 self-center text-muted-foreground transition-transform",
              !expanded && "rotate-90",
            )}
          />
          <span className="min-w-0 flex-1 truncate font-semibold">
            {c.name}
          </span>
          <strong
            className={cn(
              "shrink-0 text-sm tabular-nums",
              plan != null && amountTone(pct, c.over),
            )}
          >
            {plan != null
              ? `${shekel(c.actual)} מתוך ${shekel(plan)}`
              : shekel(c.actual)}
          </strong>
        </div>
        <StackedBar
          className="mt-2"
          fixed={c.fixed}
          variable={c.variable}
          total={plan ?? c.actual}
        />
        <div className="mt-1.5 flex flex-wrap justify-between gap-x-3 text-xs text-muted-foreground tabular-nums">
          <span>{parts.join(" · ")}</span>
          {plan != null && (
            <span className={cn(c.over && "text-bad")}>
              {c.over
                ? `${shekel(c.actual - plan)} מעל התכנון`
                : `${shekel(plan - c.actual)} נותרו`}
            </span>
          )}
        </div>
      </button>
      {expanded && c.lever && (
        <div className="mt-2 text-xs text-muted-foreground">{c.lever}</div>
      )}
      {expanded && self && (
        <button
          type="button"
          onClick={() => onOpen(self)}
          className="mt-2 flex w-full items-baseline justify-between text-xs text-muted-foreground tabular-nums"
        >
          <span>
            {self.budget?.estimate != null &&
              `בחודש רגיל ${shekel(self.budget.estimate)}`}
          </span>
          <span className="font-semibold text-brand">תנועות ותכנון ›</span>
        </button>
      )}
      {expanded && (
        <div className="mt-1">
          {!self && c.fixedLines.length > 0 && (
            <>
              {both && <SectionLabel className="mt-2">קבוע</SectionLabel>}
              <div className="divide-y divide-line">
                {c.fixedLines.map((l) => (
                  <LineRow key={l.key} l={l} onOpen={() => onOpen(l)} />
                ))}
              </div>
            </>
          )}
          {!self && c.variableLines.length > 0 && (
            <>
              {both && <SectionLabel className="mt-2">משתנה</SectionLabel>}
              <div className="divide-y divide-line">
                {c.variableLines.map((l) => (
                  <LineRow key={l.key} l={l} onOpen={() => onOpen(l)} />
                ))}
              </div>
            </>
          )}
          {onMerge && (
            <button
              type="button"
              onClick={onMerge}
              className="mt-2 text-xs text-muted-foreground underline"
            >
              מיזוג לקטגוריה אחרת
            </button>
          )}
        </div>
      )}
    </Card>
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

  const cards = useMemo(
    () => buildCards(sections),
    [sections],
  );
  const spendTotal = cards.reduce((t, c) => t + c.actual, 0);

  // fees + subscriptions: the low-effort ceiling of the fixed review, current cycle only
  const cuttable =
    current && cashflow.fixed_expenses?.month === month
      ? cashflow.fixed_expenses.cuttable_total
      : 0;
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const [sheet, setSheet] = useState<SheetTarget | null>(null);
  const [editing, setEditing] = useState<EditTarget | null>(null);
  const [hiddenOpen, setHiddenOpen] = useState(false);
  const [merging, setMerging] = useState<string | null>(null);
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
      hint: l.charge ? chargeHint(l.charge) : null,
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
    setOpen((prev) =>
      new Set(prev).add(
        `card|${hit.line.category ?? hit.line.name}`,
      ),
    );
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

  // Rows with no category group (an unmapped label or none): triage them into a
  // category from the edit sheet, or leave them as they are.
  const unassigned = unassignedTransactions(m);
  const unassignedTotal = unassigned.reduce((t, x) => t + net(x), 0);

  return (
    <>
      <div className="flex justify-end">
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
      ) : (
        <>
          {(cards.length > 0 || unassigned.length > 0) && (
            <div id="sec-spend" className="scroll-mt-20">
              <Section title={`הוצאות · ${shekel(spendTotal + unassignedTotal)}`}>
                {cuttable > 0 && (
                  <div className="-mt-1.5 mb-2.5 text-xs text-muted-foreground">
                    עד {shekel(cuttable)} בחודש בעמלות ומנויים אפשר לבדוק בקלות
                  </div>
                )}
                {cards.some((c) => c.fixed + c.fixedPending > 0) && (
                  <div className="mix-legend -mt-1 mb-2.5 text-muted-foreground">
                    <span>
                      <i className="mix-fixed" />
                      קבוע
                    </span>
                    <span>
                      <i className="mix-var" />
                      משתנה
                    </span>
                  </div>
                )}
                <div className="flex flex-col gap-2.5">
                  {unassigned.length > 0 && (
                    <Card className="!px-4 !py-3">
                      <div className="flex items-baseline gap-2">
                        <span className="min-w-0 flex-1 font-semibold">
                          לא משויך
                        </span>
                        <strong className="shrink-0 text-sm tabular-nums">
                          {shekel(unassignedTotal)}
                        </strong>
                      </div>
                      <div className="mt-0.5 text-xs text-muted-foreground">
                        {num(unassigned.length)} תנועות בלי קטגוריה · לחיצה
                        לשיוך, או להשאיר כך
                      </div>
                      <TransactionList>
                        {unassigned.map((t, i) => txRow(t, i, false))}
                      </TransactionList>
                    </Card>
                  )}
                  {cards.map((c) => {
                    const key = `card|${c.name}`;
                    return (
                      <SpendCardView
                        key={key}
                        c={c}
                        expanded={isOpen(key, c.alert)}
                        onToggle={() => toggle(key)}
                        onOpen={openLine}
                        onMerge={
                          c.category ? () => setMerging(c.name) : undefined
                        }
                      />
                    );
                  })}
                </div>
              </Section>
            </div>
          )}
          {sections
            .filter((s) => s.key === "debt_savings")
            .map((s) => (
              <div key={s.key} id={`sec-${s.key}`} className="scroll-mt-20">
                <Section title={`${s.label} · ${shekel(s.total)}`}>
                  <Card className="!py-1">
                    <div className="divide-y divide-line">
                      {s.groups
                        .flatMap((g) => g.lines)
                        .sort((x, y) => y.amount - x.amount)
                        .map((l) => (
                          <LineRow
                            key={l.key}
                            l={l}
                            withCategory
                            onOpen={() => openLine(l)}
                          />
                        ))}
                    </div>
                  </Card>
                </Section>
              </div>
            ))}
        </>
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
                <SheetTitle className="font-display text-xl font-medium">
                  {sheet.title}
                </SheetTitle>
                <SheetDescription className="tabular-nums">
                  {sheet.sub ??
                    `${shekel(sheet.txns.reduce((s, t) => s + net(t), 0))} · ${num(sheet.txns.length)} תנועות`}
                </SheetDescription>
                {sheet.hint && (
                  <div className="text-sm text-muted-foreground">
                    {sheet.hint}
                  </div>
                )}
              </SheetHeader>
              <div className="px-4 pb-4">
                {sheet.budget && (
                  <div className="mb-4 border-b border-line pb-4">
                    <SectionLabel className="mb-1">תקציב</SectionLabel>
                    <BudgetPlan key={sheet.budget.name} c={sheet.budget} />
                  </div>
                )}
                <SectionLabel className="mb-1">תנועות החודש</SectionLabel>
                {sheet.txns.length ? (
                  <TransactionList>
                    {sheet.txns.map((t, i) => txRow(t, i, false))}
                  </TransactionList>
                ) : (
                  <div className="py-2 text-sm text-muted-foreground">
                    אין תנועות החודש.
                  </div>
                )}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
      <TransactionEditSheet tx={editing} onClose={() => setEditing(null)} />
      {sheets}
      <CategoryMergeSheet
        category={merging}
        targets={cards
          .filter((c) => c.category && c.name !== merging)
          .map((c) => c.name)}
        onClose={() => setMerging(null)}
      />
      <HiddenTransactionsSheet
        open={hiddenOpen}
        onClose={() => setHiddenOpen(false)}
      />
    </>
  );
}
