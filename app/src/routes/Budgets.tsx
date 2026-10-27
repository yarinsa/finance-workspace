import { useState } from "react";
import BudgetEditorSheet from "@/components/BudgetEditorSheet";
import { BigNumber, Card, CardLabel, Page, Section, StatRow } from "@/components/common";
import { cashflow, shekel } from "@/lib/data";
import type { BudgetCategory, BudgetSummary, Budgets as BudgetsData } from "@/lib/budgets";

/** Thin progress bar; overspend fills it fully in red. */
function Bar({ pct, over }: { pct: number; over?: boolean }) {
  return (
    <div className="h-2 overflow-hidden rounded-full bg-line">
      <div
        className={`h-full rounded-full ${over ? "bg-bad" : pct >= 90 ? "bg-warn" : "bg-brand"}`}
        style={{ width: `${Math.min(Math.max(pct, 0), 100)}%` }}
      />
    </div>
  );
}

function Hero({ b }: { b: BudgetsData }) {
  const over = b.left < 0;
  const pct = b.total_planned > 0 ? (b.total_spent / b.total_planned) * 100 : 0;
  return (
    <Card>
      <CardLabel>תקציב החודש</CardLabel>
      <BigNumber tone={over ? "bad" : undefined}>
        {over ? `חריגה ${shekel(-b.left)}` : `${shekel(b.left)} נותרו`}
      </BigNumber>
      <div className="mt-3">
        <Bar pct={pct} over={over} />
      </div>
      <div className="mt-2 text-sm text-muted-foreground">
        {shekel(b.total_spent)} מתוך {shekel(b.total_planned)}
      </div>
      {b.per_day != null && b.days_left > 0 && (
        <div className="mt-1 text-sm font-semibold">
          {shekel(b.per_day)} ליום ל-{b.days_left} ימים
        </div>
      )}
    </Card>
  );
}

/** "₪X מתוך ₪Y" when the expectation is above what happened so far. */
function soFar(actual: number, expected?: number | null) {
  return expected != null && expected > actual ? `${shekel(actual)} מתוך ${shekel(expected)}` : shekel(actual);
}

/**
 * The month in three blocks: fixed (קבוע), variable (משתנה, against the usual
 * month) and what is left — income minus both, minus loans and savings.
 */
function ThreeBlocks({ s }: { s: BudgetSummary }) {
  return (
    <Card>
      <CardLabel>החודש בשלושה חלקים</CardLabel>
      <BigNumber tone={s.left < 0 ? "bad" : undefined}>
        {s.left < 0 ? `חסרים ${shekel(-s.left)}` : `${shekel(s.left)} נשארים`}
      </BigNumber>
      <div className="mt-2">
        <StatRow label="הכנסות" value={soFar(s.income.actual, s.income.expected)} />
        <StatRow label="קבוע" value={soFar(s.fixed.actual, s.fixed.expected)} />
        <StatRow
          label={s.variable.estimate != null ? `משתנה · בחודש רגיל ${shekel(s.variable.estimate)}` : "משתנה"}
          value={shekel(s.variable.actual)}
          tone={s.variable.estimate != null && s.variable.actual > s.variable.estimate ? "bad" : undefined}
        />
        <StatRow label="הלוואות וחיסכון" value={soFar(s.debt_savings.actual, s.debt_savings.expected)} />
      </div>
    </Card>
  );
}

function Row({ c, onOpen }: { c: BudgetCategory; onOpen: () => void }) {
  const pct = c.planned > 0 ? (c.spent / c.planned) * 100 : c.spent > 0 ? 100 : 0;
  return (
    <button type="button" onClick={onOpen} className="block w-full border-b border-line py-3 text-start last:border-b-0">
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <span className="font-semibold">
          {c.name}
          {c.source === "override" && <span className="ms-1.5 text-xs font-normal text-muted-foreground">מותאם אישית</span>}
        </span>
        <span className={`text-sm font-bold tabular-nums ${c.over ? "text-bad" : ""}`}>
          {c.over ? `חריגה ${shekel(-c.left)}` : `${shekel(c.left)} נותרו`}
        </span>
      </div>
      <Bar pct={pct} over={c.over} />
      <div className="mt-1.5 text-xs text-muted-foreground tabular-nums">
        {shekel(c.spent)} מתוך {shekel(c.planned)}
        {c.estimate != null && ` · בחודש רגיל ${shekel(c.estimate)}`}
      </div>
    </button>
  );
}

export default function Budgets() {
  const [editing, setEditing] = useState<string | null>(null);
  const b = cashflow.budgets;
  return (
    <Page title="תקציב">
      {!b ? (
        <Card>
          <div className="text-sm text-muted-foreground">אין עדיין נתוני תקציב. רענן את RiseUp והרץ את הפייפליין.</div>
        </Card>
      ) : (
        <>
          {b.summary && <ThreeBlocks s={b.summary} />}
          <Hero b={b} />
          <Section title="לפי קטגוריה">
            <Card>
              {b.categories.map((c) => (
                <Row key={c.name} c={c} onOpen={() => setEditing(c.name)} />
              ))}
            </Card>
          </Section>
          <BudgetEditorSheet
            category={b.categories.find((c) => c.name === editing) ?? null}
            onClose={() => setEditing(null)}
          />
        </>
      )}
    </Page>
  );
}
