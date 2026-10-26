import { Component, Suspense, useEffect, useState, type ReactNode } from "react";
import { graphql, useMutation, usePreloadedQuery, useQueryLoader, type PreloadedQuery } from "react-relay";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Input } from "@/components/ui/input";
import OptionChips from "@/components/OptionChips";
import { CategoryPickerSheet } from "@/components/CategoryPicker";
import { readRecentCategories } from "@/components/QuickEditSheets";
import { ApiOffline, ledgerKey, type Horizon, type Row } from "@/lib/api";
import { shekel } from "@/lib/data";
import { buildPatch } from "@/lib/editPatch";
import { useLedgerApi } from "@/lib/useLedgerApi";
import type { TransactionEditSheetQuery } from "@/__generated__/TransactionEditSheetQuery.graphql";
import type { TransactionEditSheetUpdateMutation } from "@/__generated__/TransactionEditSheetUpdateMutation.graphql";
import type { TransactionEditSheetTagsMutation } from "@/__generated__/TransactionEditSheetTagsMutation.graphql";
import type { TransactionEditSheetClearMutation } from "@/__generated__/TransactionEditSheetClearMutation.graphql";
import OffsetSection from "@/components/OffsetSection";
import { lower, toRow, type Txn } from "@/lib/txnRow";

export { toRow, type Txn };

export const HORIZON_LABEL: Record<Horizon, string> = {
  current: "אני של היום",
  near: "אני של העתיד הקרוב",
  future: "אני של העתיד (פרישה)",
};
export const HORIZON_SHORT: Record<Horizon, string> = { current: "היום", near: "עתיד קרוב", future: "פרישה" };

/** What the static data knows about a transaction before the API is asked. */
export interface EditTarget {
  date: string;
  /** Signed or positive; only the magnitude is used for the key. */
  amount: number;
  merchant: string;
  category: string;
  overridden?: boolean;
  tags?: string[];
}

const sameTags = (a: string[], b: string[]) => a.length === b.length && a.every((t, i) => t === b[i]);

// Picker lists are small (a household's categories, tags and goals); 200 is the API's page cap.
const QUERY = graphql`
  query TransactionEditSheetQuery($date: Date!, $absAmount: Money!) {
    transactionByKey(date: $date, absAmount: $absAmount) {
      ...TransactionEditSheet_transaction @relay(mask: false)
    }
    categories(first: 200, orderBy: NAME_ASC) { edges { node { name } } }
    tags(first: 200, orderBy: NAME_ASC) { edges { node { name } } }
    goals(first: 200) { edges { node { id description horizon { key } } } }
  }
`;

graphql`
  fragment TransactionEditSheet_transaction on Transaction {
    id date amount absAmount description origin sources note excluded overridden
    category { name }
    horizon { key }
    goal { id description }
    raw { category { name } horizon { key } }
    tags(first: 50) { edges { node { name } } }
    netAmount offsetAmount
    offsets { amount kind transaction { id date description amount } }
    offsetCandidates(first: 20) { edges { node { id date description amount netAmount } } }
  }
`;

const UPDATE = graphql`
  mutation TransactionEditSheetUpdateMutation($input: UpdateTransactionInput!) {
    updateTransaction(input: $input) { transaction { ...TransactionEditSheet_transaction @relay(mask: false) } }
  }
`;

const SET_TAGS = graphql`
  mutation TransactionEditSheetTagsMutation($input: SetTransactionTagsInput!) {
    setTransactionTags(input: $input) { transaction { ...TransactionEditSheet_transaction @relay(mask: false) } }
  }
`;

const CLEAR = graphql`
  mutation TransactionEditSheetClearMutation($input: ClearTransactionOverrideInput!) {
    clearTransactionOverride(input: $input) { transaction { ...TransactionEditSheet_transaction @relay(mask: false) } }
  }
`;

type GoalOption = { id: string; description: string; horizon: Horizon | null };

