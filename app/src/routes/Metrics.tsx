import { Card, PageTitle, RankPill } from "@/components/common";
import { cashflow, shekel } from "@/lib/data";

function fmtMetric(value: number, units: string): string {
  if (units === "₪") return shekel(value);
  if (units === "%") return `${value.toFixed(1)}%`;
  return value.toLocaleString("he-IL");
}

export default function Metrics() {
  return (
    <div>
      <PageTitle>התקדמות — מדדים</PageTitle>
      <div className="grid grid-3">
        {cashflow.metrics.map((m) => (
          <Card key={m.key}>
            <div className="card-title">{m.name}</div>
            <div className="big-num" style={{ fontSize: 26 }}>
              {fmtMetric(m.value, m.units)}
            </div>
            <div style={{ margin: "8px 0" }}>
              <RankPill rank={m.rank} />
            </div>
            <div className="muted" style={{ fontSize: 13 }}>{m.description}</div>
          </Card>
        ))}
      </div>
    </div>
  );
}
