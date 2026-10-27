import { useState } from "react";
import { graphql, useMutation } from "react-relay";
import { Input } from "@/components/ui/input";
import type { Row } from "@/lib/api";
import { shekel } from "@/lib/data";
import { OFFSET_KIND_LABEL, type OffsetKind } from "@/lib/spending";
import { toRow, type Txn } from "@/lib/txnRow";
import type { OffsetSectionLinkOffsetMutation } from "@/__generated__/OffsetSectionLinkOffsetMutation.graphql";
import type { OffsetSectionUnlinkOffsetMutation } from "@/__generated__/OffsetSectionUnlinkOffsetMutation.graphql";

const LINK_OFFSET = graphql`
  mutation OffsetSectionLinkOffsetMutation($input: LinkOffsetInput!) {
    linkOffset(input: $input) { expense { ...TransactionEditSheet_transaction @relay(mask: false) } }
  }
`;

const UNLINK_OFFSET = graphql`
  mutation OffsetSectionUnlinkOffsetMutation($input: UnlinkOffsetInput!) {
    unlinkOffset(input: $input) { expense { ...TransactionEditSheet_transaction @relay(mask: false) } }
  }
`;

const monthName = (iso: string) =>
  new Intl.DateTimeFormat("he-IL", { month: "long", year: "numeric" }).format(new Date(`${iso.slice(0, 7)}-15T12:00:00`));
const dayMonth = (iso: string) => iso.slice(0, 10).split("-").reverse().slice(0, 2).join("/");
const money = (s: string | number) => Number(s);

/**
 * קיזוז on an expense: the paybacks netted against it (each removable) and a picker of
 * paybacks that could be (same merchant first, then nearest date). Netting counts the
 * payback in the expense's month, so a payback into a closed month warns first. Saves
 * at once through `linkOffset` / `unlinkOffset`; the payload refreshes this sheet.
 */