/**
 * Bottom sheet for editing one transaction through the ledger API's GraphQL endpoint:
 * category (picker plus free text), tags (picker, type to create), note, horizon, goal,
 * hide/unhide, and reset to raw. One query loads the transaction and the pickers; saves
 * are the `updateTransaction` / `setTransactionTags` / `clearTransactionOverride`
 * mutations. Tags are not part of the override, so "reset" leaves them.
 * When the API is unreachable it opens read-only from the static data. Writes go to the
 * shared overlay (`useLedgerApi().recordEdit`) so lists and totals update before the
 * rebuild publishes.
 */
export default function TransactionEditSheet({ tx, onClose }: { tx: EditTarget | null; onClose: () => void }) {
  const { online } = useLedgerApi();
  // Fetch once per opened transaction, here rather than on mount: the sheet's portal and
  // Suspense remount the body, and a fetch-on-mount query would refetch on every remount.
  const [queryRef, loadQuery, disposeQuery] = useQueryLoader<TransactionEditSheetQuery>(QUERY);
  const date = tx ? ledgerKey(tx).date : null;
  const absAmount = tx ? ledgerKey(tx).abs_amount : null;
  useEffect(() => {
    if (online !== true || date == null || absAmount == null) return;
    loadQuery({ date, absAmount }, { fetchPolicy: "network-only" });
    return () => disposeQuery();
  }, [online, date, absAmount, loadQuery, disposeQuery]);

  return (
    <Sheet open={tx != null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="bottom" className="max-h-[90vh] overflow-y-auto" dir="rtl">
        {tx &&
          (online === true && queryRef ? (
            <OfflineFallback key={`${tx.date}/${tx.amount}`} tx={tx} onClose={onClose}>
              <Suspense fallback={<Body tx={tx} onClose={onClose} loading />}>
                <LiveBody tx={tx} onClose={onClose} queryRef={queryRef} />
              </Suspense>
            </OfflineFallback>
          ) : (
            <Body key={`${tx.date}/${tx.amount}`} tx={tx} onClose={onClose} />
          ))}
      </SheetContent>
    </Sheet>
  );
}

/** A failed load shows the read-only sheet; an unreachable API is also reported to the shared state. */
class OfflineFallback extends Component<
  { tx: EditTarget; onClose: () => void; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: unknown) {
    if (error instanceof ApiOffline) window.dispatchEvent(new Event("ledger-api-offline"));
  }
  render() {
    return this.state.failed ? <Body tx={this.props.tx} onClose={this.props.onClose} /> : this.props.children;
  }
}

function LiveBody({
  tx,
  onClose,
  queryRef,
}: {
  tx: EditTarget;
  onClose: () => void;
  queryRef: PreloadedQuery<TransactionEditSheetQuery>;
}) {
  const data = usePreloadedQuery<TransactionEditSheetQuery>(QUERY, queryRef);
  return (
    <Body
      tx={tx}
      onClose={onClose}
      txn={data.transactionByKey}
      categories={data.categories.edges.map((e) => e.node.name)}
      tagNames={data.tags.edges.map((e) => e.node.name)}
      goals={data.goals.edges.map((e) => ({
        id: e.node.id,
        description: e.node.description,
        horizon: lower(e.node.horizon?.key),
      }))}
    />
  );
}

interface BodyProps {
  tx: EditTarget;
  onClose: () => void;
  /** The live transaction; absent when read-only (API off) or still loading. */
  txn?: Txn | null;
  categories?: string[];
  tagNames?: string[];
  goals?: GoalOption[];
  loading?: boolean;
}

