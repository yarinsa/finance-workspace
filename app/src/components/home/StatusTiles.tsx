import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import { cashflow, shekel, shekelCompact, snapshot } from "@/lib/data";

function Tile({
  to,
  label,
  value,
  sub,
  tone,
  subTone,
}: {
  to: string;
  label: string;
  value: string;
  sub?: string;
  tone?: "bad";
  subTone?: "good" | "bad";
}) {
  return (
    <Link
      to={to}
      className="block min-w-0 rounded-[16px] border border-line bg-panel p-3 shadow-[var(--shadow)] transition active:scale-[.98] active:border-brand [-webkit-tap-highlight-color:transparent]"
    >
      <div className="truncate text-xs font-semibold text-muted-foreground">
        {label}
      </div>
      <div
        className={cn(
          "mt-1 truncate text-[17px] font-extrabold tabular-nums md:text-xl",
          tone === "bad" && "text-bad",
        )}
      >
        {value}
      </div>
      <div
        className={cn(
          "mt-0.5 min-h-4 truncate text-[11px] tabular-nums text-muted-foreground",
          subTone === "good" && "text-good",
          subTone === "bad" && "text-bad",
        )}
      >
        {sub}
      </div>
    </Link>
  );
}

/** Whole shekels while they fit a narrow tile; compact (₪28K) only past 5 digits. */
function tileValue(n: number): string {
  return Math.abs(n) < 10_000 ? shekel(n) : shekelCompact(n);
}

/** "33.8K" with no ₪ sign, for two amounts sharing one narrow line. */
function kilo(n: number): string {
  return Math.abs(n) < 1000 ? String(Math.round(n)) : `${(n / 1000).toFixed(1)}K`;
}

function metric(key: string) {
  return cashflow.metrics.find((m) => m.key === key);
}

function pct(v: number | null | undefined, signed = false): string {
  if (v == null) return "—";
  return `${signed && v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

/** Monzo-style summary tiles: checking balance, this month's spend vs income, budget left;
 * below them the 5-year growth index and the debt-repayment share of expenses. */
export default function StatusTiles() {
  const bank = snapshot.totals.bank_balances_sum;
  const cur = cashflow.pace?.current.expense ?? null;
  const income = cashflow.pace?.current.income ?? null;
  // This month's spend as a share of this month's income: over 100% = spending more than came in.
  const ratio = cur != null && income ? (cur / income) * 100 : null;
  const b = cashflow.budgets;
  const perDay = b?.per_day ?? null;

  const growth = metric("growth");
  const debt = metric("debt_repayment_pct");
  const rankTone = (r?: string | null) => (r === "bad" ? "bad" : undefined);
  const rankSub = (r?: string | null) =>
    r === "good" ? "good" : r === "bad" ? "bad" : undefined;

  return (
    <div className="grid gap-2.5">
        <div className="grid grid-cols-3 gap-2.5">
          <Tile
            to="/monthly?view=forecast"
            label="בעו״ש"
            value={tileValue(bank)}
            tone={bank < 0 ? "bad" : undefined}
          />
          <Tile
            to="/monthly"
            label="הוצאות/הכנסה"
            value={ratio != null ? `${Math.round(ratio)}%` : cur != null ? tileValue(cur) : "—"}
            tone={ratio != null && ratio > 100 ? "bad" : undefined}
            sub={
              cur != null && income != null
                ? `${kilo(cur)}/${kilo(income)}`
                : undefined
            }
          />
          <Tile
            to="/monthly?section=variable"
            label="נותר בתקציב"
            value={b ? tileValue(b.left) : "—"}
            tone={b && b.left < 0 ? "bad" : undefined}
            sub={perDay != null ? `${shekel(perDay)}/יום` : undefined}
          />
        </div>
        <div className="grid grid-cols-2 gap-2.5">
          <Tile
            to="/networth"
            label="מדד הצמיחה"
            value={pct(growth?.value, true)}
            tone={rankTone(growth?.rank)}
            sub="שווי נקי · 5 שנים"
            subTone={rankSub(growth?.rank)}
          />
          <Tile
            to="/metrics"
            label="אחוז החזר חוב"
            value={pct(debt?.value)}
            tone={rankTone(debt?.rank)}
            sub="מתוך ההוצאות"
            subTone={rankSub(debt?.rank)}
          />
        </div>
    </div>
  );
}
