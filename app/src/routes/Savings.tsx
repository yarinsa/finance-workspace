import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Card, CardLabel, Page } from "@/components/common";
import NetWorthChart from "@/components/NetWorthChart";
import Horizons from "./Horizons";
import GoalEditorSheet, { type GoalEditorTarget } from "@/components/GoalEditorSheet";
import SavingsGroups from "@/components/savings/SavingsGroups";
import SavingsWidgets from "@/components/savings/SavingsWidgets";
import { CHIP_ROW, Chip } from "@/components/shared/Chip";
import TargetsSheet from "@/components/TargetsSheet";
import TransactionEditSheet, { type EditTarget } from "@/components/TransactionEditSheet";
import { TransactionRow } from "@/components/TransactionRow";
import { Input } from "@/components/ui/input";
import { goals, snapshot, sourceLabel, transactions, useDataVersion } from "@/lib/data";
import { manualPlacements, useHoldingsOverlay } from "@/lib/holdingsOverlay";
import { applyGoalsOverlay, useGoalsOverlay } from "@/lib/goalsOverlay";
import {
  SAVINGS_CATEGORY,
  groupSavings,
  holdingRows,
  movementRows,
  movementsInRange,
  parseSavingsGroup,
  savingsStats,
  type MovementRow,
  type SavingsGroupBy,
} from "@/lib/savingsView";
import { PRESET_DAYS, accountLabel, parseRange, rangeToParams, resolveRange, todayIso, type LedgerRow, type RangeSpec } from "@/lib/transactionsView";
import { useLedgerApi } from "@/lib/useLedgerApi";

const GROUP_CHIPS: { key: SavingsGroupBy; label: string }[] = [
  { key: "horizon", label: "לפי אופק" },
  { key: "goal", label: "לפי יעד" },
  { key: "kind", label: "לפי סוג" },
  { key: "institution", label: "לפי גוף" },
];

const LINK = "text-sm font-semibold text-brand hover:underline";

/**
 * "חיסכון": holdings (pension, study and provident funds, deposits: balances) and savings
 * movements (ledger rows: flows) in one screen. State lives in the URL: ?days= or ?from=&to=
 * window the movements, ?group=horizon|goal|kind|institution picks the grouping. Balances are
 * as of their read date and never added to flows; the household targets ignore the range.
 */