export default function OffsetSection({
  txn,
  disabled,
  onChanged,
  defaultOpen = false,
}: {
  txn: Txn;
  disabled: boolean;
  onChanged: (r: Row) => void;
  /** Open the payback picker straight away (the quick-offset sheet). */
  defaultOpen?: boolean;
}) {
  const [commitLink] = useMutation<OffsetSectionLinkOffsetMutation>(LINK_OFFSET);
  const [commitUnlink] = useMutation<OffsetSectionUnlinkOffsetMutation>(UNLINK_OFFSET);
  const [open, setOpen] = useState(defaultOpen);
  const [pick, setPick] = useState<{ id: string; date: string; max: number } | null>(null);
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const left = Math.abs(money(txn.amount)) - money(txn.offsetAmount);
  const thisMonth = new Date().toISOString().slice(0, 7);
  const closed = txn.date.slice(0, 7) < thisMonth;
  const candidates = txn.offsetCandidates.edges.map((e) => e.node);

  const run = (commit: (cfg: never) => unknown, input: object, pickExpense: (r: never) => Txn) => {
    setBusy(true);
    setError(null);
    commit({
      variables: { input },
      onCompleted: (r: never) => {
        setBusy(false);
        setPick(null);
        setOpen(false);
        onChanged(toRow(pickExpense(r)));
      },
      onError: (e: Error) => {
        setBusy(false);
        setError(e.message);
      },
    } as never);
  };
  const link = () =>
    run(
      commitLink as never,
      { paybackId: pick!.id, expenseId: txn.id, ...(amount ? { amount: Number(amount).toFixed(2) } : {}) },
      (r: OffsetSectionLinkOffsetMutation["response"]) => r.linkOffset.expense,
    );
  const unlink = (paybackId: string) =>
    run(
      commitUnlink as never,
      { paybackId, expenseId: txn.id },
      (r: OffsetSectionUnlinkOffsetMutation["response"]) => r.unlinkOffset.expense,
    );

  return (
    <div className="rounded-xl border border-line p-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-semibold">קיזוז מול החזר</span>
        {txn.offsets.length > 0 && (
          <span className="text-xs tabular-nums text-muted-foreground">
            נטו {shekel(money(txn.netAmount), { decimals: 2 })}
          </span>
        )}
      </div>
      <p className="mt-0.5 text-xs text-muted-foreground">
        כסף שהוחזר לך (ביט, זיכוי, שותף לדירה) יורד מההוצאה ולא נספר כהכנסה.
      </p>

      {txn.offsets.map((o) => (
        <div key={o.transaction.id} className="mt-2 flex items-center gap-2 text-sm">
          <div className="min-w-0 flex-1">
            <div className="truncate">{o.transaction.description}</div>
            <div className="text-xs text-muted-foreground">
              {dayMonth(o.transaction.date)} · {OFFSET_KIND_LABEL[o.kind.toLowerCase() as OffsetKind]}
            </div>
          </div>
          <span className="tabular-nums text-good">−{shekel(money(o.amount), { decimals: 2 })}</span>
          <button
            type="button"
            aria-label={`בטל קיזוז ${o.transaction.description}`}
            disabled={disabled || busy}
            onClick={() => unlink(o.transaction.id)}
            className="text-muted-foreground disabled:opacity-40"
          >
            ✕
          </button>
        </div>
      ))}

      {closed && (open || txn.offsets.length > 0) && (
        <div role="note" className="mt-2 flex gap-2 rounded-xl bg-panel-2 p-3 text-xs text-muted-foreground">
          <span className="mt-1 size-1.5 shrink-0 rounded-full bg-warn" aria-hidden />
          ההוצאה מ{monthName(txn.date)}, חודש שכבר נסגר: קיזוז משנה את הסיכום שלו, גם אם ההחזר נכנס בחודש אחר.
        </div>
      )}

      {left > 0.005 &&
        (open ? (
          <div className="mt-2 space-y-1">
            {candidates.length === 0 && <div className="text-xs text-muted-foreground">אין הכנסות מתאימות סביב התאריך.</div>}
            {candidates.map((c) => {
              const max = Math.min(money(c.netAmount), left);
              const selected = pick?.id === c.id;
              return (
                <div key={c.id} className={`rounded-lg border ${selected ? "border-brand bg-brand/10" : "border-line"}`}>
                  <button
                    type="button"
                    disabled={disabled || busy}
                    onClick={() => {
                      setPick({ id: c.id, date: c.date, max });
                      setAmount(max.toFixed(2));
                    }}
                    className="flex w-full items-center gap-2 px-2 py-1.5 text-start text-sm disabled:opacity-40"
                  >
                    <span className="min-w-0 flex-1 truncate">{c.description}</span>
                    <span className="text-xs text-muted-foreground">{dayMonth(c.date)}</span>
                    <span className="tabular-nums text-good">+{shekel(money(c.netAmount), { decimals: 2 })}</span>
                  </button>
                  {selected && (
                    <div className="space-y-1.5 px-2 pb-2">
                      {c.date.slice(0, 7) !== txn.date.slice(0, 7) && (
                        <div className="text-xs text-warn">
                          ההחזר נכנס ב{monthName(c.date)} ויקוזז מההוצאה של {monthName(txn.date)}.
                        </div>
                      )}
                      <div className="flex items-center gap-2">
                        <Input
                          inputMode="decimal"
                          aria-label="סכום לקיזוז"
                          value={amount}
                          disabled={busy}
                          onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ""))}
                          className="h-9 flex-1 tabular-nums"
                        />
                        <button
                          type="button"
                          disabled={busy || !(Number(amount) > 0 && Number(amount) <= max + 0.005)}
                          onClick={link}
                          className="rounded-full bg-[var(--lg-primary)] px-3 py-2 text-sm font-semibold text-[var(--lg-on-accent)] disabled:opacity-40"
                        >
                          {busy ? "מקזז…" : "קזז"}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <button
            type="button"
            disabled={disabled}
            onClick={() => setOpen(true)}
            className="mt-2 w-full rounded-lg border border-dashed border-line px-3 py-2 text-sm disabled:opacity-40"
          >
            + קזז מול החזר
          </button>
        ))}
      {error && <div className="mt-2 text-sm text-bad">{error}</div>}
    </div>
  );
}
