import { BigNumber, Card, CardLabel } from "@/components/common";
import type { BudgetSummary } from "@/lib/budgets";
import { shekel, type MonthGroup } from "@/lib/data";
import type { SectionKey } from "@/lib/monthList";
import { cn } from "@/lib/utils";

/** Scroll the month list to one of its sections (ids `sec-<key>`). */
export function scrollToSection(key: SectionKey) {
  document
    .getElementById(`sec-${key}`)
    ?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function Figure({
  label,
  value,
  sub,
  bad,
  to,
}: {
  label: string;
  value: string;
  sub?: string;
  bad?: boolean;
  to?: SectionKey;
}) {
  const body = (
    <>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div
        className={cn(
          "font-display text-[20px] font-semibold tabular-nums",
          bad && "text-bad",
        )}
      >
        {value}
      </div>
      {sub && (
        <div className="truncate text-[11px] text-muted-foreground tabular-nums">
          {sub}
        </div>
      )}
    </>
  );
  const cls = "min-w-0 rounded-xl bg-panel-2 px-2.5 py-2 text-start";
  return to ? (
    <button
      type="button"
      className={cn(cls, "active:opacity-70")}
      onClick={() => scrollToSection(to)}
    >
      {body}
    </button>
  ) : (
    <div className={cls}>{body}</div>
  );
}

/** "₪X מתוך ₪Y" when the expectation is above what happened so far. */
const ofExpected = (actual: number, expected?: number | null) =>
  expected != null && expected > actual
    ? `מתוך ${shekel(expected)}`
    : undefined;

/**
 * Top of the current month: free money (income − fixed − debt/savings − the variable plan;
 * aim ~0), where the pace lands it, and income / fixed / variable. A figure scrolls to its section.
 */
export function FreeMoneyCard({ s }: { s: BudgetSummary }) {
  const v = s.variable;
  const plan = v.planned ?? v.estimate;
  return (
    <Card>
      <CardLabel>כסף פנוי (לא מתוכנן)</CardLabel>
      <BigNumber tone={s.left < 0 ? "bad" : undefined}>
        {s.left < 0 ? `חסרים ${shekel(-s.left)}` : shekel(s.left)}
      </BigNumber>
      {s.projected_end != null && (
        <div
          className={cn(
            "text-xs",
            s.projected_end < 0 ? "text-bad" : "text-muted-foreground",
          )}
        >
          {s.projected_end < 0
            ? `בקצב הנוכחי: חסרים ${shekel(-s.projected_end)} בסוף החודש`
            : `בקצב הנוכחי: ${shekel(s.projected_end)} בסוף החודש`}
        </div>
      )}
      <div className="mt-3 grid grid-cols-3 gap-2">
        <Figure
          label="הכנסות"
          value={shekel(s.income.actual)}
          sub={ofExpected(s.income.actual, s.income.expected)}
        />
        <Figure
          label="קבוע"
          value={shekel(s.fixed.actual)}
          sub={ofExpected(s.fixed.actual, s.fixed.expected)}
          to="fixed"
        />
        <Figure
          label="משתנה"
          value={shekel(v.actual)}
          sub={[
            plan != null ? `מתוך ${shekel(plan)}` : null,
            v.projected != null ? `צפוי ${shekel(v.projected)}` : null,
          ]
            .filter(Boolean)
            .join(" · ")}
          bad={plan != null && (v.projected ?? v.actual) > plan}
          to="variable"
        />
      </div>
      <button
        type="button"
        onClick={() => scrollToSection("debt_savings")}
        className="mt-2 flex w-full items-baseline justify-between text-sm text-muted-foreground"
      >
        <span>הלוואות וחיסכון</span>
        <strong className="tabular-nums text-foreground">
          {shekel(s.debt_savings.actual)}
          {ofExpected(s.debt_savings.actual, s.debt_savings.expected) && (
            <span className="font-normal text-muted-foreground">
              {" "}
              {ofExpected(s.debt_savings.actual, s.debt_savings.expected)}
            </span>
          )}
        </strong>
      </button>
    </Card>
  );
}

/** A past (or summary-less) month: the same three figures from months_view's actuals. */
export function MonthFigures({ groups }: { groups: MonthGroup[] }) {
  const g = (k: MonthGroup["key"]) => groups.find((x) => x.key === k);
  const val = (x?: MonthGroup) => (x?.actual != null ? shekel(x.actual) : "—");
  const plan = (x?: MonthGroup) =>
    x?.expected != null && x.actual != null
      ? `מתוכנן ${shekel(x.expected)}`
      : undefined;
  if (!groups.length) return null;
  return (
    <div className="grid grid-cols-3 gap-2">
      <Figure label="הכנסות" value={val(g("income"))} sub={plan(g("income"))} />
      <Figure
        label="קבוע"
        value={val(g("fixed"))}
        sub={plan(g("fixed"))}
        to="fixed"
      />
      <Figure
        label="משתנה"
        value={val(g("variable"))}
        sub={plan(g("variable"))}
        to="variable"
      />
    </div>
  );
}
