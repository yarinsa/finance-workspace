import { Card, PageTitle } from "@/components/ui";
import { goals, shekel, shekelCompact } from "@/lib/data";
import type { GeneralGoalCard, PersonalGoal } from "@/lib/data";

function generalValue(c: GeneralGoalCard): string {
  if (c.status === "needs_input" || c.value == null) return "חסר קלט";
  if (c.units === "%") return `${c.value}%`;
  // large ₪ figures (inheritance) read better compact
  return Math.abs(c.value) >= 1_000_000 ? shekelCompact(c.value) : shekel(c.value);
}

function GeneralCard({ c }: { c: GeneralGoalCard }) {
  const muted = c.status === "needs_input";
  return (
    <Card>
      <div className="card-title">{c.name}</div>
      <div className="big-num" style={{ fontSize: 24, color: muted ? "var(--muted)" : undefined }}>
        {generalValue(c)}
      </div>
      {c.key === "emergency_fund_coverage" && c.shortfall ? (
        <div className="muted" style={{ fontSize: 13 }}>חוסר {shekel(c.shortfall)}</div>
      ) : null}
      {c.key === "inheritance_amount" && c.meets_target != null ? (
        <div className="muted" style={{ fontSize: 13 }}>
          {c.meets_target ? "✓ עומד ביעד ההורשה" : "מתחת ליעד ההורשה"}
        </div>
      ) : null}
      {c.target_derived ? (
        <div className="muted" style={{ fontSize: 12 }}>יעד נגזר מהתחזית — הזן יעד פרישה לדיוק</div>
      ) : null}
      <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>{c.description}</div>
    </Card>
  );
}

function GoalCard({ g }: { g: PersonalGoal }) {
  const prog = g.progress_pct ?? 0;
  const trackColor =
    g.on_track === false ? "var(--bad)" : g.on_track ? "var(--accent)" : "var(--muted)";
  return (
    <Card>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <strong>{g.description}</strong>
        <span className="muted" style={{ fontSize: 13 }}>
          {g.on_track === false ? "לא בכיוון" : g.on_track ? "בכיוון" : "—"}
        </span>
      </div>
      <div className="bar-track" style={{ margin: "10px 0" }}>
        <div className="bar-fill" style={{ width: `${prog}%`, background: trackColor }} />
      </div>
      <div className="row" style={{ border: 0, padding: 0 }}>
        <span className="muted">יעד {shekel(g.amount)}</span>
        <span className="muted">
          {g.progress_pct != null ? `${g.progress_pct}%` : "—"}
          {g.days_left != null ? ` · ${g.days_left} ימים` : ""}
        </span>
      </div>
    </Card>
  );
}

export default function Goals() {
  const { general, personal_goals, missing_piece } = goals;
  return (
    <div>
      <PageTitle>יעדים</PageTitle>

      <h2 style={{ fontSize: 18, margin: "0 0 12px" }}>יעדים כללים</h2>
      <div className="grid grid-4">
        {general.map((c) => (
          <GeneralCard key={c.key} c={c} />
        ))}
      </div>
      {missing_piece > 0 && (
        <div className="muted section-gap">חתיכה חסרה (פער למימון כל היעדים): {shekel(missing_piece)}</div>
      )}

      <h2 style={{ fontSize: 18, margin: "26px 0 12px" }}>יעדים אישיים</h2>
      {personal_goals.length === 0 ? (
        <Card>
          <span className="muted">
            אין יעדים אישיים עדיין. הוסף ל-<code>data/goals/goals.json</code> והרץ{" "}
            <code>python3 data/goals.py</code>.
          </span>
        </Card>
      ) : (
        <div className="grid grid-2">
          {personal_goals.map((g) => (
            <GoalCard key={g.id ?? g.description} g={g} />
          ))}
        </div>
      )}
    </div>
  );
}
