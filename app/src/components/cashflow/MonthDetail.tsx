import { Link } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { BigNumber, Card, CardLabel } from "@/components/common";
import { cn } from "@/lib/utils";
import { monthYear, shekel, shekelSigned, type MonthGroup, type MonthViewRow } from "@/lib/data";

/** One plan-vs-actual row: ₪actual מתוך ₪expected with a proportional bar. */
function GroupRow({ g, projected }: { g: MonthGroup; projected: boolean }) {
  const isIncome = g.key === "income";
  const hasBar = g.actual != null && g.expected != null && g.expected > 0;
  const ratio = hasBar ? g.actual! / g.expected! : 0;
  const over = !isIncome && hasBar && ratio > 1;
  const met = isIncome && hasBar && ratio >= 1;
  const barCls = over ? "bg-bad" : met ? "bg-good" : "bg-brand";

  let text: string;
  if (g.actual != null && g.expected != null) text = `${shekel(g.actual)} מתוך ${shekel(g.expected)}`;
  else if (g.actual != null) text = shekel(g.actual);
  else if (g.expected != null) text = projected ? `צפוי ${shekel(g.expected)}` : `מתוכנן ${shekel(g.expected)}`;
  else text = "—";

  return (
    <div className="py-2">
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <span className="truncate">{g.label}</span>
        <strong className={cn("shrink-0 text-sm tabular-nums", over && "text-bad")}>{text}</strong>
      </div>
      {hasBar && (
        <div className="h-2.5 overflow-hidden rounded-full bg-panel-2">
          <div className={cn("h-full rounded-full", barCls)} style={{ width: `${Math.min(1, ratio) * 100}%` }} />
        </div>
      )}
    </div>
  );
}

/**
 * The selected month in one card: net, end-of-month expectation, then plan vs actual per group
 * (the group rows already carry income and expense, so no separate totals line), and a link to
 * that month's spending for anything already spent.
 */
export function MonthSummary({ m }: { m: MonthViewRow }) {
  const tone = m.net >= 0 ? "good" : "bad";
  return (
    <Card>
      <div className="flex items-center justify-between gap-2">
        <CardLabel>{monthYear(`${m.month}-01`)}</CardLabel>
        {m.kind === "projected" && <span className="pill pill-muted -mt-2">תחזית</span>}
        {m.kind === "current" && <span className="pill pill-good -mt-2">החודש</span>}
      </div>
      <BigNumber tone={tone}>{shekelSigned(m.net)}</BigNumber>
      {m.kind === "current" && m.projected_end && (
        <div className="mt-1 text-sm text-muted-foreground">
          צפי לסוף החודש{" "}
          <strong className={cn("tabular-nums", m.projected_end.net >= 0 ? "text-good" : "text-bad")}>
            {shekelSigned(m.projected_end.net)}
          </strong>
        </div>
      )}
      {m.groups.length > 0 && (
        <div className="mt-3 border-t border-line pt-1">
          {m.groups.map((g) => (
            <GroupRow key={g.key} g={g} projected={m.kind === "projected"} />
          ))}
        </div>
      )}
      {m.kind !== "projected" && (
        <Link
          to={`/spending?month=${m.month}`}
          className="mt-2 flex items-center justify-between gap-3 border-t border-line pt-3 font-semibold text-brand"
        >
          לאן הלך הכסף
          <ChevronLeft className="size-4" />
        </Link>
      )}
    </Card>
  );
}

const LINKS = [
  { to: "/runway", label: "יתרה יומית" },
  { to: "/timeline", label: "ציר זמן" },
  { to: "/metrics", label: "מדדים" },
];

/** Small row of related deep pages. */
export function CashflowLinks() {
  return (
    <div className="flex flex-wrap gap-2">
      {LINKS.map((l) => (
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
