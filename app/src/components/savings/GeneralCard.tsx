import { Card, CardLabel } from "@/components/common";
import { shekel, shekelCompact } from "@/lib/data";
import type { DisplayGeneral } from "@/lib/goalsOverlay";

const PENDING = "מתעדכן…";

function generalValue(c: DisplayGeneral): string {
  if (c.pending) return PENDING;
  // No real retirement target → coverage is undefined, not 100%.
  if (c.key === "retirement_coverage" && c.status === "needs_input") return "הגדירו יעד פרישה";
  if (c.status === "needs_input" || c.value == null) return "חסר קלט";
  if (c.units === "%") return `${c.value}%`;
  // large ₪ figures (inheritance) read better compact
  return Math.abs(c.value) >= 1_000_000 ? shekelCompact(c.value) : shekel(c.value);
}

/** One general target (emergency fund, retirement coverage…) as a card; on the חיסכון screen. */
export function GeneralCard({ c }: { c: DisplayGeneral }) {
  const muted = c.status === "needs_input" || c.pending;
  return (
    <Card>
      <CardLabel>{c.name}</CardLabel>
      <div className="big-num" style={{ fontSize: 24, color: muted ? "var(--lg-muted)" : undefined }}>
        {generalValue(c)}
      </div>
      {c.pending || (c.target != null && !c.target_derived) ? (
        <div className="muted" style={{ fontSize: 13 }}>{c.target != null ? `יעד ${shekel(c.target)}` : "ללא יעד"}</div>
      ) : null}
      {!c.pending && c.key === "emergency_fund_coverage" && c.shortfall ? (
        <div className="muted" style={{ fontSize: 13 }}>חוסר {shekel(c.shortfall)}</div>
      ) : null}
      {!c.pending && c.key === "emergency_fund_coverage" && c.meets_target != null ? (
        <div className="muted" style={{ fontSize: 13 }}>
          {c.meets_target ? "✓ קרן החירום מלאה" : "קרן החירום מתחת ליעד"}
        </div>
      ) : null}
      {!c.pending && c.key === "retirement_coverage" && c.meets_target != null ? (
        <div className="muted" style={{ fontSize: 13 }}>
          {c.meets_target ? "✓ עומד ביעד הפרישה" : "מתחת ליעד הפרישה"}
        </div>
      ) : null}
      {!c.pending && c.key === "inheritance_amount" && c.meets_target != null ? (
        <div className="muted" style={{ fontSize: 13 }}>
          {c.meets_target ? "✓ עומד ביעד ההורשה" : "מתחת ליעד ההורשה"}
        </div>
      ) : null}
      {!c.pending && c.key === "retirement_coverage" && c.status === "needs_input" ? (
        <div className="muted" style={{ fontSize: 12 }}>ללא יעד פרישה אין מול מה למדוד את התחזית</div>
      ) : null}
      <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>{c.description}</div>
    </Card>
  );
}
