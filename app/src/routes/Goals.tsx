import { useState } from "react";
import { graphql, useMutation } from "react-relay";
import { Card, CardLabel, Section } from "@/components/common";
import { HORIZON_LABEL, HORIZON_SHORT } from "@/components/TransactionEditSheet";
import GoalEditorSheet, { type GoalEditorTarget } from "@/components/GoalEditorSheet";
import TargetsSheet from "@/components/TargetsSheet";
import type { Horizon } from "@/lib/api";
import { goals, shekel, shekelCompact, useDataVersion, getDataVersion } from "@/lib/data";
import { applyGoalsOverlay, overlayUpdate, recordGoalsChange, useGoalsOverlay, type DisplayGeneral, type DisplayGoal } from "@/lib/goalsOverlay";
import { failureMessage } from "@/lib/mutationError";
import { toGlobalId } from "@/lib/notifications";
import { useLedgerApi } from "@/lib/useLedgerApi";
import type { RoutesGoalsHorizonMutation } from "@/__generated__/RoutesGoalsHorizonMutation.graphql";

const PENDING = "מתעדכן…";

const SET_HORIZON = graphql`
  mutation RoutesGoalsHorizonMutation($id: ID!, $input: GoalUpdateInput!) {
    goalUpdate(id: $id, input: $input) {
      success
      goal { id horizon { key } }
    }
  }
`;

function generalValue(c: DisplayGeneral): string {
  if (c.pending) return PENDING;
  // No real retirement target → coverage is undefined, not 100%.
  if (c.key === "retirement_coverage" && c.status === "needs_input") return "הגדירו יעד פרישה";
  if (c.status === "needs_input" || c.value == null) return "חסר קלט";
  if (c.units === "%") return `${c.value}%`;
  // large ₪ figures (inheritance) read better compact
  return Math.abs(c.value) >= 1_000_000 ? shekelCompact(c.value) : shekel(c.value);
}

