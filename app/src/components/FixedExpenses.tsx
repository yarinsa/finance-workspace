import { Card, CardLabel } from "@/components/common";
import { cashflow, daysSince, num, shekel, type FixedExpenses as FX } from "@/lib/data";
import { cn } from "@/lib/utils";

const EASE: Record<FX["groups"][number]["ease"], { text: string; cls: string }> = {
  trivial: { text: "קל מאוד", cls: "pill-good" },
  easy: { text: "קל", cls: "pill-good" },
  moderate: { text: "לבירור", cls: "pill-warn" },
  wait: { text: "מסתיים", cls: "pill-muted" },
  committed: { text: "התחייבות", cls: "pill-muted" },
};

const dayMonth = new Intl.DateTimeFormat("he-IL", { day: "numeric", month: "numeric" });

/** "חויב 11.10", or a nudge when a bill hasn't been charged for a while (maybe cancelled). */
function lastCharged(iso?: string | null): { text: string; stale: boolean } | null {
  if (!iso) return null;
  const days = daysSince(`${iso}T12:00:00`);
  // 70 days: bi-monthly bills (water, municipal) are normal, not cancelled
  if (days > 70) return { text: `לא חויב מאז ${dayMonth.format(new Date(`${iso}T12:00:00`))} — אולי בוטל?`, stale: true };
  return { text: `חויב ${dayMonth.format(new Date(`${iso}T12:00:00`))}`, stale: false };
}

/**
 * Every fixed monthly bill, grouped by how realistically it can be cut —
 * fees and subscriptions first (open), loans and rent last (collapsed).
 */
export default function FixedExpenses() {
  const fx = cashflow.fixed_expenses;
  if (!fx) return null;

  return (
    <Card>
      <CardLabel>הוצאות קבועות — מה אפשר לקצץ</CardLabel>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-[28px] leading-tight font-extrabold tabular-nums">
          {shekel(fx.total)}
          <span className="text-sm font-semibold text-muted-foreground"> / חודש</span>
        </div>
        {fx.cuttable_total > 0 && (
          <span className="pill pill-good">עד {shekel(fx.cuttable_total)} בקלות</span>
        )}
      </div>

      <div className="mt-3 flex flex-col gap-2">
        {fx.groups.map((g) => {
          const ease = EASE[g.ease];
          const open = g.ease === "trivial" || g.ease === "easy";
          return (
            <details key={g.key} open={open} className="fixed-group group/fx rounded-xl bg-panel-2 px-3 py-2">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-2 py-1">
                <span className="flex min-w-0 items-center gap-2">
                  <span className="text-muted-foreground transition-transform group-open/fx:-rotate-90">‹</span>
                  <strong className="whitespace-nowrap">{g.label}</strong>
                  <span className={cn("pill whitespace-nowrap", ease.cls)}>{ease.text}</span>
                </span>
                <strong className="shrink-0 tabular-nums">{shekel(g.total)}</strong>
              </summary>
              <p className="mt-0.5 mb-1 text-xs text-muted-foreground">
                {g.lever} · {num(g.items.length)} חיובים
              </p>
              <ul className="m-0 list-none p-0">
                {g.items.map((it, i) => {
                  const lc = lastCharged(it.last_charged);
                  return (
                    <li key={i} className="flex items-center justify-between gap-3 border-t border-line py-2">
                      <div className="flex min-w-0 flex-col">
                        <span className="truncate">{it.name}</span>
                        <span className="flex flex-wrap gap-x-2 text-xs text-muted-foreground">
                          {it.category && <span>{it.category}</span>}
                          {lc && <span className={cn(lc.stale && "text-warn")}>{lc.text}</span>}
                          {it.duplicate && (
                            <span className="font-semibold text-warn">כפול · {it.duplicate_reason}</span>
                          )}
                        </span>
                      </div>
                      <strong className="shrink-0 tabular-nums">{shekel(it.amount)}</strong>
                    </li>
                  );
                })}
              </ul>
            </details>
          );
        })}
      </div>
    </Card>
  );
}
