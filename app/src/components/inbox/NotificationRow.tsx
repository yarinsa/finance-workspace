import { Link } from "react-router-dom";
import { ArchiveRestore } from "lucide-react";
import { cn } from "@/lib/utils";
import { shekel } from "@/lib/data";
import { detailChip, isUnread, type Notification, type Severity } from "@/lib/notifications";

const DOT: Record<Severity, string> = {
  critical: "bg-bad",
  high: "bg-bad/70",
  medium: "bg-warn",
  low: "bg-muted-foreground/50",
};

/** One inbox line: severity dot, bold while unread, detail chip, CTA. Tapping it (or its CTA) marks it read. */
export default function NotificationRow({
  n,
  onRead,
  onRestore,
}: {
  n: Notification;
  onRead: (n: Notification) => void;
  /** Given for archived rows: shows the restore button. */
  onRestore?: (n: Notification) => void;
}) {
  const unread = isUnread(n);
  const chip = detailChip(n);
  return (
    <div
      className="flex items-start gap-3 px-4 py-3"
      onClick={() => unread && onRead(n)}
    >
      <span className={cn("mt-2 size-2.5 shrink-0 rounded-full", DOT[n.severity], !unread && "opacity-40")} aria-hidden />
      <div className="min-w-0 flex-1">
        <div className={cn("leading-snug", unread ? "font-semibold" : "font-medium text-muted-foreground")}>
          {n.title}
          {n.amount != null && <span className="ms-2 tabular-nums">{shekel(Math.abs(n.amount))}</span>}
        </div>
        {n.detail && <div className="mt-0.5 text-sm leading-snug text-muted-foreground">{n.detail}</div>}
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {chip && <span className="rounded-full border border-line px-2.5 py-0.5 text-xs text-muted-foreground">{chip}</span>}
          {n.cta && (
            <Link
              to={n.cta.to}
              onClick={() => onRead(n)}
              className="inline-block rounded-full bg-brand/15 px-3 py-1 text-sm font-semibold text-brand no-underline"
            >
              {n.cta.label}
            </Link>
          )}
        </div>
      </div>
      {onRestore && (
        <button
          type="button"
          aria-label="שחזר מהארכיון"
          className="-m-2 shrink-0 p-2 text-muted-foreground/70"
          onClick={(e) => {
            e.stopPropagation();
            onRestore(n);
          }}
        >
          <ArchiveRestore className="size-4" />
        </button>
      )}
    </div>
  );
}
