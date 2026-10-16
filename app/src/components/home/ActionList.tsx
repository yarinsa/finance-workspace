import { useState } from "react";
import { Link } from "react-router-dom";
import { Check, X } from "lucide-react";
import { Card } from "@/components/common";
import { cn } from "@/lib/utils";
import type { HomeAction } from "@/lib/data";

const STORAGE_KEY = "plangram.dismissed-actions";
const VISIBLE = 4;

function readDismissed(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const v = raw ? JSON.parse(raw) : [];
    return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function writeDismissed(ids: string[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
  } catch {
    /* storage unavailable: dismissal lasts for this session only */
  }
}

const DOT: Record<HomeAction["severity"], string> = {
  critical: "bg-bad",
  high: "bg-bad/70",
  medium: "bg-warn",
  low: "bg-muted-foreground/50",
};

/** Copilot-style "to review" list. Renders nothing when the pipeline emits no actions. */
export default function ActionList({ actions }: { actions: HomeAction[] | undefined }) {
  const [dismissed, setDismissed] = useState<string[]>(readDismissed);
  const [expanded, setExpanded] = useState(false);
  if (!actions) return null;

  const open = actions.filter((a) => !dismissed.includes(a.id));
  const hidden = actions.length - open.length;
  const shown = expanded ? open : open.slice(0, VISIBLE);

  const update = (ids: string[]) => {
    setDismissed(ids);
    writeDismissed(ids);
  };

  return (
    <section>
      <header className="mb-2.5 flex items-baseline justify-between">
        <h2 className="m-0 text-lg font-extrabold">
          לטיפול{open.length > 0 && <span className="text-muted-foreground"> · {open.length}</span>}
        </h2>
        {hidden > 0 && open.length > 0 && (
          <button type="button" className="text-sm font-semibold text-brand" onClick={() => update([])}>
            הצג שהוסתרו
          </button>
        )}
      </header>

      {open.length === 0 ? (
        <Card>
          <div className="flex items-center gap-3">
            <span className="grid size-8 shrink-0 place-items-center rounded-full bg-good/15 text-good">
              <Check className="size-4" />
            </span>
            <span className="flex-1 font-bold">הכל מטופל ✓</span>
            {hidden > 0 && (
              <button type="button" className="text-sm font-semibold text-brand" onClick={() => update([])}>
                הצג שהוסתרו
              </button>
            )}
          </div>
        </Card>
      ) : (
        <div className="overflow-hidden rounded-[20px] border border-line bg-panel shadow-[var(--shadow)]">
          {shown.map((a) => (
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
                aria-label="הסתר"
                className="-m-2 shrink-0 p-2 text-muted-foreground/70"
                onClick={() => update([...dismissed, a.id])}
              >
                <X className="size-4" />
              </button>
            </div>
          ))}
          {!expanded && open.length > VISIBLE && (
            <button
              type="button"
              className="w-full px-4 py-2.5 text-sm font-semibold text-brand"
              onClick={() => setExpanded(true)}
            >
              עוד {open.length - VISIBLE}
            </button>
          )}
        </div>
      )}
    </section>
  );
}
