import { Card, CardLabel, Page, RankPill } from "@/components/common";
import { cashflow, formatMetric } from "@/lib/data";

export default function Metrics() {
  return (
    <Page title="התקדמות — מדדים" wide>
      <div className="grid grid-3">
        {cashflow.metrics.map((m) => (
          <Card key={m.key}>
            <CardLabel>{m.name}</CardLabel>
            <div className="big-num" style={{ fontSize: 26 }}>
              {formatMetric(m.value, m.units)}
            </div>
            <div style={{ margin: "8px 0" }}>
              <RankPill rank={m.rank} />
            </div>
            <div className="muted" style={{ fontSize: 13 }}>{m.description}</div>
          </Card>
        ))}
      </div>
    </Page>
  );
}
