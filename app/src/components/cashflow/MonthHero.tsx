import { BigNumber, Card, CardLabel } from "@/components/common";
import { PaceTrend } from "@/components/PaceDetails";
import { cashflow, monthYear, shekel, shekelSigned, type MonthViewRow } from "@/lib/data";
import { cn } from "@/lib/utils";

export type MonthViewMode = "actual" | "forecast";

const monthName = (ym: string) =>
  new Intl.DateTimeFormat("he-IL", { month: "long" }).format(new Date(`${ym}-01T12:00:00`));

const shortDate = (iso: string) =>
  new Intl.DateTimeFormat("he-IL", { day: "numeric", month: "short" }).format(new Date(`${iso.slice(0, 10)}T12:00:00`));

/**
 * The one number of the month screen, per view:
 * - actual, current month: net so far on the dark hero, with the pace-vs-last-month trend;
 * - actual, past month: the month's final net;
 * - forecast, current month: expected end-of-month net plus the lowest balance before payday;
 * - forecast, later month: the expected net, flagged "תחזית" and drawn with a dashed edge so
 *   it never reads as money that moved.
 */
export default function MonthHero({ m, mode }: { m: MonthViewRow; mode: MonthViewMode }) {
  const projected = m.kind === "projected";
  const runway = cashflow.runway;

  if (mode === "actual") {
    const pace = cashflow.pace;
    const showPace = m.kind === "current" && pace && pace.current.month === m.month;
    if (showPace) {
      return (
        <section className="wallet">
          <div className="wallet-card">
            <div className="wallet-top">
              <span className="wallet-label">תזרים נקי עד היום</span>
              <span className="wallet-asof">
                נכון ל-{pace.as_of_day} ב{monthName(m.month)}
              </span>
            </div>
            <div className="wallet-balance">{shekelSigned(m.net)}</div>
            <div className="wallet-sub">
              הכנסות {shekel(m.income)} · הוצאות {shekel(m.expense)}
            </div>
            <PaceTrend pace={pace} />
          </div>
        </section>
      );
    }
    return (
      <Card>
        <CardLabel>{monthYear(`${m.month}-01`)}</CardLabel>
        <BigNumber tone={m.net >= 0 ? "good" : "bad"}>{shekelSigned(m.net)}</BigNumber>
        <div className="mt-1 text-sm text-muted-foreground">
          הכנסות {shekel(m.income)} · הוצאות {shekel(m.expense)}
        </div>
      </Card>
    );
  }

  // Forecast view: the current month shows where it is expected to land.
  const end = m.kind === "current" ? m.projected_end : null;
  const net = end ? end.net : m.net;
  const income = end ? end.income : m.income;
  const expense = end ? end.expense : m.expense;
  const low = m.kind === "current" && runway ? (runway.low_before_payday ?? runway.low_point) : null;

  return (
    <Card className={cn("border-dashed", projected && "bg-panel-2/40")}>
      <div className="flex items-center justify-between gap-2">
        <CardLabel>{m.kind === "current" ? "צפי לסוף החודש" : `צפי ל${monthYear(`${m.month}-01`)}`}</CardLabel>
        <span className="pill pill-muted -mt-2">תחזית</span>
      </div>
      <BigNumber tone={net >= 0 ? "good" : "bad"}>{shekelSigned(net)}</BigNumber>
      <div className="mt-1 text-sm text-muted-foreground">
        הכנסות צפויות {shekel(income)} · הוצאות צפויות {shekel(expense)}
      </div>
      {m.kind === "current" && (
        <div className="mt-1 text-sm text-muted-foreground">
          עד היום <strong className="tabular-nums">{shekelSigned(m.net)}</strong>
        </div>
      )}
      {low && (
        <div className="mt-3 border-t border-line pt-3 text-sm">
          <span className="text-muted-foreground">היתרה הנמוכה ביותר עד המשכורת </span>
          <strong className={cn("tabular-nums", low.balance < 0 ? "text-bad" : "text-foreground")}>
            {shekel(low.balance)}
          </strong>
          <span className="text-muted-foreground"> · {shortDate(low.date)}</span>
        </div>
      )}
    </Card>
  );
}
