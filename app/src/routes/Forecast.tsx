import { Area, AreaChart, ResponsiveContainer, YAxis } from "recharts";
import { Card, CardLabel, PageTitle, Section, StatRow } from "@/components/common";
import GroupLinks from "@/components/GroupLinks";
import RunwayTeaser from "@/components/RunwayTeaser";
import { noAnim, useChartColors } from "@/components/chartTheme";
import { cashflow, forecast, monthYear, shekel, shekelSigned } from "@/lib/data";

/** Tiny balance-path sparkline; the full chart with markers lives at /runway. */
function RunwaySpark() {
  const C = useChartColors();
  const r = cashflow.runway;
  if (!r || !r.days.length) return null;
  const vals = r.days.map((d) => d.balance);
  const lo = Math.min(-Math.abs(r.overdraft_limit), ...vals);
  const hi = Math.max(0, ...vals);
  return (
    <Card to="/runway">
      <CardLabel>מסלול היתרה בחשבון</CardLabel>
      <div dir="ltr">
        <ResponsiveContainer width="100%" height={110}>
          <AreaChart data={r.days} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
            <YAxis hide domain={[lo, hi]} />
            <Area dataKey="balance" type="stepAfter" stroke={C.accent} strokeWidth={2} fill={C.accent}
              fillOpacity={0.15} dot={false} {...noAnim} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-1 text-sm text-muted-foreground">
        הנקודה הנמוכה: {shekel(r.low_point.balance)}
      </div>
    </Card>
  );
}

/** Full-month expectation from forecast.py's envelopes (cashflow.pace.expected). */
function MonthExpectation() {
  const e = cashflow.pace?.expected;
  if (!e) return null;
  return (
    <Card to="/cashflow">
      <CardLabel>צפי לסוף החודש</CardLabel>
      <div className={`text-[28px] leading-tight font-extrabold tabular-nums ${e.net < 0 ? "text-bad" : "text-good"}`}>
        {shekelSigned(e.net)}
      </div>
      <div className="mt-2">
        <StatRow label="הכנסות צפויות" value={shekel(e.income)} />
        <StatRow label="הוצאות צפויות" value={shekel(e.expense)} />
      </div>
    </Card>
  );
}

/** Multi-month projection from forecast.json, with the running total of monthly nets. */
function ForecastMonths() {
  const months = forecast?.months ?? [];
  if (!months.length) return null;
  let running = 0;
  return (
    <Card>
      <CardLabel>תחזית ל-{months.length} חודשים</CardLabel>
      {months.map((m) => {
        running += m.projected_net;
        return (
          <div key={m.forecast_month} className="flex items-center justify-between gap-3 border-b border-border py-2.5 last:border-0">
            <div className="min-w-0">
              <div className="font-semibold">
                {monthYear(`${m.forecast_month}-01`)}
                {m.confidence !== "high" && <span className="ms-2 text-xs font-normal text-muted-foreground">משוער</span>}
              </div>
              <div className="text-xs text-muted-foreground tabular-nums">
                {shekel(m.income.total)} הכנסות · {shekel(m.expenses.total)} הוצאות
              </div>
            </div>
            <div className="text-end tabular-nums">
              <div className={`font-bold ${m.projected_net < 0 ? "text-bad" : "text-good"}`}>{shekelSigned(m.projected_net)}</div>
              <div className="text-xs text-muted-foreground">מצטבר {shekelSigned(running)}</div>
            </div>
          </div>
        );
      })}
      <div className="mt-2 text-xs text-muted-foreground">
        חודש ראשון לפי תקציב RiseUp הנוכחי; החודשים הבאים ממשיכים אותו, כולל שינויים ידועים במשכנתא.
      </div>
    </Card>
  );
}

/** Forward-looking hub: safe-to-spend, balance path, month expectation, links to the deep pages. */
export default function Forecast() {
  const hasAny = cashflow.runway || cashflow.pace?.expected || forecast?.months.length;
  return (
    <div className="feed">
      <PageTitle>תזרים</PageTitle>
      {cashflow.runway && <RunwayTeaser runway={cashflow.runway} />}
      <RunwaySpark />
      {cashflow.pace?.expected && (
        <Section title="החודש הנוכחי" to="/cashflow">
          <MonthExpectation />
        </Section>
      )}
      {!!forecast?.months.length && (
        <Section title="החודשים הבאים">
          <ForecastMonths />
        </Section>
      )}
      {!hasAny && <p className="muted">אין עדיין תחזית — הריצו את הפייפליין לעדכון.</p>}
      <GroupLinks group="forecast" />
    </div>
  );
}
