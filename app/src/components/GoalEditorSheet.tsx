import { useEffect, useState } from "react";
import { fetchQuery, graphql, useMutation } from "react-relay";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { HORIZON_LABEL, HORIZON_SHORT } from "@/components/TransactionEditSheet";
import type { Horizon } from "@/lib/api";
import { getDataVersion } from "@/lib/data";
import { buildCreateInput, buildUpdateInput, EMPTY_GOAL_FORM, validateGoalForm, type GoalFormValues } from "@/lib/goalValidation";
import { overlayCreate, overlayDelete, overlayUpdate, recordGoalsChange, type GoalPatch } from "@/lib/goalsOverlay";
import { failureMessage } from "@/lib/mutationError";
import { fromGlobalId, toGlobalId } from "@/lib/notifications";
import { environment } from "@/lib/relay";
import { lower } from "@/lib/txnRow";
import { useLedgerApi } from "@/lib/useLedgerApi";
import type { GoalEditorSheetCreateMutation } from "@/__generated__/GoalEditorSheetCreateMutation.graphql";
import type { GoalEditorSheetDeleteMutation } from "@/__generated__/GoalEditorSheetDeleteMutation.graphql";
import type { GoalEditorSheetQuery } from "@/__generated__/GoalEditorSheetQuery.graphql";
import type { GoalEditorSheetUpdateMutation } from "@/__generated__/GoalEditorSheetUpdateMutation.graphql";


const QUERY = graphql`
  query GoalEditorSheetQuery($id: ID!) {
    node(id: $id) {
      ... on Goal { id description amount startDate endDate interval repetitions rise horizon { key } }
    }
  }
`;

const CREATE = graphql`
  mutation GoalEditorSheetCreateMutation($input: GoalCreateInput!) {
    goalCreate(input: $input) {
      success
      goal { id description amount startDate endDate interval repetitions rise horizon { key } }
    }
  }
`;

const UPDATE = graphql`
  mutation GoalEditorSheetUpdateMutation($id: ID!, $input: GoalUpdateInput!) {
    goalUpdate(id: $id, input: $input) {
      success
      goal { id description amount startDate endDate interval repetitions rise horizon { key } }
    }
  }
`;

const DELETE = graphql`
  mutation GoalEditorSheetDeleteMutation($id: ID!) {
    goalDelete(id: $id) { success entityId }
  }
`;

/** Which goal the sheet edits: a table id, or `{}` for a new goal. */
export interface GoalEditorTarget {
  goal_id?: number | null;
}

const toGoalId = (n: number) => toGlobalId(n, "Goal");
const asNumber = (money: string) => String(Number(money));

/**
 * Bottom sheet for creating or editing one goal. Fields: description (required), amount ₪
 * (required, > 0), end date, horizon (three chips), and a collapsible "מתקדם" section with
 * start date, interval, repetitions, rise. Edit mode loads the goal through GraphQL (the
 * digest lacks the advanced fields) and has a delete button with an inline confirm. Every
 * accepted change is also recorded in the goals overlay so the screen shows it before the
 * rebuild publishes.
 */
