import { pct as fmtPct, shekel, type Pace, type PaceAverage, type PaceSide } from "@/lib/data";

const monthName = (ym: string) =>
  new Intl.DateTimeFormat("he-IL", { month: "long" }).format(new Date(`${ym}-01T12:00:00`));

/** Percent change, or null when the base is too small to be meaningful. */
function change(now: number, before: number): number | null {
  if (Math.abs(before) < 1) return null;
  return ((now - before) / Math.abs(before)) * 100;
}

/** Cumulative spend this month (solid) over last month's full curve (dashed). */
function PaceSpark({ cur, prev, avg }: { cur: PaceSide; prev: PaceSide; avg?: PaceAverage | null }) {
  const W = 300;
  const H = 64;
  const days = Math.max(prev.daily_expense.length, avg?.daily_expense.length ?? 0, 28);
  const max = Math.max(prev.month_expense, avg?.month_expense ?? 0, ...cur.daily_expense, 1);
  const pts = (arr: number[]) =>
    arr.map((v, i) => `${((i + 0.5) / days) * W},${H - 4 - (v / max) * (H - 8)}`).join(" ");
  const last = cur.daily_expense.length;
  const lastY = H - 4 - ((cur.daily_expense[last - 1] ?? 0) / max) * (H - 8);
  return (
    <svg className="wallet-spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden>
      <defs>
        <linearGradient id="spark-glow" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" style={{ stopColor: "var(--hero-line)", stopOpacity: 0.35 }} />
          <stop offset="100%" style={{ stopColor: "var(--hero-line)", stopOpacity: 0 }} />
        </linearGradient>
      </defs>
      {last > 0 && (
        <polygon
          points={`${(0.5 / days) * W},${H} ${pts(cur.daily_expense)} ${((last - 0.5) / days) * W},${H}`}
          fill="url(#spark-glow)"
        />
      )}
      {avg && <polyline points={pts(avg.daily_expense)} className="spark-avg" />}
      <polyline points={pts(prev.daily_expense)} className="spark-prev" />
      <polyline points={pts(cur.daily_expense)} className="spark-cur" />
      <circle cx={((last - 0.5) / days) * W} cy={lastY} r="3.5" className="spark-dot" />
    </svg>
  );
}

/**
 * How this month is running against last month (and the multi-month average) at the
 * same day: comparison chips, the cumulative-spend spark and its legend. Rendered
 * inside the dark `wallet-card` hero.
 */
export function PaceTrend({ pace }: { pace: Pace }) {
  const { current: cur, previous: prev } = pace;
  const prevName = monthName(prev.month);
  const spendPct = change(cur.expense, prev.expense);
  const spentLess = spendPct != null && spendPct < 0;
  const avg = pace.average ?? null;
  const avgPct = avg ? change(cur.expense, avg.expense) : null;

  return (
    <>
      <div className="wallet-chips">
        {spendPct != null && (
          <div className={`wallet-chip ${spentLess ? "chip-good" : "chip-bad"}`}>
            {spentLess ? "▼" : "▲"} הוצאת {fmtPct(Math.abs(spendPct))}{" "}
            {spentLess ? "פחות" : "יותר"} מ{prevName} באותה נקודה
          </div>
        )}
        {avgPct != null && (
          <div className={`wallet-chip ${avgPct < 0 ? "chip-good" : "chip-bad"}`}>
            {avgPct < 0 ? "▼" : "▲"} {fmtPct(Math.abs(avgPct))} {avgPct < 0 ? "מתחת" : "מעל"} לממוצע{" "}
            {avg!.months} החודשים האחרונים
          </div>
        )}
      </div>

      <PaceSpark cur={cur} prev={prev} avg={avg} />
      <div className="wallet-legend">
        <span><i className="lg-cur" /> {monthName(cur.month)}</span>
        <span><i className="lg-prev" /> {prevName} {shekel(prev.month_expense)}</span>
        {avg && <span><i className="lg-avg" /> ממוצע {shekel(avg.month_expense)}</span>}
      </div>
    </>
  );
}
