import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { Card, ProgressBar, StackedBar, StatusPill } from "@/components/common";
import { fullDate } from "@/components/savings/SavingsWidgets";
import { TransactionList } from "@/components/TransactionRow";
import { Button } from "@/components/ui/button";
import { num, shekel } from "@/lib/data";
import { KIND_LABEL, type HoldingRow, type MovementRow, type SavingsGroup, type SavingsGroupBy } from "@/lib/savingsView";
import { PAGE_SIZE } from "@/lib/transactionsView";

/** Each of the three horizons is meant to hold about a third of the savings. */
const HORIZON_TARGET_PCT = 100 / 3;

/** Share of all savings in a horizon, with a hairline at the one-third mark. */
function ShareBar({ share }: { share: number }) {
  const pct = Math.max(0, Math.min(1, share)) * 100;
  return (
    <div
      className="relative mt-2 h-1.5 overflow-hidden rounded-full bg-line"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(pct)}
    >
      <div className="h-full rounded-full bg-[var(--lg-primary)]" style={{ width: `${pct}%` }} />
      <div className="absolute inset-y-0 w-px bg-foreground/60" style={{ insetInlineStart: `${HORIZON_TARGET_PCT}%` }} />
    </div>
  );
}

function HoldingItem({ h, by }: { h: HoldingRow; by: SavingsGroupBy }) {
  const mark =
    h.horizonSource === "derived" ? "נגזר מתאריך הנזילות" : h.horizon == null && by !== "horizon" ? "לא משויך" : null;
  return (
    <div className="py-2.5 text-[15px] leading-5">
      <div className="flex items-baseline gap-3">
        <span className="min-w-0 flex-1 truncate font-medium" dir="auto">{h.label}</span>
        <strong className="shrink-0 font-semibold tabular-nums">{shekel(h.balance)}</strong>
      </div>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground tabular-nums">
        <span>{KIND_LABEL[h.kind] ?? h.kind}</span>
        <span>·</span>
        <span>{h.institution}</span>
        <span>·</span>
        <span>{h.liquid ? "נזיל" : h.liquidityDate ? `נזיל מ־${fullDate(h.liquidityDate)}` : "אין תאריך נזילות"}</span>
        {h.asOf && <span>· נכון ל־{fullDate(h.asOf)}</span>}
        {mark && <span className="rounded-full bg-panel-2 px-1.5 py-px text-[10px]">{mark}</span>}
      </div>
    </div>
  );
}

function GroupCard({
  g,
  by,
  totalBalance,
  renderMovement,
  onEditGoal,
  defaultOpen,
}: {
  g: SavingsGroup;
  by: SavingsGroupBy;
  totalBalance: number;
  renderMovement: (m: MovementRow, i: number) => ReactNode;
  onEditGoal?: (goalId: number) => void;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const goal = by === "goal" ? g.goal : undefined;
  const empty = g.holdings.length === 0 && g.movements.length === 0;
  const sub = [
    g.holdings.length > 0 && `${num(g.holdings.length)} קרנות`,
    g.movements.length > 0 && `${num(g.movements.length)} תנועות`,
  ]
    .filter(Boolean)
    .join(" · ");

  let bar: ReactNode = null;
  let barNote: ReactNode = null;
  if (by === "horizon" && g.key !== "none" && totalBalance > 0) {
    const share = g.balance / totalBalance;
    bar = <ShareBar share={share} />;
    barNote = `${Math.round(share * 100)}% מהחיסכון · יעד שליש`;
  } else if (goal) {
    bar = <ProgressBar className="mt-2" value={(goal.progress_pct ?? 0) / 100} />;
    barNote = `יעד ${shekel(goal.amount)} · ${goal.progress_pct != null ? `${num(goal.progress_pct)}%` : "—"}`;
  } else if (by !== "horizon" && by !== "goal" && g.balance > 0) {
    bar = <StackedBar className="mt-2" fixed={g.illiquid} variable={g.liquid} total={g.balance} />;
    barNote = `נעול ${shekel(g.illiquid)} · נזיל ${shekel(g.liquid)}`;
  }

  const flowText = g.flow > 0.5 ? `הפקדות בטווח ${shekel(g.flow)}` : g.flow < -0.5 ? `משיכות בטווח ${shekel(-g.flow)}` : null;

  return (
    <Card className="!px-4 !py-3">
      <div className="flex items-start gap-2">
        <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="block min-w-0 flex-1 text-start">
          <div className="flex items-baseline gap-2">
            <ChevronDown className={`size-4 shrink-0 self-center text-muted-foreground transition-transform ${open ? "" : "rotate-90"}`} />
            <span className="min-w-0 flex-1 truncate font-semibold">{g.label}</span>
            {(g.holdings.length > 0 || by === "horizon") && (
              <strong className="shrink-0 text-sm tabular-nums">{shekel(g.balance)}</strong>
            )}
          </div>
          {bar}
          <div className="mt-1.5 flex flex-wrap justify-between gap-x-3 text-xs text-muted-foreground tabular-nums">
            <span>{[sub, flowText].filter(Boolean).join(" · ") || (empty ? "אין כאן חיסכון" : "")}</span>
            <span>{barNote}</span>
          </div>
        </button>
        {goal && (
          <span className="flex shrink-0 items-center gap-2 pt-px">
            {goal.on_track != null && (
              <StatusPill tone={goal.on_track ? "good" : "warn"}>{goal.on_track ? "במסלול" : "כדאי לבדוק"}</StatusPill>
            )}
            {onEditGoal && goal.goal_id != null && (
              <button
                type="button"
                aria-label="עריכת יעד"
                title="עריכת יעד"
                className="text-base leading-none text-brand"
                onClick={() => onEditGoal(goal.goal_id as number)}
              >
                ✎
              </button>
            )}
          </span>
        )}
      </div>
      {open && !empty && (
        <div className="mt-1">
          {g.holdings.length > 0 && (
            <div className="divide-y divide-line">
              {g.holdings.map((h) => (
                <HoldingItem key={h.id} h={h} by={by} />
              ))}
            </div>
          )}
          {g.movements.length > 0 && (
            <>
              <div className="mt-2 text-xs font-semibold text-muted-foreground">הפקדות ומשיכות בטווח</div>
              <TransactionList>{g.movements.slice(0, limit).map(renderMovement)}</TransactionList>
              {g.movements.length > limit && (
                <Button variant="secondary" size="sm" className="mt-2" onClick={() => setLimit(limit + PAGE_SIZE)}>
                  הצג עוד
                </Button>
              )}
            </>
          )}
        </div>
      )}
    </Card>
  );
}

/**
 * The grouped list of חיסכון: one collapsible card per group with its balance (a stock) and,
 * when non-zero, its flow in the range, then a bar by grouping: share vs the one-third mark for
 * horizons, progress for goals, locked vs liquid for kind and institution. Holdings first
 * (read only: assigning them is not shipped yet), then the movements.
 */
export default function SavingsGroups({
  groups,
  by,
  renderMovement,
  onEditGoal,
}: {
  groups: SavingsGroup[];
  by: SavingsGroupBy;
  renderMovement: (m: MovementRow, i: number) => ReactNode;
  onEditGoal?: (goalId: number) => void;
}) {
  const totalBalance = groups.reduce((s, g) => s + g.balance, 0);
  return (
    <div className="flex flex-col gap-2.5">
      {groups.map((g) => (
        <GroupCard
          key={g.key}
          g={g}
          by={by}
          totalBalance={totalBalance}
          renderMovement={renderMovement}
          onEditGoal={onEditGoal}
          defaultOpen={groups.length === 1}
        />
      ))}
    </div>
  );
}
