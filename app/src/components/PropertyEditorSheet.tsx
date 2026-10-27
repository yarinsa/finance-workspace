import { useEffect, useState } from "react";
import { fetchQuery, graphql, useMutation } from "react-relay";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { failureMessage } from "@/lib/mutationError";
import { environment } from "@/lib/relay";
import { useLedgerApi } from "@/lib/useLedgerApi";
import type { PropertyEditorSheetQuery } from "@/__generated__/PropertyEditorSheetQuery.graphql";
import type { PropertyEditorSheetCreateMutation } from "@/__generated__/PropertyEditorSheetCreateMutation.graphql";
import type { PropertyEditorSheetUpdateMutation } from "@/__generated__/PropertyEditorSheetUpdateMutation.graphql";

const QUERY = graphql`
  query PropertyEditorSheetQuery {
    assets(first: 10) { edges { node { id kind label value valuedAt valuationSource } } }
  }
`;

const CREATE = graphql`
  mutation PropertyEditorSheetCreateMutation($input: AssetCreateInput!) {
    assetCreate(input: $input) { success asset { id value valuedAt } }
  }
`;

const UPDATE = graphql`
  mutation PropertyEditorSheetUpdateMutation($id: ID!, $input: AssetUpdateInput!) {
    assetUpdate(id: $id, input: $input) { success asset { id value valuedAt } }
  }
`;

interface Existing {
  id: string;
  label: string;
  value: string;
  valuedAt: string;
}

type Loaded = { state: "loading" } | { state: "error"; message: string } | { state: "ready"; property: Existing | null };

/**
 * The apartment's value, typed in by hand (an automatic estimate comes later). Creates the
 * property asset the first time, then revalues it; a new value is dated today. Net worth picks
 * it up after the rebuild that the edit triggers.
 */
export default function PropertyEditorSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
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
    const sub = fetchQuery<PropertyEditorSheetQuery>(environment, QUERY, {}, { fetchPolicy: "network-only" }).subscribe({
      next: ({ assets }) => {
        const p = assets.edges.map((e) => e.node).find((a) => a.kind === "PROPERTY");
        setLoaded({ state: "ready", property: p ? { id: p.id, label: p.label, value: p.value, valuedAt: p.valuedAt } : null });
      },
      error: (e: Error) => setLoaded({ state: "error", message: failureMessage(e, markOffline, "הטעינה נכשלה") }),
    });
    return () => sub.unsubscribe();
  }, [markOffline]);

  if (loaded.state === "ready") return <Form property={loaded.property} onClose={onClose} />;
  return (
    <>
      <SheetHeader>
        <SheetTitle className="font-display text-xl font-medium">שווי הדירה</SheetTitle>
        <SheetDescription>{loaded.state === "loading" ? "טוען…" : loaded.message}</SheetDescription>
      </SheetHeader>
      <div className="px-4 pb-6">
        <Button type="button" variant="secondary" size="pill" className="w-full" onClick={onClose}>
          סגירה
        </Button>
      </div>
    </>
  );
}

function parse(text: string): number | null {
  const n = Number(text.replace(/[,\s₪]/g, ""));
  return text.trim() && Number.isFinite(n) && n >= 0 ? n : null;
}

function Form({ property, onClose }: { property: Existing | null; onClose: () => void }) {
  const { online, markOffline, markDirty } = useLedgerApi();
  const [create] = useMutation<PropertyEditorSheetCreateMutation>(CREATE);
  const [update] = useMutation<PropertyEditorSheetUpdateMutation>(UPDATE);
  const [label, setLabel] = useState(property?.label ?? "דירה");
  const [value, setValue] = useState(property ? String(Number(property.value)) : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const readOnly = online !== true;
  const amount = parse(value);
  const changed = amount != null && (property == null || amount !== Number(property.value) || label.trim() !== property.label);

  const done = () => {
    setBusy(false);
    markDirty();
    onClose();
  };
  const failed = (e: Error) => {
    setBusy(false);
    setError(failureMessage(e, markOffline, "השמירה נכשלה"));
  };

  const save = () => {
    if (amount == null || !changed) return;
    setBusy(true);
    setError(null);
    const money = amount.toFixed(2);
    if (property) {
      update({ variables: { id: property.id, input: { value: money, label: label.trim() } }, onCompleted: done, onError: failed });
    } else {
      create({ variables: { input: { kind: "PROPERTY", label: label.trim() || "דירה", value: money } }, onCompleted: done, onError: failed });
    }
  };

  return (
    <>
      <SheetHeader>
        <SheetTitle className="font-display text-xl font-medium">שווי הדירה</SheetTitle>
        <SheetDescription>
          {property
            ? `עודכן ידנית ב-${property.valuedAt.split("-").reverse().join("/")}`
            : "הערכה ידנית. השווי הנקי יכלול אותה אחרי עדכון הנתונים."}
        </SheetDescription>
      </SheetHeader>

      <div className="space-y-4 px-4 pb-6">
        {error && (
          <div role="alert" className="rounded-xl bg-panel-2 px-3 py-2 text-sm text-bad">
            {error}
          </div>
        )}
        {readOnly && !error && <div className="text-xs text-muted-foreground">אין חיבור למחשב הביתי, אי אפשר לשמור עכשיו.</div>}

        <div>
          <label className="mb-1 block text-sm font-semibold" htmlFor="property-value">שווי משוער (₪)</label>
          <Input
            id="property-value"
            inputMode="decimal"
            placeholder="2,400,000"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            disabled={readOnly || busy}
            aria-invalid={value.trim() !== "" && amount == null}
            className="font-display text-2xl tabular-nums"
          />
          <div className="mt-1 text-xs text-muted-foreground">מה הדירה הייתה נמכרת בו היום, לפני משכנתא.</div>
        </div>
        <div>
          <label className="mb-1 block text-sm font-semibold" htmlFor="property-label">שם</label>
          <Input id="property-label" value={label} onChange={(e) => setLabel(e.target.value)} disabled={readOnly || busy} maxLength={80} />
        </div>

        <Button type="button" variant="primary" size="pill" className="w-full" onClick={save} disabled={readOnly || busy || !changed}>
          {busy ? "שומר…" : "שמירה"}
        </Button>
      </div>
    </>
  );
}
