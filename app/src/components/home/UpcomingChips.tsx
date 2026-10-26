import { Section } from "@/components/common";
import { cn } from "@/lib/utils";
import { shekelSigned, type Runway } from "@/lib/data";

const DAY = 86_400_000;
/** Copilot-style "Upcoming": always the next few items, however far out. */
const MAX_CHIPS = 6;

function when(days: number): string {
  if (days <= 0) return "היום";
  if (days === 1) return "מחר";
  return `בעוד ${days} ימים`;
}

/** Horizontal strip of the next known/inferred money events. */
export default function UpcomingChips({ runway }: { runway: Runway | undefined }) {
  if (!runway) return null;
  const start = new Date(`${runway.as_of}T12:00:00`).getTime();
  const items = runway.events
    .map((e) => ({ e, days: Math.round((new Date(`${e.date}T12:00:00`).getTime() - start) / DAY) }))
    .filter((x) => x.days >= 0)
    .sort((a, b) => a.days - b.days)
    .slice(0, MAX_CHIPS);
  if (items.length === 0) return null;

  return (
    <Section title="הבאים בתור" to="/monthly?view=forecast">
      <div className="-mx-4 flex gap-2.5 overflow-x-auto px-4 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {items.map(({ e, days }, i) => (
          <div
            key={`${e.date}-${e.name}-${i}`}
            className="w-[140px] shrink-0 rounded-[14px] border border-line bg-panel px-3 py-2.5"
          >
            <div className="text-xs font-semibold text-muted-foreground">{when(days)}</div>
            <div className="mt-0.5 truncate text-sm font-bold">{e.name}</div>
            <div className={cn("mt-0.5 text-sm font-extrabold tabular-nums", e.amount > 0 && "text-good")}>
              {shekelSigned(e.amount)}
            </div>
          </div>
        ))}
      </div>
    </Section>
  );
}
