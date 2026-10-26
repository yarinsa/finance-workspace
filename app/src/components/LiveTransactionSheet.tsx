import { Component, Suspense, useEffect, type ReactNode } from "react";
import { usePreloadedQuery, useQueryLoader, type GraphQLTaggedNode, type PreloadedQuery } from "react-relay";
import type { OperationType } from "relay-runtime";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { ApiOffline, ledgerKey } from "@/lib/api";
import { useLedgerApi } from "@/lib/useLedgerApi";
import type { EditTarget } from "@/components/TransactionEditSheet";

interface Props<Q extends OperationType> {
  /** A query taking `($date: Date!, $absAmount: Money!)`. */
  query: GraphQLTaggedNode;
  tx: EditTarget | null;
  onClose: () => void;
  /** Rendered with the loaded data. */
  live: (data: Q["response"]) => ReactNode;
  /** Rendered while loading and when the API is off or the load failed (read-only). */
  fallback: (state: { loading: boolean }) => ReactNode;
  className?: string;
}

/**
 * Bottom sheet that loads a transaction (and whatever else `query` fetches) once per opened
 * transaction, keyed on its date and amount. Fetching happens in an effect rather than on
 * mount: the sheet's portal and Suspense remount the body, which would refetch every time.
 * While the API is offline, or the load fails, `fallback` renders instead; an unreachable
 * API is also reported to the shared state.
 */
export default function LiveTransactionSheet<Q extends OperationType>({
  query,
  tx,
  onClose,
  live,
  fallback,
  className = "",
}: Props<Q>) {
  const { online } = useLedgerApi();
  const [queryRef, loadQuery, disposeQuery] = useQueryLoader<Q>(query);
  const date = tx ? ledgerKey(tx).date : null;
  const absAmount = tx ? ledgerKey(tx).abs_amount : null;
  useEffect(() => {
    if (online !== true || date == null || absAmount == null) return;
    loadQuery({ date, absAmount } as Q["variables"], { fetchPolicy: "network-only" });
    return () => disposeQuery();
  }, [online, date, absAmount, loadQuery, disposeQuery]);

  return (
    <Sheet open={tx != null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="bottom" className={`max-h-[90vh] overflow-y-auto ${className}`} dir="rtl">
        {tx &&
          (online === true && queryRef ? (
            <Fallback key={`${tx.date}/${tx.amount}`} fallback={fallback}>
              <Suspense fallback={fallback({ loading: true })}>
                <Live query={query} queryRef={queryRef} live={live} />
              </Suspense>
            </Fallback>
          ) : (
            fallback({ loading: online === null })
          ))}
      </SheetContent>
    </Sheet>
  );
}

function Live<Q extends OperationType>({
  query,
  queryRef,
  live,
}: {
  query: GraphQLTaggedNode;
  queryRef: PreloadedQuery<Q>;
  live: (data: Q["response"]) => ReactNode;
}) {
  return <>{live(usePreloadedQuery<Q>(query, queryRef))}</>;
}

/** A failed load shows the read-only fallback; an unreachable API is also reported to the shared state. */
class Fallback extends Component<
  { fallback: (state: { loading: boolean }) => ReactNode; children: ReactNode },
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
    return this.state.failed ? this.props.fallback({ loading: false }) : this.props.children;
  }
}
