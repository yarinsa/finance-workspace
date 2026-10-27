import { Link } from "react-router-dom";
import { Inbox } from "lucide-react";
import { useInboxCount } from "@/lib/inbox";

/** Home header entry to /inbox, with an unread-count badge. */
export default function InboxButton() {
  const count = useInboxCount();
  return (
    <Link
      to="/inbox"
      aria-label={count ? `אינבוקס, ${count} פריטים` : "אינבוקס"}
      className="relative grid size-10 place-items-center rounded-full surface text-foreground active:scale-95 [-webkit-tap-highlight-color:transparent]"
    >
      <Inbox className="size-5" />
      {count > 0 && (
        <span className="absolute -top-1 -start-1 grid min-w-5 place-items-center rounded-full bg-bad px-1 text-[11px] font-bold leading-5 text-[var(--lg-on-accent)] tabular-nums">
          {count}
        </span>
      )}
    </Link>
  );
}
