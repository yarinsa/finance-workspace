import { Children, type ReactNode } from "react";
import CategoryTag from "@/components/CategoryTag";
import TagChips from "@/components/TagChips";
import { shekel, shekelSigned } from "@/lib/data";
import { cn } from "@/lib/utils";

/** The one transaction date format across the app: day + short month, e.g. "16 באוק׳". */
export function txDate(iso: string): string {
  return new Intl.DateTimeFormat("he-IL", { day: "numeric", month: "short" }).format(new Date(`${iso.slice(0, 10)}T12:00:00`));
}

export interface TransactionRowProps {
  merchant: string;
  /** Signed ₪, money out negative (the ledger convention). */
  amount: number;
  /** ISO date. */
  date: string;
  category?: string | null;
  tags?: string[];
  onPickTag?: (tag: string) => void;
  /** Leading 10px category dot colour. */
  dotColor?: string;
  /** Shows the "נערך" pill. */
  edited?: boolean;
  /** ₪ paid back (קיזוז): the row shows the net, with the real charge struck through. */
  offset?: number;
  /** Extra meta item after the date (e.g. the goal name). */
  meta?: ReactNode;
  /** Slot after the amount; may hold its own button. */
  trailing?: ReactNode;
  /** Makes the row content a button. `trailing` stays outside it, so buttons never nest. */
  onClick?: () => void;
}

/** The single anatomy of a ledger transaction row: merchant, category/tags/date/meta line, signed amount. Render inside `TransactionList`. */
export function TransactionRow({
  merchant,
  amount,
  date,
  category,
  tags,
  onPickTag,
  dotColor,
  edited,
  offset,
  meta,
  trailing,
  onClick,
}: TransactionRowProps) {
  const net = offset ? (amount < 0 ? amount + offset : amount - offset) : amount;
  const content = (
    <>
      {dotColor ? <i className="size-2.5 shrink-0 rounded-full" style={{ background: dotColor }} /> : null}
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{merchant}</div>
        <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          {category ? <CategoryTag name={category} /> : null}
          <TagChips tags={tags} onPick={onPickTag} />
          <span>
            {txDate(date)}
            {meta ? <> · {meta}</> : null}
          </span>
          {edited ? <span className="rounded-full bg-brand/15 px-1.5 py-px text-[10px] font-semibold">נערך</span> : null}
          {offset ? <span className="rounded-full bg-good/15 px-1.5 py-px text-[10px] font-semibold text-good">קוזז</span> : null}
        </div>
      </div>
      <div className="shrink-0 text-end tabular-nums">
        <strong className={cn("block font-semibold", net > 0 && "text-good")}>
          {net > 0 ? shekelSigned(net) : shekel(net)}
        </strong>
        {offset ? <s className="block text-xs text-muted-foreground">{shekel(amount)}</s> : null}
      </div>
    </>
  );
  const body = "flex min-w-0 flex-1 items-center gap-3";
  return (
    <div className="flex w-full items-center gap-3 py-2.5 text-[15px] leading-5">
      {onClick ? (
        <button type="button" onClick={onClick} className={cn(body, "text-start")}>
          {content}
        </button>
      ) : (
        <div className={body}>{content}</div>
      )}
      {trailing}
    </div>
  );
}

/** Divided `<ul>` of `TransactionRow`s; `inset` pads rows with `px-4` for lists that sit edge to edge in a panel. */
export function TransactionList({ children, inset }: { children: ReactNode; inset?: boolean }) {
  return (
    <ul className={cn("divide-y divide-line", inset && "[&>li]:px-4")}>
      {Children.map(children, (c) => (c ? <li>{c}</li> : null))}
    </ul>
  );
}
