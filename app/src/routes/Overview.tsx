import { BigNumber, Card, CardLabel, Kpi, KpiGrid, Nudge, PageTitle } from "@/components/common";
import NetWorthChart from "@/components/NetWorthChart";
import { cashflow, daysSince, shekel, formatMetric, formatMetricCompact } from "@/lib/data";

export default function Overview() {
  const { metrics, today, projection } = cashflow;
  const netToday = projection?.net_worth_today ?? null;
  const netRetire = projection?.net_worth_at_retirement ?? null;
  const days = daysSince(cashflow.generated_at);
  const topMetrics = metrics.slice(0, 4);

  return (
    <div className="space-y-4 md:space-y-[18px]">
      <div>
        <PageTitle>היי 👋</PageTitle>
        <p className="-mt-3 text-muted-foreground max-md:hidden">
          להלן מבט מהיר לתמונת המצב הפיננסית שלך
        </p>
      </div>

      {days > 7 && (
        <Nudge action="לעדכון יתרות ▸">
          🕑 הגיע זמן לעדכן את היתרות שלך — הנתונים מלפני {days} ימים.
        </Nudge>
      )}

      <div className="grid gap-3 md:grid-cols-2 md:gap-3.5">
        <Card to="/networth">
          <CardLabel>שווי נקי נוכחי</CardLabel>
          <BigNumber>{netToday != null ? shekel(netToday) : "—"}</BigNumber>
          <div className="mt-1 text-muted-foreground">סך כל הנכסים שלך פחות התחייבויות</div>
        </Card>
        <Card to="/cashflow">
          <CardLabel>התזרים — נכון להיום</CardLabel>
          <BigNumber tone={today.net >= 0 ? "good" : "bad"}>{shekel(today.net)}</BigNumber>
          <div className="mt-1 text-muted-foreground">
            הכנסות {shekel(today.income)} · הוצאות {shekel(today.expense)}
          </div>
        </Card>
      </div>

      <KpiGrid cols={4}>
        {topMetrics.map((m) => (
          <Card key={m.key} to="/metrics">
            <Kpi
              label={m.name}
              value={formatMetric(m.value, m.units)}
              compactValue={formatMetricCompact(m.value, m.units)}
              rank={m.rank}
              hint={m.description}
            />
          </Card>
        ))}
      </KpiGrid>

      <Card to="/networth">
        <CardLabel>שווי נקי — לאורך החיים</CardLabel>
        <NetWorthChart height={220} />
        {netRetire != null && (
          <div className="mt-4 text-muted-foreground">
            בפרישה צפוי שווי נקי של כ-{shekel(netRetire)}
          </div>
        )}
      </Card>
    </div>
  );
}
