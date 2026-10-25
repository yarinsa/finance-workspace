import { Link } from "react-router-dom";
import { Archive, Check } from "lucide-react";
import { Card, Section } from "@/components/common";
import { cn } from "@/lib/utils";
import type { HomeAction } from "@/lib/data";
import { useDismissed } from "@/lib/inbox";

const DOT: Record<HomeAction["severity"], string> = {
  critical: "bg-bad",
  high: "bg-bad/70",
  medium: "bg-warn",
  low: "bg-muted-foreground/50",
};

/** Inbox list: each item can be archived (kept locally); archived ones can be restored. */
export default function ActionList({ actions }: { actions: HomeAction[] | undefined }) {
  const [dismissed, update] = useDismissed();
  const list = actions ?? [];
  const open = list.filter((a) => !dismissed.includes(a.id));
  const hidden = list.length - open.length;

  const restore =
    hidden > 0 ? (
      <button type="button" className="text-sm font-semibold text-brand" onClick={() => update([])}>
        שחזר מהארכיון ({hidden})
      </button>
    ) : undefined;

  return (
    <Section
      title={
        <>
          פתוחים{open.length > 0 && <span className="text-muted-foreground"> · {open.length}</span>}
        </>
      }
      action={open.length > 0 ? restore : undefined}
    >
      {open.length === 0 ? (
        <Card>
          <div className="flex items-center gap-3">
            <span className="grid size-8 shrink-0 place-items-center rounded-full bg-good/15 text-good">
              <Check className="size-4" />
            </span>
            <span className="flex-1 font-bold">האינבוקס ריק ✓</span>
            {restore}
          </div>
        </Card>
      ) : (
        <div className="overflow-hidden rounded-[20px] border border-line bg-panel shadow-[var(--shadow)]">
          {open.map((a) => (
            <div key={a.id} className="flex items-start gap-3 border-b border-line px-4 py-3 last:border-b-0">
              <span className={cn("mt-2 size-2.5 shrink-0 rounded-full", DOT[a.severity])} aria-hidden />
              <div className="min-w-0 flex-1">
                <div className="font-bold leading-snug">{a.title}</div>
                <div className="mt-0.5 text-sm leading-snug text-muted-foreground">{a.detail}</div>
                {a.cta && (
                  <Link
                    to={a.cta.to}
                    className="mt-2 inline-block rounded-full bg-brand/15 px-3 py-1 text-sm font-bold text-brand no-underline"
                  >
                    {a.cta.label}
                  </Link>
                )}
              </div>
              <button
                type="button"
                aria-label="העבר לארכיון"
                className="-m-2 shrink-0 p-2 text-muted-foreground/70"
                onClick={() => update([...dismissed, a.id])}
              >
                <Archive className="size-4" />
              </button>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}
