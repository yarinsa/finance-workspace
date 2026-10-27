import { useEffect, useState } from "react";
import { fetchQuery, graphql, useMutation } from "react-relay";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { getDataVersion } from "@/lib/data";
import { overlayTargets, recordGoalsChange, type TargetKey } from "@/lib/goalsOverlay";
import { failureMessage } from "@/lib/mutationError";
import { environment } from "@/lib/relay";
import { useLedgerApi } from "@/lib/useLedgerApi";
import type { TargetsSheetQuery } from "@/__generated__/TargetsSheetQuery.graphql";
import type { PlanTargetsUpdateInput, TargetsSheetUpdateMutation } from "@/__generated__/TargetsSheetUpdateMutation.graphql";

const QUERY = graphql`
  query TargetsSheetQuery {
    planTargets { emergencyFund inheritance retirement }
  }
`;

const UPDATE = graphql`
  mutation TargetsSheetUpdateMutation($input: PlanTargetsUpdateInput!) {
    planTargetsUpdate(input: $input) {
      success
      planTargets { emergencyFund inheritance retirement }
    }
  }
`;

type Fields = Record<TargetKey, string>;

const FIELDS: { key: TargetKey; label: string; hint: string }[] = [
  { key: "emergencyFund", label: "קרן חירום (₪)", hint: "ריק = ללא יעד" },
  { key: "retirement", label: "יעד פרישה (₪)", hint: "ריק ⇒ ללא יעד פרישה" },
  { key: "inheritance", label: "יעד הורשה (₪)", hint: "ריק = ללא יעד" },
];

/** "" for unset (null or 0), else the number as typed text. */
const asText = (money: string | null | undefined): string => (money == null || Number(money) === 0 ? "" : String(Number(money)));

/** Parse one field: null = unset (empty), NaN = invalid (not a number or negative). */
function parse(text: string): number | null {
  if (!text.trim()) return null;
  const n = Number(text);
  return Number.isFinite(n) && n >= 0 ? (n === 0 ? null : n) : Number.NaN;
}

type Loaded = { state: "loading" } | { state: "error"; message: string } | { state: "ready"; initial: Fields };

/**
 * Bottom sheet for the three general plan targets (emergency fund, retirement, inheritance).
 * Prefills from the `planTargets` query, sends only the targets that changed (`null` unsets),
 * and records the new targets in the goals overlay so the cards update before the rebuild.
 */
export default function TargetsSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="bottom" className="max-h-[90dvh] overflow-y-auto" dir="rtl">
        {open && <Loader onClose={onClose} />}
      </SheetContent>
    </Sheet>
  );
}

function Loader({ onClose }: { onClose: () => void }) {
  const { markOffline } = useLedgerApi();
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });

  useEffect(() => {
    const sub = fetchQuery<TargetsSheetQuery>(environment, QUERY, {}, { fetchPolicy: "network-only" }).subscribe({
      next: ({ planTargets: t }) =>
        setLoaded({
          state: "ready",
          initial: { emergencyFund: asText(t.emergencyFund), inheritance: asText(t.inheritance), retirement: asText(t.retirement) },
        }),
      error: (e: Error) => setLoaded({ state: "error", message: failureMessage(e, markOffline, "הטעינה נכשלה") }),
    });
    return () => sub.unsubscribe();
  }, [markOffline]);

  if (loaded.state === "ready") return <Form initial={loaded.initial} onClose={onClose} />;
  return (
    <>
      <SheetHeader>
        <SheetTitle className="text-lg font-bold">יעדים כלליים</SheetTitle>
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

function Form({ initial, onClose }: { initial: Fields; onClose: () => void }) {
  const { online, markOffline, markDirty } = useLedgerApi();
  const [commit] = useMutation<TargetsSheetUpdateMutation>(UPDATE);
  const [values, setValues] = useState<Fields>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const readOnly = online !== true;
  const changed = FIELDS.filter(({ key }) => parse(values[key]) !== parse(initial[key]));
  const invalid = FIELDS.some(({ key }) => Number.isNaN(parse(values[key])));

  const save = () => {
    if (invalid || changed.length === 0) return;
    setBusy(true);
    setError(null);
    const sent: Partial<Record<TargetKey, number | null>> = {};
    for (const { key } of changed) sent[key] = parse(values[key]);
    const money = (v: number | null | undefined) => (v == null ? null : v.toFixed(2));
    const input: PlanTargetsUpdateInput = {};
    if ("emergencyFund" in sent) input.emergencyFund = money(sent.emergencyFund);
    if ("inheritance" in sent) input.inheritance = money(sent.inheritance);
    if ("retirement" in sent) input.retirement = money(sent.retirement);
    commit({
      variables: { input },
      onCompleted: (r) => {
        setBusy(false);
        if (r.planTargetsUpdate.success) recordGoalsChange((o) => overlayTargets(o, sent, getDataVersion()));
        markDirty();
        onClose();
      },
      onError: (e) => {
        setBusy(false);
        setError(failureMessage(e, markOffline, "השמירה נכשלה"));
      },
    });
  };

  return (
    <>
      <SheetHeader>
        <SheetTitle className="text-lg font-bold">יעדים כלליים</SheetTitle>
        <SheetDescription>קרן חירום, פרישה והורשה</SheetDescription>
      </SheetHeader>

      <div className="space-y-4 px-4">
        {error && (
          <div role="alert" className="rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        )}
        {readOnly && !error && <div className="text-xs text-muted-foreground">אין חיבור למחשב הביתי, אי אפשר לשמור עכשיו.</div>}

        {FIELDS.map(({ key, label, hint }) => {
          const bad = Number.isNaN(parse(values[key]));
          return (
            <div key={key}>
              <label className="mb-1 block text-sm font-semibold">{label}</label>
              <Input
                type="number"
                inputMode="decimal"
                placeholder="0"
                value={values[key]}
                onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
                disabled={readOnly || busy}
                aria-invalid={bad}
                step="0.01"
                min="0"
              />
              {bad ? <div className="mt-1 text-xs text-destructive">הסכום לא יכול להיות שלילי</div> : <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
            </div>
          );
        })}

        <div className="flex gap-2 pt-2">
          <Button type="button" className="flex-1" onClick={save} disabled={readOnly || busy || invalid || changed.length === 0}>
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