export default function Savings() {
  const [params, setParams] = useSearchParams();
  const { overlay, online } = useLedgerApi();
  const version = useDataVersion();
  const goalsOverlay = useGoalsOverlay();
  const holdingsOverlay = useHoldingsOverlay();
  const [editing, setEditing] = useState<EditTarget | null>(null);
  const [targetSheet, setTargetSheet] = useState(false);
  const [goalEditorTarget, setGoalEditorTarget] = useState<GoalEditorTarget | null>(null);

  const today = todayIso();
  const spec = parseRange({ days: params.get("days"), from: params.get("from"), to: params.get("to") });
  const range = resolveRange(spec, today);
  const by = parseSavingsGroup(params.get("group"));
  const custom = spec.kind === "custom";

  const { general, personal_goals } = applyGoalsOverlay(goals, goalsOverlay, version);

  const holdings = useMemo(
    () => holdingRows(snapshot.savings ?? [], today, manualPlacements(snapshot.holding_assignments, holdingsOverlay, version)),
    [version, today, holdingsOverlay],
  ); // eslint-disable-line react-hooks/exhaustive-deps
  const allMovements = useMemo(() => movementRows(transactions.transactions as LedgerRow[], overlay), [overlay, version]); // eslint-disable-line react-hooks/exhaustive-deps
  const movements = useMemo(() => movementsInRange(allMovements, range), [allMovements, range.from, range.to]); // eslint-disable-line react-hooks/exhaustive-deps
  const stats = savingsStats(holdings, movements);
  const groups = groupSavings(holdings, movements, by, {
    goals: personal_goals,
    institutionLabel: (i) => accountLabel(i, sourceLabel),
  });

  const write = (next: { spec?: RangeSpec; group?: SavingsGroupBy }) =>
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        if (next.spec) {
          for (const k of ["days", "from", "to", "range"]) p.delete(k);
          for (const [k, v] of Object.entries(rangeToParams(next.spec))) p.set(k, v);
        }
        if (next.group) {
          if (next.group === "horizon") p.delete("group");
          else p.set("group", next.group);
        }
        return p;
      },
      { replace: true },
    );
  const setCustom = (from: string, to: string) => {
    if (from && to) write({ spec: { kind: "custom", from, to } });
  };

  const renderMovement = (m: MovementRow, i: number) => {
    const target: EditTarget = { date: m.date, amount: m.amount, merchant: m.description, category: SAVINGS_CATEGORY, overridden: m.edited };
    return (
      <TransactionRow
        key={`${m.date}-${m.amount}-${i}`}
        merchant={m.description}
        amount={m.amount}
        date={m.date}
        edited={m.edited}
        meta={accountLabel(m.origin, sourceLabel)}
        onClick={() => setEditing(target)}
      />
    );
  };

  const empty = holdings.length === 0 && allMovements.length === 0 && personal_goals.length === 0;

  return (
    <Page title="חיסכון">
      <div className="flex flex-col gap-3">
        <div className={CHIP_ROW} role="group" aria-label="טווח זמן">
          {PRESET_DAYS.map((d) => (
            <Chip key={d} selected={spec.kind === "days" && spec.days === d} onClick={() => write({ spec: { kind: "days", days: d } })}>
              {d} יום
            </Chip>
          ))}
          <Chip selected={custom} onClick={() => !custom && write({ spec: { kind: "custom", ...range } })}>
            טווח אחר
          </Chip>
        </div>
        {custom && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <label className="flex flex-1 items-center gap-2">
              מ־
              <Input type="date" value={range.from} max={range.to} onChange={(e) => setCustom(e.target.value, range.to)} />
            </label>
            <label className="flex flex-1 items-center gap-2">
              עד
              <Input type="date" value={range.to} min={range.from} onChange={(e) => setCustom(range.from, e.target.value)} />
            </label>
          </div>
        )}
        <div className={CHIP_ROW} role="group" aria-label="קיבוץ">
          {GROUP_CHIPS.map((c) => (
            <Chip key={c.key} selected={by === c.key} onClick={() => write({ group: c.key })}>
              {c.label}
            </Chip>
          ))}
        </div>
      </div>

      {empty ? (
        <Card>
          <div className="text-muted-foreground">אין עדיין חיסכון להציג. אחרי סנכרון של קרנות או פיקדונות הוא יופיע כאן.</div>
        </Card>
      ) : (
        <div className="flex flex-col gap-2">
          <SavingsWidgets stats={stats} general={general} missingPiece={goals.missing_piece} />
          {online === true && (
            <div className="mt-1 flex items-baseline justify-between">
              <button type="button" className={LINK} onClick={() => setTargetSheet(true)}>
                ✎ עריכת יעדים כלליים
              </button>
              <button type="button" className={LINK} onClick={() => setGoalEditorTarget({})}>
                + הוספת יעד
              </button>
            </div>
          )}
          <p className="mt-1 text-sm text-muted-foreground tabular-nums">
            {holdings.length} קרנות ופיקדונות · {movements.length} תנועות בטווח
          </p>
          <SavingsGroups
            key={by}
            groups={groups}
            by={by}
            goals={personal_goals}
            renderMovement={renderMovement}
            onEditGoal={online === true ? (goal_id) => setGoalEditorTarget({ goal_id }) : undefined}
          />
        </div>
      )}
      <Card>
        <CardLabel>המסע הפיננסי שלי</CardLabel>
        <NetWorthChart height={280} />
      </Card>
      <Horizons />
      <TargetsSheet open={targetSheet} onClose={() => setTargetSheet(false)} />
      <GoalEditorSheet goal={goalEditorTarget} onClose={() => setGoalEditorTarget(null)} />
      <TransactionEditSheet tx={editing} onClose={() => setEditing(null)} />
    </Page>
  );
}
