import { useState } from "react";
import { Money, Section, StatusPill } from "@/components/common";
import { cn } from "@/lib/utils";
import { shekel, shekelSigned, type Runway } from "@/lib/data";
import { initialDay, nextBeyond, weekDays } from "@/lib/week";

/**
 * "בקרוב" as the kit's week strip: the next seven days, today in a filled forest circle, a dot
 * under days with money moving. Tapping a day lists its items with the balance after each one
 * (principle: balance-after on every upcoming item, docs/ux-references.md).
 */
export default function WeekStrip({ runway }: { runway: Runway | undefined }) {
  const days = runway ? weekDays(runway) : [];
  const [selected, setSelected] = useState(() => initialDay(days));
  if (!runway || days.length === 0) return null;
  const day = days.find((d) => d.date === selected) ?? days[0];
  const next = nextBeyond(runway, days);
  const quiet = days.every((d) => d.events.length === 0);

  return (
    <Section title="בקרוב" to="/monthly?view=forecast">
      <div className="surface p-4">
        <div className="grid grid-cols-7 gap-1" role="tablist" aria-label="השבוע הקרוב">
          {days.map((d) => {
            const on = d.date === day.date;
            return (
              <button
                key={d.date}
                type="button"
                role="tab"
                aria-selected={on}
                aria-label={`${d.dow} ${d.day}${d.events.length ? `, ${d.events.length} תנועות` : ""}`}
                onClick={() => setSelected(d.date)}
                className="flex flex-col items-center gap-1.5 py-1"
              >
                <span className="text-xs text-muted-foreground">{d.dow}</span>
                <span
                  className={cn(
                    "grid size-10 place-items-center rounded-full text-[15px] tabular-nums transition-colors duration-200",
                    d.today && "bg-[var(--lg-primary)] font-semibold text-[var(--lg-on-accent)]",
                    on && !d.today && "bg-secondary ring-1 ring-[var(--lg-secondary-line)]",
                  )}
                >
                  {d.day}
                </span>
                <span
                  aria-hidden
                  className={cn("size-1.5 rounded-full", d.events.length ? "bg-[var(--lg-primary)]" : "bg-transparent")}
                />
              </button>
            );
          })}
        </div>

        <div className="mt-3 border-t border-line pt-1">
          {day.events.length === 0 ? (
            <div className="py-3 text-sm text-muted-foreground">
              {day.today ? "היום" : "ביום הזה"} אין חיובים צפויים.
              {quiet && next && ` הבא בתור: ${next.name}, ${shekel(Math.abs(next.amount))}.`}
            </div>
          ) : (
            day.events.map((e, i) => (
              <div key={`${e.name}-${i}`} className="flex items-center gap-3 border-b border-line py-3 last:border-b-0">
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate font-medium">{e.name}</span>
                  <span className="text-xs text-muted-foreground tabular-nums">
                    יתרה אחרי: <span className={cn(e.balance_after < 0 && "text-bad")}>{shekel(e.balance_after)}</span>
                  </span>
                </div>
                {e.confidence === "inferred" && <StatusPill>משוער</StatusPill>}
                <strong className={cn("font-semibold tabular-nums", e.amount > 0 && "text-good")}>
                  <Money>{shekelSigned(e.amount)}</Money>
                </strong>
              </div>
            ))
          )}
        </div>
      </div>
    </Section>
  );
}
