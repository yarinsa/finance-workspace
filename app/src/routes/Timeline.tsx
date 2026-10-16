import { Card, CardLabel, Page } from "@/components/common";
import { cashflow, shekel } from "@/lib/data";

/** Monthly cashflow waterfall. Renders projection focal points as life-horizon
 *  rows; full four-bucket monthly split (income→expense→loans→deposits) is a
 *  Phase-2 item per PRD 09. */
export default function Timeline() {
  const points = (cashflow.projection?.focal_points ?? []).filter((p) => p.net_val != null);

  return (
    <Page title="ציר זמן">
      <Card>
        <CardLabel>נקודות מוקד לאורך החיים</CardLabel>
        <div className="muted" style={{ fontSize: 13, marginBottom: 8 }}>
          השווי כאן כולל חיסכון ארוך טווח (פנסיה וקרנות השתלמות) ואת המשכנתא — לכן נקודת "היום"
          שונה מהמצב הנזיל במבט על. שווי הדירה אינו נכלל.
        </div>
        {points.length === 0 && <div className="muted">אין נתוני תחזית.</div>}
        {points.map((p, i) => (
          <div key={i} className="row">
            <span>
              {p.age != null ? `גיל ${p.age}` : p.date}
              {p.name && <span className="muted"> · {p.name}</span>}
            </span>
            <strong>{shekel(p.net_val as number)}</strong>
          </div>
        ))}
      </Card>
    </Page>
  );
}