function GeneralCard({ c }: { c: DisplayGeneral }) {
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

/** The goal's horizon as three chips; tapping one reassigns the goal (needs the ledger API). */
function GoalHorizon({ g }: { g: DisplayGoal }) {
  const { online, markOffline, markDirty } = useLedgerApi();
  const [commit] = useMutation<RoutesGoalsHorizonMutation>(SET_HORIZON);
  // Shown while the request is in flight, so the chip responds to the tap.
  const [optimistic, setOptimistic] = useState<{ value: Horizon | null } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const horizon = optimistic ? optimistic.value : (g.horizon ?? null);
  const goalId = g.goal_id;
  const editable = online === true && goalId != null && optimistic == null;

  const pick = (h: Horizon) => {
    if (goalId == null) return;
    const next = h === horizon ? null : h;
    setOptimistic({ value: next });
    setFailed(null);
    commit({
      variables: { id: toGlobalId(goalId, "Goal"), input: { horizon: next ? (next.toUpperCase() as "CURRENT" | "NEAR" | "FUTURE") : null } },
      onCompleted: (r) => {
        if (r.goalUpdate.success) {
          recordGoalsChange((o) => overlayUpdate(o, goalId, { horizon: next }, getDataVersion()));
          markDirty();
        }
        setOptimistic(null);
      },
      onError: (e) => {
        setOptimistic(null);
        setFailed(failureMessage(e, markOffline, "השמירה נכשלה"));
      },
    });
  };

  if (!editable && !horizon && !optimistic) return null;
  return (
    <div className="mt-2">
      <div className="flex gap-1.5" role="radiogroup" aria-label="אופק">
        {(Object.keys(HORIZON_SHORT) as Horizon[]).map((h) =>
          editable || optimistic || h === horizon ? (
            <button
              key={h}
              type="button"
              role="radio"
              aria-checked={horizon === h}
              title={HORIZON_LABEL[h]}
              disabled={!editable}
              onClick={() => pick(h)}
              className={`rounded-full border px-2.5 py-0.5 text-xs ${
                horizon === h ? "border-brand bg-brand/15 font-semibold" : "border-line text-muted-foreground"
              }`}
            >
              {HORIZON_SHORT[h]}
            </button>
          ) : null,
        )}
      </div>
      {failed && <div role="alert" className="mt-1 text-xs text-destructive">{failed}</div>}
    </div>
  );
}

function GoalCard({ g, onEdit, canEdit }: { g: DisplayGoal; onEdit: (goalId: number) => void; canEdit: boolean }) {
  const prog = Math.min(100, Math.max(0, g.progress_pct ?? 0));
  const trackColor =
    g.on_track === false ? "var(--lg-bad)" : g.on_track ? "var(--lg-accent)" : "var(--lg-muted)";
  const goalId = g.goal_id;

  return (
    <Card>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
        <strong>{g.description}</strong>
        <span className="muted" style={{ display: "flex", alignItems: "baseline", gap: 8, fontSize: 13 }}>
          {g.pending ? PENDING : g.on_track === false ? "לא בכיוון" : g.on_track ? "בכיוון" : "—"}
          {canEdit && goalId != null ? (
            <button
              type="button"
              aria-label="עריכת יעד"
              title="עריכת יעד"
              className="text-base leading-none text-brand"
              onClick={() => onEdit(goalId)}
            >
              ✎
            </button>
          ) : null}
        </span>
      </div>
      <div className="bar-track" style={{ margin: "10px 0" }}>
        <div className="bar-fill" style={{ width: `${g.pending ? 0 : prog}%`, background: trackColor }} />
      </div>
      <div className="row" style={{ border: 0, padding: 0 }}>
        <span className="muted">יעד {shekel(g.amount)}</span>
        <span className="muted">
          {g.pending
            ? PENDING
            : `${g.progress_pct != null ? `${g.progress_pct}%` : "—"}${g.days_left != null ? ` · ${g.days_left} ימים` : ""}`}
        </span>
      </div>
      <GoalHorizon g={g} />
    </Card>
  );
}

/** The goals sections of the plan hub: general targets and personal goals (no page chrome). */
export default function Goals() {
  const version = useDataVersion();
  const overlay = useGoalsOverlay();
  const { general, personal_goals } = applyGoalsOverlay(goals, overlay, version);
  const { missing_piece } = goals;
  const { online } = useLedgerApi();
  const [targetSheet, setTargetSheet] = useState(false);
  const [goalEditorTarget, setGoalEditorTarget] = useState<GoalEditorTarget | null>(null);

  return (
    <>
      <Section
        title="יעדים כללים"
        action={
          online === true ? (
            <button type="button" className="text-sm font-semibold text-brand hover:underline" onClick={() => setTargetSheet(true)}>
              ✎ עריכה
            </button>
          ) : undefined
        }
      >
        <div className="grid grid-4">
          {general.map((c) => (
            <GeneralCard key={c.key} c={c} />
          ))}
        </div>
        {missing_piece > 0 && (
          <div className="muted mt-[18px]">חתיכה חסרה (פער למימון כל היעדים): {shekel(missing_piece)}</div>
        )}
      </Section>

      <Section
        title="יעדים אישיים"
        action={
          online === true ? (
            <button type="button" className="text-sm font-semibold text-brand hover:underline" onClick={() => setGoalEditorTarget({})}>
              + הוספת יעד
            </button>
          ) : undefined
        }
      >
        {personal_goals.length === 0 ? (
          <Card>
            <span className="muted">אין יעדים אישיים עדיין</span>
            {online === true && (
              <div className="mt-2">
                <button type="button" className="text-sm font-semibold text-brand hover:underline" onClick={() => setGoalEditorTarget({})}>
                  + הוספת יעד
                </button>
              </div>
            )}
          </Card>
        ) : (
          <div className="grid grid-2">
            {personal_goals.map((g) => (
              <GoalCard
                key={g.goal_id ?? g.id ?? g.description}
                g={g}
                canEdit={online === true}
                onEdit={(goal_id) => setGoalEditorTarget({ goal_id })}
              />
            ))}
          </div>
        )}
      </Section>

      <TargetsSheet open={targetSheet} onClose={() => setTargetSheet(false)} />
      <GoalEditorSheet goal={goalEditorTarget} onClose={() => setGoalEditorTarget(null)} />
    </>
  );
}
