import { BarRow, Card, CardLabel, Kpi, KpiGrid, PageTitle, StatRow } from "@/components/common";
import NetWorthChart from "@/components/NetWorthChart";
import { cashflow, shekel, transactions, formatMetric, formatMetricCompact } from "@/lib/data";

export default function Cashflow() {
  const { metrics, today } = cashflow;
  const kpis = metrics.slice(0, 5);
  const expenseCats = Object.entries(transactions.summary.by_category)
    .map(([k, v]) => [k, Math.abs(v)] as const)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6);
  const maxCat = expenseCats[0]?.[1] ?? 1;

  return (
    <div className="space-y-4 md:space-y-[18px]">
      <PageTitle>תזרים כספי</PageTitle>

      <KpiGrid cols={5}>
        {kpis.map((m) => (
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

      {/* Phones: this month's numbers first — they're what you open the screen for. */}
      <div className="grid gap-3 md:grid-cols-2 md:gap-3.5">
        <Card to="/networth" className="max-md:order-2">
          <CardLabel>שווי נקי — לאורך החיים</CardLabel>
          <NetWorthChart />
        </Card>

        <Card>
          <CardLabel>התזרים — נכון לחודש זה</CardLabel>
          <StatRow label="הכנסות" value={shekel(today.income)} />
          <StatRow label="הוצאות" value={shekel(today.expense)} />
          <StatRow
            label="תזרים"
            value={shekel(today.net)}
            tone={today.net >= 0 ? "good" : "bad"}
          />
        </Card>
      </div>

      <Card>
        <CardLabel>הוצאות לפי קטגוריה</CardLabel>
        {expenseCats.map(([cat, amt]) => (
          <BarRow key={cat} label={cat} value={shekel(amt)} fraction={amt / maxCat} />
        ))}
      </Card>
    </div>
  );
}
