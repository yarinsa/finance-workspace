import { Card, Kpi, PageTitle } from "@/components/common";
import NetWorthChart from "@/components/NetWorthChart";
import { cashflow, shekel, transactions } from "@/lib/data";

function fmtMetric(value: number, units: string): string {
  if (units === "₪") return shekel(value);
  if (units === "%") return `${value.toFixed(1)}%`;
  return value.toLocaleString("he-IL");
}

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
    <div>
      <PageTitle>תזרים כספי</PageTitle>

      <div className="grid grid-5">
        {kpis.map((m) => (
          <Card key={m.key} to="/metrics">
            <Kpi
              label={m.name}
              value={fmtMetric(m.value, m.units)}
              rank={m.rank}
              hint={m.description}
            />
          </Card>
        ))}
      </div>

      <div className="grid grid-2 section-gap">
        <Card to="/networth">
          <div className="card-title">שווי נקי — לאורך החיים</div>
          <NetWorthChart />
        </Card>

        <Card>
          <div className="card-title">התזרים — נכון לחודש זה</div>
          <div className="row">
            <span>הכנסות</span>
            <strong>{shekel(today.income)}</strong>
          </div>
          <div className="row">
            <span>הוצאות</span>
            <strong>{shekel(today.expense)}</strong>
          </div>
          <div className="row">
            <span>תזרים</span>
            <strong style={{ color: today.net >= 0 ? "var(--lg-good)" : "var(--lg-bad)" }}>
              {shekel(today.net)}
            </strong>
          </div>
        </Card>
      </div>

      <Card className="section-gap">
        <div className="card-title">הוצאות לפי קטגוריה</div>
        {expenseCats.map(([cat, amt]) => (
          <div key={cat} style={{ margin: "10px 0" }}>
            <div className="row" style={{ border: 0, paddingBottom: 4 }}>
              <span>{cat}</span>
              <strong>{shekel(amt)}</strong>
            </div>
            <div className="bar-track">
              <div className="bar-fill" style={{ width: `${(amt / maxCat) * 100}%` }} />
            </div>
          </div>
        ))}
      </Card>
    </div>
  );
}
