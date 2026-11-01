import type { ReactNode } from "react";
import { BigNumber, Card, CardLabel, StackedBar, StatRow } from "@/components/common";
import type { BudgetSummary } from "@/lib/budgets";
import { shekel, shekelSigned } from "@/lib/data";
import type { WidgetStats } from "@/lib/transactionsView";

/** One snap-aligned slide; the next one peeks in so the row reads as scrollable. */
export function Slide({ children }: { children: ReactNode }) {
  return <div className="w-[78%] max-w-[300px] shrink-0 snap-start">{children}</div>;
}

export function Legend({ tone, label, value }: { tone: string; label: string; value: number }) {
  return (
    <div className="flex items-center justify-between gap-2 text-sm">
      <span className="flex items-center gap-1.5 text-muted-foreground">
        <i className="size-2 rounded-full" style={{ background: tone }} />
        {label}
      </span>
      <span className="tabular-nums">{shekel(value)}</span>
    </div>
  );
}

/**
 * The "תנועות" stats, one card per slide. Every figure comes from the filtered rows, except
 * free money: that is the current budget cycle's, so it shows only under "הכל" and says so.
 */
export default function WidgetsCarousel({ w, cycle }: { w: WidgetStats; cycle: BudgetSummary | null }) {
  const spent = w.split.fixed + w.split.variable + w.split.other;
  return (
    <div className="-mx-1 flex snap-x snap-mandatory gap-3 overflow-x-auto px-1 pb-1" role="region" aria-label="סיכומים">
      <Slide>
        <Card>
          <CardLabel>נטו בטווח</CardLabel>
          <BigNumber tone={w.net < 0 ? "bad" : undefined}>{w.net > 0 ? shekelSigned(w.net) : shekel(w.net)}</BigNumber>
          <div className="mt-2 text-sm">
            <StatRow label="נכנס" value={shekel(w.in)} />
            <StatRow label="יצא" value={shekel(w.out)} />
          </div>
        </Card>
      </Slide>
      {spent > 0 && (
        <Slide>
          <Card>
            <CardLabel>קבוע ומשתנה</CardLabel>
            <StackedBar fixed={w.split.fixed} variable={w.split.variable} total={spent} className="mb-3" />
            <div className="flex flex-col gap-1.5">
              <Legend tone="var(--holst-1)" label="קבוע" value={w.split.fixed} />
              <Legend tone="var(--holst-4)" label="משתנה" value={w.split.variable} />
              {w.split.other > 0 && <Legend tone="var(--line)" label="אחר" value={w.split.other} />}
            </div>
          </Card>
        </Slide>
      )}
      {w.topCategories.length > 0 && (
        <Slide>
          <Card>
            <CardLabel>הכי הרבה הוצאה</CardLabel>
            <div className="text-sm">
              {w.topCategories.map((c) => (
                <StatRow key={c.name} label={c.name} value={shekel(c.amount)} />
              ))}
            </div>
          </Card>
        </Slide>
      )}
      {cycle && (
        <Slide>
          <Card to="/monthly">
            <CardLabel>כסף פנוי במחזור הנוכחי</CardLabel>
            <BigNumber tone={cycle.left < 0 ? "bad" : undefined}>
              {cycle.left < 0 ? `חסרים ${shekel(-cycle.left)}` : shekel(cycle.left)}
            </BigNumber>
            <div className="mt-2 text-xs text-muted-foreground">לפי התקציב, לא לפי הסינון</div>
          </Card>
        </Slide>
      )}
    </div>
  );
}