function Body({ tx, onClose, txn, categories = [], tagNames = [], goals = [], loading = false }: BodyProps) {
  const { online, overlay, recordEdit, markOffline, updating } = useLedgerApi();
  const key = ledgerKey(tx);
  const known = overlay.get(`${key.date}/${key.abs_amount}`);
  const base: Row | null = txn ? toRow(txn) : (known ?? null);
  const baseGoal = txn?.goal?.id ?? null;

  const [tags, setTags] = useState<string[]>(base?.tags ?? tx.tags ?? []);
  const [tagDraft, setTagDraft] = useState("");
  const [form, setForm] = useState<{
    category: string;
    note: string;
    excluded: boolean;
    horizon?: Horizon | "clear";
    goal_id?: string | null;
  }>(() =>
    base
      ? { category: base.category, note: base.note ?? "", excluded: base.excluded, horizon: base.horizon ?? undefined }
      : { category: tx.category, note: "", excluded: false },
  );
  const [pickingCategory, setPickingCategory] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [commitUpdate] = useMutation<TransactionEditSheetUpdateMutation>(UPDATE);
  const [commitTags] = useMutation<TransactionEditSheetTagsMutation>(SET_TAGS);
  const [commitClear] = useMutation<TransactionEditSheetClearMutation>(CLEAR);

  const readOnly = online !== true || !txn;

  const baseline = {
    ...(base ?? { category: tx.category, note: null, excluded: false, horizon: null, scraped_horizon: null }),
    goal_id: baseGoal,
  };
  const shownGoal = form.goal_id === undefined ? baseGoal : form.goal_id;
  // Picking a goal also files the money under that goal's horizon.
  const pickGoal = (g: GoalOption | null) =>
    setForm((f) => ({ ...f, goal_id: g?.id ?? null, ...(g?.horizon ? { horizon: g.horizon } : {}) }));
  const shownHorizon = form.horizon === "clear" ? (base?.scraped_horizon ?? null) : (form.horizon ?? null);
  const patch = buildPatch<string>(baseline, form);
  const savedTags = base?.tags ?? tx.tags ?? [];
  // A name typed but not yet confirmed with Enter still counts when saving.
  const draft = tagDraft.trim().slice(0, 40);
  const finalTags = draft && !tags.includes(draft) ? [...tags, draft].sort((x, y) => x.localeCompare(y, "he")) : tags;
  const tagsDirty = !sameTags(finalTags, savedTags);
  const dirty = Object.keys(patch).length > 0 || tagsDirty;

  const addTag = (raw: string) => {
    const name = raw.trim().slice(0, 40);
    setTagDraft("");
    if (name && !tags.includes(name)) setTags((ts) => [...ts, name].sort((a, b) => a.localeCompare(b, "he")));
  };

  /** Commit one mutation and hand back the transaction its payload carries. */
  const mutate = <M extends { response: object }>(
    commit: (cfg: { variables: never; onCompleted: (r: M["response"]) => void; onError: (e: Error) => void }) => unknown,
    variables: object,
    pick: (r: M["response"]) => Txn,
  ) =>
    new Promise<Txn>((resolve, reject) =>
      commit({ variables: variables as never, onCompleted: (r) => resolve(pick(r)), onError: reject }),
    );

  // updateTransaction for the override fields, then setTransactionTags; the last payload is what the overlay keeps.
  const save = async (): Promise<Txn> => {
    const id = txn!.id;
    let t: Txn = txn!;
    if (Object.keys(patch).length > 0) {
      const { goal_id, horizon, ...rest } = patch;
      const input = {
        id,
        ...rest,
        ...(horizon !== undefined ? { horizon: horizon ? (horizon.toUpperCase() as "CURRENT" | "NEAR" | "FUTURE") : null } : {}),
        ...(goal_id !== undefined ? { goalId: goal_id } : {}),
      };
      t = await mutate<TransactionEditSheetUpdateMutation>(commitUpdate, { input }, (r) => r.updateTransaction.transaction);
    }
    if (tagsDirty) {
      t = await mutate<TransactionEditSheetTagsMutation>(
        commitTags,
        { input: { id, tags: finalTags } },
        (r) => r.setTransactionTags.transaction,
      );
    }
    return t;
  };

  const reset = () =>
    mutate<TransactionEditSheetClearMutation>(
      commitClear,
      { input: { id: txn!.id } },
      (r) => r.clearTransactionOverride.transaction,
    );

  const run = async (call: () => Promise<Txn>) => {
    setBusy(true);
    setError(null);
    try {
      recordEdit(toRow(await call()));
      onClose();
    } catch (e) {
      if (e instanceof ApiOffline) markOffline();
      setError(e instanceof ApiOffline ? "אין חיבור למחשב הביתי" : e instanceof Error ? e.message : "השמירה נכשלה");
    } finally {
      setBusy(false);
    }
  };

  const overridden = base?.overridden ?? tx.overridden ?? false;
  const disabled = readOnly || busy || loading;

  return (
    <>
      <SheetHeader>
        <SheetTitle className="text-lg font-bold">{base?.description || tx.merchant}</SheetTitle>
        <SheetDescription className="tabular-nums">
          {key.date.split("-").reverse().join("/")} · {shekel(-Math.abs(tx.amount), { decimals: 2 })}
          {base?.sources?.length ? ` · ${base.sources.join(", ")}` : ""}
          {overridden && (
            <span className="ms-2 rounded-full bg-brand/15 px-2 py-0.5 text-xs font-semibold">נערך</span>
          )}
        </SheetDescription>
      </SheetHeader>

      <div className="space-y-4 px-4 pb-4">
        {readOnly && !loading && (
          <div className="rounded-xl border border-line bg-panel-2 p-3 text-sm text-muted-foreground">
            עריכה זמינה כשהמחשב הביתי פועל
          </div>
        )}
        {updating && <div className="text-xs text-muted-foreground">מתעדכן…</div>}

        <div>
          <span className="mb-1 block text-xs text-muted-foreground">קטגוריה</span>
          <button
            type="button"
            disabled={disabled}
            onClick={() => setPickingCategory(true)}
            className="flex min-h-11 w-full items-center justify-between rounded-lg border border-line px-3 text-start text-[15px] disabled:opacity-40"
          >
            <span className={form.category ? "" : "text-muted-foreground"}>{form.category || "בחירת קטגוריה"}</span>
            <span className="text-muted-foreground" aria-hidden>‹</span>
          </button>
          <CategoryPickerSheet
            open={pickingCategory}
            onClose={() => setPickingCategory(false)}
            categories={categories}
            current={form.category}
            recent={readRecentCategories()}
            onPick={(c) => setForm((f) => ({ ...f, category: c }))}
          />
          {base && base.scraped_category && base.scraped_category !== form.category && (
            <span className="mt-1 block text-xs text-muted-foreground">מקור: {base.scraped_category}</span>
          )}
        </div>

        <div>
          <span className="mb-1 block text-xs text-muted-foreground">תגיות</span>
          <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-line px-2 py-1.5">
            {tags.map((t) => (
              <span key={t} className="inline-flex items-center gap-1 rounded-full border border-brand/40 px-2 py-0.5 text-xs text-brand">
                #{t}
                <button
                  type="button"
                  aria-label={`הסר ${t}`}
                  disabled={disabled}
                  onClick={() => setTags((ts) => ts.filter((x) => x !== t))}
                  className="disabled:opacity-40"
                >
                  ✕
                </button>
              </span>
            ))}
            <input
              value={tagDraft}
              disabled={disabled}
              maxLength={40}
              placeholder={tags.length ? "" : "הוסיפו תגית (Enter)"}
              aria-label="תגית חדשה"
              className="min-w-[90px] flex-1 bg-transparent py-0.5 text-sm outline-none"
              onChange={(e) => setTagDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === ",") {
                  e.preventDefault();
                  addTag(tagDraft);
                } else if (e.key === "Backspace" && tagDraft === "" && tags.length) {
                  setTags((ts) => ts.slice(0, -1));
                }
              }}
            />
          </div>
          <OptionChips
            label="תגיות קיימות"
            options={tagNames.filter((t) => !tags.includes(t))}
            query={tagDraft}
            disabled={disabled}
            onPick={addTag}
          />
        </div>

        <label className="block">
          <span className="mb-1 block text-xs text-muted-foreground">הערה</span>
          <Input
            value={form.note}
            disabled={disabled}
            maxLength={500}
            placeholder="אפשר להוסיף הערה"
            onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))}
          />
        </label>

        <div>
          <span className="mb-1 block text-xs text-muted-foreground">שייך ל…</span>
          <div className="grid grid-cols-3 gap-1.5" role="radiogroup" aria-label="אופק">
            {(Object.keys(HORIZON_SHORT) as Horizon[]).map((h) => (
              <button
                key={h}
                type="button"
                role="radio"
                aria-checked={shownHorizon === h}
                title={HORIZON_LABEL[h]}
                disabled={disabled}
                onClick={() => setForm((f) => ({ ...f, horizon: h }))}
                className={`rounded-lg border px-2 py-2 text-sm disabled:opacity-40 ${
                  shownHorizon === h ? "border-brand bg-brand/15 font-semibold" : "border-line"
                }`}
              >
                {HORIZON_SHORT[h]}
              </button>
            ))}
          </div>
          {base && base.horizon !== (base.scraped_horizon ?? null) && form.horizon !== "clear" && (
            <button
              type="button"
              disabled={disabled}
              onClick={() => setForm((f) => ({ ...f, horizon: "clear" }))}
              className="mt-1 text-xs text-muted-foreground underline disabled:opacity-40"
            >
              נקה (לפי הכלל: {base.scraped_horizon ? HORIZON_SHORT[base.scraped_horizon] : "ללא"})
            </button>
          )}
        </div>

        {goals.length > 0 && (
          <div>
            <span className="mb-1 block text-xs text-muted-foreground">הכסף הלך ליעד…</span>
            <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="יעד">
              {[null, ...goals].map((g: GoalOption | null) => (
                <button
                  key={g?.id ?? "none"}
                  type="button"
                  role="radio"
                  aria-checked={shownGoal === (g?.id ?? null)}
                  disabled={disabled}
                  onClick={() => pickGoal(g)}
                  className={`rounded-full border px-3 py-1 text-sm disabled:opacity-40 ${
                    shownGoal === (g?.id ?? null) ? "border-brand bg-brand/15 font-semibold" : "border-line"
                  }`}
                >
                  {g ? g.description : "ללא יעד"}
                  {g?.horizon && <span className="ms-1 text-xs text-muted-foreground">· {HORIZON_SHORT[g.horizon]}</span>}
                </button>
              ))}
            </div>
          </div>
        )}

        {txn && Number(txn.amount) < 0 && <OffsetSection txn={txn} disabled={disabled} onChanged={recordEdit} />}

        <label className="flex items-center gap-3 text-sm">
          <input
            type="checkbox"
            className="size-4"
            checked={form.excluded}
            disabled={disabled}
            onChange={(e) => setForm((f) => ({ ...f, excluded: e.target.checked }))}
          />
          הסתר תנועה (לא תיכלל בסכומים וברשימות)
        </label>

        {error && <div className="text-sm text-bad">{error}</div>}

        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={disabled || !dirty}
            onClick={() => void run(save)}
            className="flex-1 rounded-lg bg-brand px-3 py-2.5 text-sm font-semibold text-white disabled:opacity-40"
          >
            {busy ? "שומר…" : "שמירה"}
          </button>
          {overridden && (
            <button
              type="button"
              disabled={disabled}
              onClick={() => void run(reset)}
              className="rounded-lg border border-line px-3 py-2.5 text-sm disabled:opacity-40"
            >
              החזר למקור
            </button>
          )}
        </div>
      </div>
    </>
  );
}
