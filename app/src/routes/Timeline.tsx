import { Card, PageTitle } from "@/components/ui";
import { cashflow, shekel } from "@/lib/data";

/** Monthly cashflow waterfall. Renders projection focal points as life-horizon
 *  rows; full four-bucket monthly split (income→expense→loans→deposits) is a
 *  Phase-2 item per PRD 09. */
export default function Timeline() {
  const points = (cashflow.projection?.focal_points ?? []).filter((p) => p.net_val != null);

  return (
    <div>
      <PageTitle>ציר זמן</PageTitle>
      <Card>
        <div className="card-title">נקודות מוקד לאורך החיים</div>
        {points.length === 0 && <div className="muted">אין נתוני תחזית.</div>}
        {points.map((p, i) => (
          <div key={i} className="row">
            <span>{p.age != null ? `גיל ${p.age}` : p.name ?? p.date}</span>
            <strong>{shekel(p.net_val as number)}</strong>
          </div>
        ))}
      </Card>
    </div>
  );
}
