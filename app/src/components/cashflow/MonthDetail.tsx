import { Link } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { BarRow, BigNumber, Card, CardLabel } from "@/components/common";
import { cn } from "@/lib/utils";
import { monthYear, shekel, shekelSigned, type MonthGroup, type MonthViewRow } from "@/lib/data";

/** Income / Spend / Net for the selected month (Rocket Money / Monarch), with end-of-month expectation. */
export function MonthResult({ m }: { m: MonthViewRow }) {
  const tone = m.net >= 0 ? "good" : "bad";
  return (
    <Card>
      <div className="flex items-center justify-between gap-2">
        <CardLabel>{monthYear(`${m.month}-01`)}</CardLabel>
        {m.kind === "projected" && <span className="pill pill-muted -mt-2">תחזית</span>}
        {m.kind === "current" && <span className="pill pill-good -mt-2">החודש</span>}
      </div>
      <BigNumber tone={tone}>{shekelSigned(m.net)}</BigNumber>
      <div className="mt-1 text-sm text-muted-foreground tabular-nums">
        הכנסות {shekel(m.income)} · הוצאות {shekel(m.expense)}
      </div>
      {m.kind === "current" && m.projected_end && (
        <div className="mt-3 flex items-baseline justify-between gap-3 border-t border-line pt-3">
          <span>צפי לסוף החודש</span>
          <strong className={cn("tabular-nums", m.projected_end.net >= 0 ? "text-good" : "text-bad")}>
            {shekelSigned(m.projected_end.net)}
          </strong>
        </div>
      )}
    </Card>
  );
}

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

/** Monarch/Quicken-style plan vs actual for the four groups. */
export function PlanVsActual({ m }: { m: MonthViewRow }) {
  if (!m.groups.length) return null;
  return (
    <Card>
      <CardLabel>תכנון מול בפועל</CardLabel>
      {m.groups.map((g) => (
        <GroupRow key={g.key} g={g} projected={m.kind === "projected"} />
      ))}
    </Card>
  );
}

/** That month's categories (top 8 + "עוד"); each row opens the spending explorer. */
export function MonthCategories({ m }: { m: MonthViewRow }) {
  if (!m.categories.length) return null;
  const sorted = [...m.categories].sort((a, b) => b.amount - a.amount);
  const top = sorted.slice(0, 8);
  const rest = sorted.slice(8);
  const max = top[0]?.amount || 1;
  const restSum = rest.reduce((s, c) => s + c.amount, 0);
  return (
    <Card>
      <CardLabel>לאן הלך הכסף</CardLabel>
      {top.map((c) => (
        <Link key={c.name} to={`/spending?month=${m.month}&cat=${encodeURIComponent(c.name)}`} className="block active:opacity-70">
          <BarRow label={c.name} value={shekel(c.amount)} fraction={c.amount / max} />
        </Link>
      ))}
      {rest.length > 0 && (
        <Link to={`/spending?month=${m.month}`} className="mt-1 flex items-baseline justify-between gap-3 py-2 text-muted-foreground">
          <span>עוד {rest.length} קטגוריות</span>
          <strong className="tabular-nums">{shekel(restSum)}</strong>
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
