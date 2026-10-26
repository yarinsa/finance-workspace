import { useEffect, useState } from "react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { TransactionList, TransactionRow } from "@/components/TransactionRow";
import { ApiOffline, keyId, listTransactions, patchTransaction, type Row } from "@/lib/api";
import { useLedgerApi } from "@/lib/useLedgerApi";

/** Transactions hidden through the edit sheet, with a way to bring each one back. */
export default function HiddenTransactionsSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="bottom" className="max-h-[90dvh] overflow-y-auto" dir="rtl">
        {open && <Body />}
      </SheetContent>
    </Sheet>
  );
}

function Body() {
  const { online, recordEdit, markOffline, updating } = useLedgerApi();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  useEffect(() => {
    if (online !== true) return;
    let live = true;
    listTransactions({ excluded: "only" })
      .then((r) => live && setRows(r))
      .catch((e) => {
        if (!live) return;
        if (e instanceof ApiOffline) markOffline();
        else setError(e instanceof Error ? e.message : "הטעינה נכשלה");
      });
    return () => {
      live = false;
    };
  }, [online, markOffline]);

  const unhide = async (r: Row) => {
    const id = keyId(r);
    setPending(id);
    setError(null);
    try {
      recordEdit(await patchTransaction(r, { excluded: false }));
      setRows((all) => all?.filter((x) => keyId(x) !== id) ?? null);
    } catch (e) {
      if (e instanceof ApiOffline) markOffline();
      setError(e instanceof Error ? e.message : "הפעולה נכשלה");
    } finally {
      setPending(null);
    }
  };

  return (
    <>
      <SheetHeader>
        <SheetTitle className="text-lg font-bold">תנועות מוסתרות</SheetTitle>
        <SheetDescription>תנועות שהוסתרו לא נספרות בהוצאות. אפשר להחזיר אותן.</SheetDescription>
      </SheetHeader>
      <div className="px-4 pb-4">
        {online !== true ? (
          <div className="rounded-xl border border-line bg-panel-2 p-3 text-sm text-muted-foreground">
            עריכה זמינה כשהמחשב הביתי פועל
          </div>
        ) : rows == null ? (
          <div className="py-3 text-muted-foreground">טוען…</div>
        ) : rows.length === 0 ? (
          <div className="py-3 text-muted-foreground">אין תנועות מוסתרות.</div>
        ) : (
          <TransactionList>
            {rows.map((r) => (
              <TransactionRow
                key={keyId(r)}
                merchant={r.description}
                amount={r.amount}
                date={r.date}
                category={r.category}
                tags={r.tags}
                trailing={
                  <button
                    type="button"
                    disabled={pending === keyId(r)}
                    onClick={() => void unhide(r)}
                    className="shrink-0 rounded-lg border border-line px-2.5 py-1 text-xs disabled:opacity-40"
                  >
                    בטל הסתרה
                  </button>
                }
              />
            ))}
          </TransactionList>
        )}
        {updating && <div className="mt-2 text-xs text-muted-foreground">מתעדכן…</div>}
        {error && <div className="mt-2 text-sm text-bad">{error}</div>}
      </div>
    </>
  );
}
