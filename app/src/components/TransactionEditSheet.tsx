import { useEffect, useState } from "react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Input } from "@/components/ui/input";
import OptionChips from "@/components/OptionChips";
import {
  ApiError,
  ApiOffline,
  getCategories,
  getGoals,
  getTags,
  type Goal,
  getTransaction,
  ledgerKey,
  patchTransaction,
  putTags,
  resetTransaction,
  type Horizon,
  type Row,
} from "@/lib/api";
import { shekel } from "@/lib/data";
import { buildPatch } from "@/lib/editPatch";
import { useLedgerApi } from "@/lib/useLedgerApi";

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

/**
 * Bottom sheet for editing one transaction through the ledger API: category (picker
 * from `/api/categories` plus free text), tags (picker from `/api/tags`, type to create),
 * note, hide/unhide, and reset to scraped. Tags are saved with their own PUT and are not
 * part of the override, so "reset" leaves them.
 * When the API is unreachable it opens read-only. Writes go to the shared overlay
 * (`useLedgerApi().recordEdit`) so lists and totals update before the rebuild publishes.
 */
export default function TransactionEditSheet({ tx, onClose }: { tx: EditTarget | null; onClose: () => void }) {
  return (
    <Sheet open={tx != null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="bottom" className="max-h-[90vh] overflow-y-auto" dir="rtl">
        {tx && <Body key={`${tx.date}/${tx.amount}`} tx={tx} onClose={onClose} />}
      </SheetContent>
    </Sheet>
  );
}

function Body({ tx, onClose }: { tx: EditTarget; onClose: () => void }) {
  const { online, overlay, recordEdit, markOffline, updating } = useLedgerApi();
  const key = ledgerKey(tx);
  const known = overlay.get(`${key.date}/${key.abs_amount}`);

  const [row, setRow] = useState<Row | null>(null);
  const [categories, setCategories] = useState<string[]>([]);
  const [tagNames, setTagNames] = useState<string[]>([]);
  const [tags, setTags] = useState<string[]>(known?.tags ?? tx.tags ?? []);
  const [tagDraft, setTagDraft] = useState("");
  const [goals, setGoals] = useState<Goal[]>([]);
  const [form, setForm] = useState<{
    category: string;
    note: string;
    excluded: boolean;
    horizon?: Horizon | "clear";
    goal_id?: number | null;
  }>({
    category: tx.category,
    note: "",
    excluded: false,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const readOnly = online !== true;
  const base: Row | null = row ?? known ?? null;

  // Load the authoritative row (sources, scraped category, note, flags) and the picker values.
  useEffect(() => {
    if (online !== true) return;
    let live = true;
    void Promise.all([getTransaction(key), getCategories(), getTags(), getGoals().catch(() => [] as Goal[])])
      .then(([r, cats, allTags, allGoals]) => {
        if (!live) return;
        setRow(r);
        setCategories(cats);
        setTagNames(allTags.map((t) => t.name));
        setGoals(allGoals);
        setTags(r.tags ?? []);
        setForm({ category: r.category, note: r.note ?? "", excluded: r.excluded, horizon: r.horizon ?? undefined, goal_id: r.goal_id ?? null });
      })
      .catch((e) => {
        if (!live) return;
        if (e instanceof ApiOffline) markOffline();
        else if (e instanceof ApiError && e.status !== 404) setError(e.message);
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [online, key.date, key.abs_amount]);

  const baseline = base ?? { category: tx.category, note: null, excluded: false, horizon: null, scraped_horizon: null, goal_id: null };
  const shownGoal = form.goal_id === undefined ? (base?.goal_id ?? null) : form.goal_id;
  // Picking a goal also files the money under that goal's horizon.
  const pickGoal = (g: Goal | null) =>
    setForm((f) => ({ ...f, goal_id: g?.id ?? null, ...(g?.horizon ? { horizon: g.horizon } : {}) }));
  const shownHorizon = form.horizon === "clear" ? (base?.scraped_horizon ?? null) : (form.horizon ?? null);
  const patch = buildPatch(baseline, form);
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

  // PATCH the override fields, then PUT the tag set; the last answer is the row the overlay keeps.
  const save = async (): Promise<Row> => {
    let r: Row | null = null;
    if (Object.keys(patch).length > 0) r = await patchTransaction(key, patch);
    if (tagsDirty) r = await putTags(key, finalTags);
    return r ?? getTransaction(key);
  };

  const run = async (call: () => Promise<Row>) => {
    setBusy(true);
    setError(null);
    try {
      recordEdit(await call());
      onClose();
    } catch (e) {
      if (e instanceof ApiOffline) markOffline();
      setError(e instanceof ApiOffline ? "אין חיבור למחשב הביתי" : e instanceof Error ? e.message : "השמירה נכשלה");
    } finally {
      setBusy(false);
    }
  };

  const overridden = base?.overridden ?? tx.overridden ?? false;
  const disabled = readOnly || busy;

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
        {readOnly && (
          <div className="rounded-xl border border-line bg-panel-2 p-3 text-sm text-muted-foreground">
            עריכה זמינה כשהמחשב הביתי פועל
          </div>
        )}
        {updating && <div className="text-xs text-muted-foreground">מתעדכן…</div>}

        <label className="block">
          <span className="mb-1 block text-xs text-muted-foreground">קטגוריה</span>
          <Input
            value={form.category}
            disabled={disabled}
            maxLength={64}
            onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
          />
          <OptionChips
            label="קטגוריות"
            options={categories}
            query={form.category}
            selected={form.category}
            disabled={disabled}
            onPick={(c) => setForm((f) => ({ ...f, category: c }))}
          />
          {base && base.scraped_category && base.scraped_category !== form.category && (
            <span className="mt-1 block text-xs text-muted-foreground">מקור: {base.scraped_category}</span>
          )}
        </label>

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
              {[null, ...goals].map((g) => (
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
              onClick={() => void run(() => resetTransaction(key))}
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
