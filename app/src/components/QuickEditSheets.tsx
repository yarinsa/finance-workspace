import { useState, type ReactNode } from "react";
import { graphql, useMutation } from "react-relay";
import { SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Input } from "@/components/ui/input";
import OptionChips from "@/components/OptionChips";
import OffsetSection from "@/components/OffsetSection";
import LiveTransactionSheet from "@/components/LiveTransactionSheet";
import type { EditTarget } from "@/components/TransactionEditSheet";
import { ApiOffline } from "@/lib/api";
import { shekel } from "@/lib/data";
import { useLedgerApi } from "@/lib/useLedgerApi";
import { toRow, type Txn } from "@/lib/txnRow";
import type { QuickEditSheetsCategoryQuery } from "@/__generated__/QuickEditSheetsCategoryQuery.graphql";
import type { QuickEditSheetsOffsetQuery } from "@/__generated__/QuickEditSheetsOffsetQuery.graphql";
import type { QuickEditSheetsCategoryMutation } from "@/__generated__/QuickEditSheetsCategoryMutation.graphql";

const CATEGORY_QUERY = graphql`
  query QuickEditSheetsCategoryQuery($date: Date!, $absAmount: Money!) {
    transactionByKey(date: $date, absAmount: $absAmount) {
      ...TransactionEditSheet_transaction @relay(mask: false)
    }
    categories(first: 200, orderBy: NAME_ASC) { edges { node { name } } }
  }
`;

const OFFSET_QUERY = graphql`
  query QuickEditSheetsOffsetQuery($date: Date!, $absAmount: Money!) {
    transactionByKey(date: $date, absAmount: $absAmount) {
      ...TransactionEditSheet_transaction @relay(mask: false)
    }
  }
`;

const SET_CATEGORY = graphql`
  mutation QuickEditSheetsCategoryMutation($input: UpdateTransactionInput!) {
    updateTransaction(input: $input) { transaction { ...TransactionEditSheet_transaction @relay(mask: false) } }
  }
`;

const RECENT_KEY = "plangram.recentCategories";
const RECENT_MAX = 5;

/** Categories last picked from the quick sheet, most recent first. */
export function readRecentCategories(): string[] {
  try {
    const v: unknown = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string").slice(0, RECENT_MAX) : [];
  } catch {
    return [];
  }
}

function rememberCategory(name: string) {
  try {
    const next = [name, ...readRecentCategories().filter((c) => c !== name)].slice(0, RECENT_MAX);
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    // Storage unavailable (private mode): recents are a convenience only.
  }
}

function Header({ tx, current }: { tx: EditTarget; current?: string }) {
  return (
    <SheetHeader>
      <SheetTitle className="text-lg font-bold">
        {tx.merchant} <span className="tabular-nums">{shekel(-Math.abs(tx.amount), { decimals: 2 })}</span>
      </SheetTitle>
      <SheetDescription>{current != null ? (current ? `קטגוריה: ${current}` : "ללא קטגוריה") : " "}</SheetDescription>
    </SheetHeader>
  );
}

const OfflineNotice = () => (
  <div className="rounded-xl border border-line bg-panel-2 p-3 text-sm text-muted-foreground">
    עריכה זמינה כשהמחשב הביתי פועל
  </div>
);

/**
 * Bottom sheet for the "assign category" swipe: recently used categories as one-tap chips,
 * then every category with a filter that doubles as "new category". Tapping saves at once
 * with `updateTransaction` carrying only `{ id, category }` (note, hide and horizon are left
 * as they are), records the row in the shared overlay and closes.
 */
export function QuickCategorySheet({ tx, onClose }: { tx: EditTarget | null; onClose: () => void }) {
  return (
    <LiveTransactionSheet<QuickEditSheetsCategoryQuery>
      query={CATEGORY_QUERY}
      tx={tx}
      onClose={onClose}
      live={(data) =>
        tx && (
          <CategoryBody
            tx={tx}
            onClose={onClose}
            txn={data.transactionByKey}
            categories={data.categories.edges.map((e) => e.node.name)}
          />
        )
      }
      fallback={({ loading }) => tx && <CategoryBody tx={tx} onClose={onClose} loading={loading} />}
    />
  );
}

