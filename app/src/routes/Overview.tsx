import { Card, Kpi, PageTitle } from "@/components/common";
import NetWorthChart from "@/components/NetWorthChart";
import { cashflow, daysSince, shekel } from "@/lib/data";

function fmtMetric(value: number, units: string): string {
  if (units === "₪") return shekel(value);
  if (units === "%") return `${value.toFixed(1)}%`;
  return value.toLocaleString("he-IL");
}

export default function Overview() {
  const { metrics, today, projection } = cashflow;
  const netToday = projection?.net_worth_today ?? null;
  const netRetire = projection?.net_worth_at_retirement ?? null;
  const stale = daysSince(cashflow.generated_at) > 7;
  const topMetrics = metrics.slice(0, 4);

  return (
    <div>
      <PageTitle>היי 👋</PageTitle>
      <p className="muted" style={{ marginTop: -12 }}>
        להלן מבט מהיר לתמונת המצב הפיננסית שלך
      </p>

      {stale && (
        <div className="nudge">
          <span>🕑 הגיע זמן לעדכן את היתרות שלך — הנתונים מלפני {daysSince(cashflow.generated_at)} ימים.</span>
          <span className="cta">לעדכון יתרות ▸</span>
        </div>
      )}

      <div className="grid grid-2">
        <Card to="/networth">
          <div className="card-title">שווי נקי נוכחי</div>
          <div className="big-num">{netToday != null ? shekel(netToday) : "—"}</div>
          <div className="muted">סך כל הנכסים שלך פחות התחייבויות</div>
        </Card>
        <Card to="/cashflow">
          <div className="card-title">התזרים — נכון להיום</div>
          <div className="big-num" style={{ color: today.net >= 0 ? "var(--lg-good)" : "var(--lg-bad)" }}>
            {shekel(today.net)}
          </div>
          <div className="muted">
            הכנסות {shekel(today.income)} · הוצאות {shekel(today.expense)}
          </div>
        </Card>
      </div>

      <div className="grid grid-4 section-gap">
        {topMetrics.map((m) => (
          <Card key={m.key} to="/metrics">
            <Kpi label={m.name} value={fmtMetric(m.value, m.units)} rank={m.rank} hint={m.description} />
          </Card>
        ))}
      </div>

      <Card to="/networth" className="section-gap">
        <div className="card-title">שווי נקי — לאורך החיים</div>
        <NetWorthChart height={220} />
        {netRetire != null && (
          <div className="muted section-gap">בפרישה צפוי שווי נקי של כ-{shekel(netRetire)}</div>
        )}
      </Card>
    </div>
  );
}
