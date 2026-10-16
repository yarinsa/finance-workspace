import { useState } from "react";
import { Card, CardLabel, Page, Section } from "@/components/common";
import { HORIZON_LABEL, HORIZON_SHORT } from "@/components/TransactionEditSheet";
import { ApiOffline, patchGoal, type Horizon } from "@/lib/api";
import { useLedgerApi } from "@/lib/useLedgerApi";
import { goals, shekel, shekelCompact } from "@/lib/data";
import type { GeneralGoalCard, PersonalGoal } from "@/lib/data";

function generalValue(c: GeneralGoalCard): string {
  // No real retirement target → coverage is undefined, not 100%.
  if (c.key === "retirement_coverage" && c.status === "needs_input") return "הגדירו יעד פרישה";
  if (c.status === "needs_input" || c.value == null) return "חסר קלט";
  if (c.units === "%") return `${c.value}%`;
  // large ₪ figures (inheritance) read better compact
  return Math.abs(c.value) >= 1_000_000 ? shekelCompact(c.value) : shekel(c.value);
}

function GeneralCard({ c }: { c: GeneralGoalCard }) {
  const muted = c.status === "needs_input";
  return (
    <Card>
      <CardLabel>{c.name}</CardLabel>
      <div className="big-num" style={{ fontSize: 24, color: muted ? "var(--lg-muted)" : undefined }}>
        {generalValue(c)}
      </div>
      {c.key === "emergency_fund_coverage" && c.shortfall ? (
        <div className="muted" style={{ fontSize: 13 }}>חוסר {shekel(c.shortfall)}</div>
      ) : null}
      {c.key === "emergency_fund_coverage" && c.meets_target != null ? (
        <div className="muted" style={{ fontSize: 13 }}>
          {c.meets_target ? "✓ קרן החירום מלאה" : "קרן החירום מתחת ליעד"}
        </div>
      ) : null}
      {c.key === "retirement_coverage" && c.meets_target != null ? (
        <div className="muted" style={{ fontSize: 13 }}>
          {c.meets_target ? "✓ עומד ביעד הפרישה" : "מתחת ליעד הפרישה"}
        </div>
      ) : null}
      {c.key === "inheritance_amount" && c.meets_target != null ? (
        <div className="muted" style={{ fontSize: 13 }}>
          {c.meets_target ? "✓ עומד ביעד ההורשה" : "מתחת ליעד ההורשה"}
        </div>
      ) : null}
      {c.key === "retirement_coverage" && c.status === "needs_input" ? (
        <div className="muted" style={{ fontSize: 12 }}>ללא יעד פרישה אין מול מה למדוד את התחזית</div>
      ) : null}
      <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>{c.description}</div>
    </Card>
  );
}

/** The goal's horizon as three chips; tapping one reassigns the goal (needs the ledger API). */
function GoalHorizon({ g }: { g: PersonalGoal }) {
  const { online, markOffline } = useLedgerApi();
  const [horizon, setHorizon] = useState<Horizon | null>(g.horizon ?? null);
  const [busy, setBusy] = useState(false);
  const editable = online === true && g.goal_id != null && !busy;

  const pick = async (h: Horizon) => {
    if (g.goal_id == null) return;
    const next = h === horizon ? null : h;
    const prev = horizon;
    setHorizon(next);
    setBusy(true);
    try {
      setHorizon((await patchGoal(g.goal_id, { horizon: next })).horizon);
    } catch (e) {
      setHorizon(prev);
      if (e instanceof ApiOffline) markOffline();
    } finally {
      setBusy(false);
    }
  };

  if (!editable && !horizon) return null;
  return (
    <div className="mt-2 flex gap-1.5" role="radiogroup" aria-label="אופק">
      {(Object.keys(HORIZON_SHORT) as Horizon[]).map((h) =>
        editable || h === horizon ? (
          <button
            key={h}
            type="button"
            role="radio"
            aria-checked={horizon === h}
            title={HORIZON_LABEL[h]}
            disabled={!editable}
            onClick={() => void pick(h)}
            className={`rounded-full border px-2.5 py-0.5 text-xs ${
              horizon === h ? "border-brand bg-brand/15 font-semibold" : "border-line text-muted-foreground"
            }`}
          >
            {HORIZON_SHORT[h]}
          </button>
        ) : null,
      )}
    </div>
  );
}

function GoalCard({ g }: { g: PersonalGoal }) {
  const prog = Math.min(100, Math.max(0, g.progress_pct ?? 0));
  const trackColor =
    g.on_track === false ? "var(--lg-bad)" : g.on_track ? "var(--lg-accent)" : "var(--lg-muted)";
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
      <GoalHorizon g={g} />
    </Card>
  );
}

export default function Goals() {
  const { general, personal_goals, missing_piece } = goals;
  return (
    <Page title="יעדים" wide>
      <Section title="יעדים כללים">
        <div className="grid grid-4">
          {general.map((c) => (
            <GeneralCard key={c.key} c={c} />
          ))}
        </div>
        {missing_piece > 0 && (
          <div className="muted mt-[18px]">חתיכה חסרה (פער למימון כל היעדים): {shekel(missing_piece)}</div>
        )}
      </Section>

      <Section title="יעדים אישיים">
        {personal_goals.length === 0 ? (
          <Card>
            <span className="muted">
              אין יעדים אישיים עדיין. הוסיפו עם <code>POST /api/goals</code> או{" "}
              <code>db/goal_store.py import</code>, והריצו <code>data/goals.py</code>.
            </span>
          </Card>
        ) : (
          <div className="grid grid-2">
            {personal_goals.map((g) => (
              <GoalCard key={g.id ?? g.description} g={g} />
            ))}
          </div>
        )}
      </Section>
    </Page>
  );
}