export default function GoalEditorSheet({ goal, onClose }: { goal: GoalEditorTarget | null; onClose: () => void }) {
  return (
    <Sheet open={goal != null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="bottom" className="max-h-[90dvh] overflow-y-auto" dir="rtl">
        {goal && <Loader key={goal.goal_id ?? "new"} goalId={goal.goal_id ?? null} onClose={onClose} />}
      </SheetContent>
    </Sheet>
  );
}

type Loaded = { state: "loading" } | { state: "error"; message: string } | { state: "ready"; initial: GoalFormValues };

/** Fetches the goal being edited (network only: the form must start from what the server has). */
function Loader({ goalId, onClose }: { goalId: number | null; onClose: () => void }) {
  const { markOffline } = useLedgerApi();
  const [loaded, setLoaded] = useState<Loaded>(goalId == null ? { state: "ready", initial: EMPTY_GOAL_FORM } : { state: "loading" });

  useEffect(() => {
    if (goalId == null) return;
    const sub = fetchQuery<GoalEditorSheetQuery>(environment, QUERY, { id: toGoalId(goalId) }, { fetchPolicy: "network-only" }).subscribe({
      next: ({ node }) => {
        if (!node || node.id == null) return setLoaded({ state: "error", message: "היעד לא נמצא" });
        setLoaded({
          state: "ready",
          initial: {
            description: node.description ?? "",
            amount: asNumber(node.amount ?? "0"),
            startDate: node.startDate ?? "",
            endDate: node.endDate ?? "",
            interval: node.interval ?? "",
            repetitions: String(node.repetitions ?? 1),
            rise: asNumber(node.rise ?? "0"),
            horizon: lower(node.horizon?.key),
          },
        });
      },
      error: (e: Error) => setLoaded({ state: "error", message: failureMessage(e, markOffline, "הטעינה נכשלה") }),
    });
    return () => sub.unsubscribe();
  }, [goalId, markOffline]);

  if (loaded.state === "ready") return <Form goalId={goalId} initial={loaded.initial} onClose={onClose} />;
  return (
    <>
      <SheetHeader>
        <SheetTitle className="text-lg font-bold">עריכת יעד</SheetTitle>
        <SheetDescription>{loaded.state === "loading" ? "טוען…" : loaded.message}</SheetDescription>
      </SheetHeader>
      <div className="px-4 pb-6">
        <button type="button" className="w-full rounded-lg border border-line py-2 text-sm font-semibold" onClick={onClose}>
          סגירה
        </button>
      </div>
    </>
  );
}

function Form({ goalId, initial, onClose }: { goalId: number | null; initial: GoalFormValues; onClose: () => void }) {
  const isEdit = goalId != null;
  const { online, markOffline, markDirty } = useLedgerApi();
  const [commitCreate] = useMutation<GoalEditorSheetCreateMutation>(CREATE);
  const [commitUpdate] = useMutation<GoalEditorSheetUpdateMutation>(UPDATE);
  const [commitDelete] = useMutation<GoalEditorSheetDeleteMutation>(DELETE);

  const [f, setF] = useState<GoalFormValues>(initial);
  const set = <K extends keyof GoalFormValues>(k: K, v: GoalFormValues[K]) => setF((cur) => ({ ...cur, [k]: v }));
  const [advanced, setAdvanced] = useState(
    isEdit && (initial.startDate !== "" || initial.interval !== "" || Number(initial.rise) > 0),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleteConfirming, setDeleteConfirming] = useState(false);

  const readOnly = online !== true;
  const errors = validateGoalForm(f);
  const input = isEdit ? buildUpdateInput(f, initial) : null;
  const unchanged = input != null && Object.keys(input).length === 0;
  const disabled = readOnly || busy || Object.keys(errors).length > 0 || unchanged;

  const fail = (e: Error, fallback: string) => {
    setBusy(false);
    setError(failureMessage(e, markOffline, fallback));
  };
  const done = () => {
    setBusy(false);
    markDirty();
    onClose();
  };

  const save = () => {
    if (Object.keys(errors).length > 0) return;
    setBusy(true);
    setError(null);

    if (isEdit && input) {
      commitUpdate({
        variables: { id: toGoalId(goalId), input },
        onCompleted: (r) => {
          const patch: GoalPatch = {};
          if (input.description != null) patch.description = input.description;
          if (input.amount != null) patch.amount = Number(input.amount);
          if (input.endDate !== undefined) patch.end_date = input.endDate;
          if (input.horizon !== undefined) patch.horizon = lower(input.horizon);
          if (r.goalUpdate.success) recordGoalsChange((o) => overlayUpdate(o, goalId, patch, getDataVersion()));
          done();
        },
        onError: (e) => fail(e, "השמירה נכשלה"),
      });
    } else {
      commitCreate({
        variables: { input: buildCreateInput(f) },
        onCompleted: (r) => {
          const g = r.goalCreate.goal;
          const id = g ? fromGlobalId(g.id, "Goal") : null;
          if (g && id != null) {
            recordGoalsChange((o) =>
              overlayCreate(
                o,
                {
                  goal_id: Number(id),
                  description: g.description,
                  amount: Number(g.amount),
                  end_date: g.endDate ?? null,
                  horizon: lower(g.horizon?.key),
                  progress_pct: null,
                  on_track: null,
                },
                getDataVersion(),
              ),
            );
          }
          done();
        },
        onError: (e) => fail(e, "השמירה נכשלה"),
      });
    }
  };

  const del = () => {
    if (!isEdit) return;
    setBusy(true);
    setError(null);
    commitDelete({
      variables: { id: toGoalId(goalId) },
      onCompleted: (r) => {
        if (r.goalDelete.success) recordGoalsChange((o) => overlayDelete(o, goalId, getDataVersion()));
        done();
      },
      onError: (e) => fail(e, "המחיקה נכשלה"),
    });
  };

  const field = readOnly || busy;
  return (
    <>
      <SheetHeader>
        <SheetTitle className="text-lg font-bold">{isEdit ? "עריכת יעד" : "יעד חדש"}</SheetTitle>
        {isEdit && <SheetDescription>{initial.description}</SheetDescription>}
      </SheetHeader>

      <div className="space-y-4 px-4">
        {error && (
          <div role="alert" className="rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        )}
        {readOnly && !error && <div className="text-xs text-muted-foreground">אין חיבור למחשב הביתי, אי אפשר לשמור עכשיו.</div>}

        <div>
          <label className="mb-1 block text-sm font-semibold">תיאור יעד</label>
          <Input type="text" value={f.description} onChange={(e) => set("description", e.target.value)} disabled={field} aria-invalid={!!errors.description} />
          {errors.description && <div className="mt-1 text-xs text-destructive">{errors.description}</div>}
        </div>

        <div>
          <label className="mb-1 block text-sm font-semibold">סכום (₪)</label>
          <Input type="number" inputMode="decimal" placeholder="0" value={f.amount} onChange={(e) => set("amount", e.target.value)} disabled={field} aria-invalid={!!errors.amount} step="0.01" min="0" />
          {errors.amount && <div className="mt-1 text-xs text-destructive">{errors.amount}</div>}
        </div>

        <div>
          <label className="mb-1 block text-sm font-semibold">תאריך היעד</label>
          <Input type="date" value={f.endDate} onChange={(e) => set("endDate", e.target.value)} disabled={field} aria-invalid={!!errors.endDate} />
          {errors.endDate && <div className="mt-1 text-xs text-destructive">{errors.endDate}</div>}
        </div>

        <div>
          <label className="mb-2 block text-sm font-semibold">אופק</label>
          <div role="radiogroup" aria-label="אופק" className="flex gap-2">
            {(Object.keys(HORIZON_SHORT) as Horizon[]).map((h) => (
              <button
                key={h}
                type="button"
                role="radio"
                aria-checked={f.horizon === h}
                title={HORIZON_LABEL[h]}
                disabled={field}
                onClick={() => set("horizon", f.horizon === h ? null : h)}
                className={`rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors ${
                  f.horizon === h ? "border-brand bg-brand/15 text-brand" : "border-line text-muted-foreground"
                }`}
              >
                {HORIZON_SHORT[h]}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-3 border-t border-line pt-3">
          <button
            type="button"
            className="flex w-full items-center gap-2 text-start text-sm font-semibold"
            aria-expanded={advanced}
            onClick={() => setAdvanced(!advanced)}
          >
            <span className={`text-xs transition-transform ${advanced ? "rotate-90" : ""}`}>›</span>
            מתקדם
          </button>

          {advanced && (
            <div className="mt-3 space-y-3">
              <div>
                <label className="mb-1 block text-xs font-semibold text-muted-foreground">תאריך התחלה</label>
                <Input type="date" value={f.startDate} onChange={(e) => set("startDate", e.target.value)} disabled={field} aria-invalid={!!errors.startDate} />
                {errors.startDate && <div className="mt-1 text-xs text-destructive">{errors.startDate}</div>}
              </div>

              <div>
                <label className="mb-1 block text-xs font-semibold text-muted-foreground">חזרה</label>
                <select
                  value={f.interval}
                  onChange={(e) => set("interval", e.target.value === "MONTHLY" ? "MONTHLY" : e.target.value === "YEARLY" ? "YEARLY" : "")}
                  disabled={field}
                  className="h-9 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
                >
                  <option value="">ללא</option>
                  <option value="MONTHLY">חודשי</option>
                  <option value="YEARLY">שנתי</option>
                </select>
              </div>

              {f.interval && (
                <div>
                  <label className="mb-1 block text-xs font-semibold text-muted-foreground">חזרות</label>
                  <Input type="number" inputMode="numeric" value={f.repetitions} onChange={(e) => set("repetitions", e.target.value)} disabled={field} aria-invalid={!!errors.repetitions} min="1" step="1" />
                  {errors.repetitions && <div className="mt-1 text-xs text-destructive">{errors.repetitions}</div>}
                </div>
              )}

              <div>
                <label className="mb-1 block text-xs font-semibold text-muted-foreground">עלייה שנתית (₪)</label>
                <Input type="number" inputMode="decimal" value={f.rise} onChange={(e) => set("rise", e.target.value)} disabled={field} aria-invalid={!!errors.rise} step="0.01" min="0" />
                {errors.rise && <div className="mt-1 text-xs text-destructive">{errors.rise}</div>}
              </div>
            </div>
          )}
        </div>

        {isEdit && (
          <div className="mt-3 border-t border-line pt-3">
            {deleteConfirming ? (
              <div className="flex gap-2">
                <button type="button" className="flex-1 rounded-lg border border-destructive/50 bg-destructive/10 py-2 text-sm font-semibold text-destructive" onClick={del} disabled={readOnly || busy}>
                  {busy ? "מוחק..." : "אישור מחיקה"}
                </button>
                <button type="button" className="flex-1 rounded-lg border border-line py-2 text-sm font-semibold" onClick={() => setDeleteConfirming(false)} disabled={busy}>
                  ביטול
                </button>
              </div>
            ) : (
              <button type="button" className="w-full rounded-lg border border-destructive/50 py-2 text-sm font-semibold text-destructive" onClick={() => setDeleteConfirming(true)} disabled={field}>
                מחיקת יעד
              </button>
            )}
          </div>
        )}

        <div className="flex gap-2 pt-2">
          <Button type="button" className="flex-1" onClick={save} disabled={disabled}>
            {busy ? "שומר..." : "שמור"}
          </Button>
          <button type="button" className="flex-1 rounded-lg border border-line py-2 text-sm font-semibold" onClick={onClose} disabled={busy}>
            ביטול
          </button>
        </div>
      </div>
      <div className="h-4" />
    </>
  );
}
