import { Link } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { Card } from "@/components/common";
import type { MonthViewMode } from "@/components/cashflow/MonthHero";
import { cn } from "@/lib/utils";
import { shekel, type MonthGroup, type MonthViewRow } from "@/lib/data";

/**
 * One plan-vs-actual row: ₪actual מתוך ₪expected with a proportional bar. In the
 * forecast view there is no actual, so the row is just "צפוי ₪expected" (no bar).
 */
function GroupRow({ g, forecast }: { g: MonthGroup; forecast: boolean }) {
  const isIncome = g.key === "income";
  const hasBar = !forecast && g.actual != null && g.expected != null && g.expected > 0;
  const ratio = hasBar ? g.actual! / g.expected! : 0;
  const over = !isIncome && hasBar && ratio > 1;
  const met = isIncome && hasBar && ratio >= 1;
  const barCls = over ? "bg-bad" : met ? "bg-good" : "bg-brand";

  let text: string;
  if (forecast) text = g.expected != null ? `צפוי ${shekel(g.expected)}` : "—";
  else if (g.actual != null && g.expected != null) text = `${shekel(g.actual)} מתוך ${shekel(g.expected)}`;
  else if (g.actual != null) text = shekel(g.actual);
  else if (g.expected != null) text = `מתוכנן ${shekel(g.expected)}`;
  else text = "—";

  return (
    <div className="py-2">
      <div className="flex items-baseline justify-between gap-3">
        <span className="truncate">{g.label}</span>
        <strong className={cn("shrink-0 text-sm tabular-nums", over && "text-bad")}>{text}</strong>
      </div>
      {hasBar && (
        <div className="mt-1.5 h-2.5 overflow-hidden rounded-full bg-panel-2">
          <div className={cn("h-full rounded-full", barCls)} style={{ width: `${Math.min(1, ratio) * 100}%` }} />
        </div>
      )}
    </div>
  );
}

/** The selected month's plan vs actual per group (income, fixed, variable, debt & savings). */
export function MonthGroups({ m, mode }: { m: MonthViewRow; mode: MonthViewMode }) {
  if (!m.groups.length) return null;
  return (
    <Card className="divide-y divide-line !py-2">
      {m.groups.map((g) => (
        <GroupRow key={g.key} g={g} forecast={mode === "forecast"} />
      ))}
    </Card>
  );
}

/** Small row of related deep pages. */
export function MonthLinks({ links }: { links: { to: string; label: string }[] }) {
  return (
    <div className="flex flex-wrap gap-2">
      {links.map((l) => (
        <Link
          key={l.to}
          to={l.to}
          className="flex items-center gap-1 rounded-full border border-line bg-panel px-3.5 py-2 text-sm font-semibold active:bg-panel-2"
        >
          {l.label}
          <ChevronLeft className="size-4 text-muted-foreground" />
        </Link>
      ))}
    </div>
  );
}