function CategoryBody({
  tx,
  onClose,
  txn,
  categories = [],
  loading = false,
}: {
  tx: EditTarget;
  onClose: () => void;
  txn?: Txn | null;
  categories?: string[];
  loading?: boolean;
}) {
  const { online, recordEdit, markOffline, updating } = useLedgerApi();
  const [commit] = useMutation<QuickEditSheetsCategoryMutation>(SET_CATEGORY);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recent] = useState(readRecentCategories);

  const readOnly = online !== true || !txn;
  const disabled = readOnly || busy || loading;
  const current = txn ? (txn.category?.name ?? "") : tx.category;
  const typed = draft.trim().slice(0, 64);

  const save = (category: string) => {
    if (!txn || !category) return;
    if (category === current) return onClose();
    setBusy(true);
    setError(null);
    commit({
      variables: { input: { id: txn.id, category } },
      onCompleted: (r) => {
        rememberCategory(category);
        recordEdit(toRow(r.updateTransaction.transaction));
        setBusy(false);
        onClose();
      },
      onError: (e) => {
        setBusy(false);
        if (e instanceof ApiOffline) markOffline();
        setError(e instanceof ApiOffline ? "אין חיבור למחשב הביתי" : e.message || "השמירה נכשלה");
      },
    });
  };

  return (
    <>
      <Header tx={tx} current={loading ? undefined : current} />
      <div className="space-y-4 px-4 pb-4">
        {readOnly && !loading && <OfflineNotice />}
        {updating && <div className="text-xs text-muted-foreground">מתעדכן…</div>}

        {recent.length > 0 && (
          <div>
            <span className="mb-1 block text-xs text-muted-foreground">בשימוש לאחרונה</span>
            <div className="flex flex-wrap gap-1.5" role="listbox" aria-label="קטגוריות אחרונות">
              {recent.map((c) => (
                <button
                  key={c}
                  type="button"
                  role="option"
                  aria-selected={c === current}
                  disabled={disabled}
                  onClick={() => save(c)}
                  className={`rounded-full border px-3 py-1.5 text-sm disabled:opacity-40 ${
                    c === current ? "border-brand bg-brand/15 font-semibold" : "border-line"
                  }`}
                >
                  {c}
                </button>
              ))}
            </div>
          </div>
        )}

        <div>
          <span className="mb-1 block text-xs text-muted-foreground">כל הקטגוריות</span>
          <Input
            value={draft}
            disabled={disabled}
            maxLength={64}
            placeholder="חיפוש או קטגוריה חדשה"
            aria-label="חיפוש קטגוריה"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && typed) {
                e.preventDefault();
                save(typed);
              }
            }}
          />
          <OptionChips
            label="קטגוריות"
            options={categories}
            query={draft}
            selected={current}
            disabled={disabled}
            onPick={save}
          />
          {typed && !categories.includes(typed) && (
            <button
              type="button"
              disabled={disabled}
              onClick={() => save(typed)}
              className="mt-2 w-full rounded-lg border border-dashed border-line px-3 py-2 text-sm disabled:opacity-40"
            >
              + קטגוריה חדשה: {typed}
            </button>
          )}
        </div>

        {busy && <div className="text-xs text-muted-foreground">שומר…</div>}
        {error && <div className="text-sm text-bad">{error}</div>}
      </div>
    </>
  );
}

/**
 * Bottom sheet for the "קזז" swipe: loads the live expense and shows the offset picker
 * already open. Only expenses can be offset, so anything else gets a short note. Changes
 * are saved by `OffsetSection` itself and recorded in the shared overlay.
 */
export function QuickOffsetSheet({ tx, onClose }: { tx: EditTarget | null; onClose: () => void }) {
  return (
    <LiveTransactionSheet<QuickEditSheetsOffsetQuery>
      query={OFFSET_QUERY}
      tx={tx}
      onClose={onClose}
      live={(data) => tx && <OffsetBody tx={tx} txn={data.transactionByKey} onClose={onClose} />}
      fallback={({ loading }) => tx && <OffsetBody tx={tx} loading={loading} onClose={onClose} />}
    />
  );
}

function OffsetBody({
  tx,
  txn,
  loading = false,
  onClose,
}: {
  tx: EditTarget;
  txn?: Txn | null;
  loading?: boolean;
  onClose: () => void;
}) {
  const { online, recordEdit, updating } = useLedgerApi();
  const readOnly = online !== true || !txn;
  // Swipe-offset is only offered on expenses, so until the live row loads assume one.
  const isExpense = txn ? Number(txn.amount) < 0 : true;
  let content: ReactNode;
  if (!isExpense) {
    content = (
      <div className="rounded-xl border border-line bg-panel-2 p-3 text-sm text-muted-foreground">
        אפשר לקזז רק הוצאות מול החזרים.
      </div>
    );
  } else if (txn) {
    content = <OffsetSection txn={txn} disabled={readOnly} defaultOpen onChanged={(row) => {
      recordEdit(row);
      onClose();
    }} />;
  } else if (loading) {
    content = <div className="text-sm text-muted-foreground">טוען…</div>;
  }
  return (
    <>
      <Header tx={tx} />
      <div className="space-y-4 px-4 pb-4">
        {readOnly && !loading && <OfflineNotice />}
        {updating && <div className="text-xs text-muted-foreground">מתעדכן…</div>}
        {content}
        {isExpense && txn && (
          <button type="button" onClick={onClose} className="w-full rounded-lg border border-line px-3 py-2.5 text-sm">
            סגור
          </button>
        )}
      </div>
    </>
  );
}

/**
 * Shared wiring for the swipe-to-edit rows: `swipeProps(tx, rowAmount)` returns the
 * `onSwipeCategory` / `onSwipeOffset` props for a `TransactionRow` (offset only when the
 * row's signed amount is an expense, nothing at all while the ledger API is offline) and
 * `sheets` must be rendered once in the same list.
 */
export function useQuickEdit() {
  const { online } = useLedgerApi();
  const [quick, setQuick] = useState<{ kind: "category" | "offset"; tx: EditTarget } | null>(null);
  const close = () => setQuick(null);
  const swipeProps = (tx: EditTarget, rowAmount: number) =>
    online === true
      ? {
          onSwipeCategory: () => setQuick({ kind: "category", tx }),
          onSwipeOffset: rowAmount < 0 ? () => setQuick({ kind: "offset", tx }) : undefined,
        }
      : {};
  const sheets = (
    <>
      <QuickCategorySheet tx={quick?.kind === "category" ? quick.tx : null} onClose={close} />
      <QuickOffsetSheet tx={quick?.kind === "offset" ? quick.tx : null} onClose={close} />
    </>
  );
  return { swipeProps, sheets };
}
