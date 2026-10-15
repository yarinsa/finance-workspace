import { Link } from "react-router-dom";
import { cashflow, pct as fmtPct, shekel, shekelSigned, snapshot, type PaceSide } from "@/lib/data";

const monthName = (ym: string) =>
  new Intl.DateTimeFormat("he-IL", { month: "long" }).format(new Date(`${ym}-01T12:00:00`));

/** Percent change, or null when the base is too small to be meaningful. */
function change(now: number, before: number): number | null {
  if (Math.abs(before) < 1) return null;
  return ((now - before) / Math.abs(before)) * 100;
}

/** Cumulative spend this month (solid) over last month's full curve (dashed). */
function PaceSpark({ cur, prev }: { cur: PaceSide; prev: PaceSide }) {
  const W = 300;
  const H = 64;
  const days = Math.max(prev.daily_expense.length, 28);
  const max = Math.max(prev.month_expense, ...cur.daily_expense, 1);
  const pts = (arr: number[]) =>
    arr.map((v, i) => `${((i + 0.5) / days) * W},${H - 4 - (v / max) * (H - 8)}`).join(" ");
  const last = cur.daily_expense.length;
  const lastY = H - 4 - ((cur.daily_expense[last - 1] ?? 0) / max) * (H - 8);
  return (
    <svg className="wallet-spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden>
      <defs>
        <linearGradient id="spark-glow" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" style={{ stopColor: "var(--hero-accent)", stopOpacity: 0.35 }} />
          <stop offset="100%" style={{ stopColor: "var(--hero-accent)", stopOpacity: 0 }} />
        </linearGradient>
      </defs>
      {last > 0 && (
        <polygon
          points={`${(0.5 / days) * W},${H} ${pts(cur.daily_expense)} ${((last - 0.5) / days) * W},${H}`}
          fill="url(#spark-glow)"
        />
      )}
      <polyline points={pts(prev.daily_expense)} className="spark-prev" />
      <polyline points={pts(cur.daily_expense)} className="spark-cur" />
      <circle cx={((last - 0.5) / days) * W} cy={lastY} r="3.5" className="spark-dot" />
    </svg>
  );
}

/**
 * Change vs. last month, as a percent — or as a signed ₪ amount when `money`
 * is set (net can sit near or cross zero, where a percent like "2,133%" is noise).
 */
function Delta({ now, before, goodWhenUp, money = false }: {
  now: number; before: number; goodWhenUp: boolean; money?: boolean;
}) {
  const diff = now - before;
  const pct = change(now, before);
  if (!money && pct == null) return <span className="delta muted">—</span>;
  const up = diff >= 0;
  const good = up === goodWhenUp;
  return (
    <span className={`delta ${good ? "delta-good" : "delta-bad"}`}>
      {up ? "▲" : "▼"} {money ? shekelSigned(diff) : fmtPct(Math.abs(pct!))}
    </span>
  );
}

/**
 * One month-to-date figure against the month's expectation. The bar fills to
 * actual/expected; the tick marks how much of the month has passed, so a bar
 * past the tick means income arrived early — or spending is running ahead.
 * Net has no meaningful "fill" (it can be negative), so it shows the target only.
 */
function Stat({ label, now, before, expected, monthDone, goodWhenUp, money = false }: {
  label: string;
  now: number;
  before: number;
  expected?: number;
  monthDone: number;
  goodWhenUp: boolean;
  money?: boolean;
}) {
  const ratio = expected && expected > 0 ? now / expected : null;
  const ahead = ratio != null && ratio > monthDone;
  const barCls = ratio == null ? "" : ahead === goodWhenUp ? "fill-good" : "fill-warn";
  return (
    <div className="wstat">
      <div className="wstat-line">
        <span className="wstat-label">{label}</span>
        <strong style={money ? { color: now >= 0 ? "var(--good)" : "var(--bad)" } : undefined}>{shekel(now)}</strong>
      </div>
      {ratio != null && !money && (
        <div className="wstat-bar" aria-label={`${fmtPct(ratio * 100)} מהצפי`}>
          <div className={`wstat-fill ${barCls}`} style={{ width: `${Math.min(ratio, 1) * 100}%` }} />
          <div className="wstat-tick" style={{ insetInlineStart: `${monthDone * 100}%` }} />
        </div>
      )}
      <div className="wstat-line wstat-meta">
        <span>
          {expected != null &&
            (money
              ? `צפי לסוף החודש ${shekel(expected)}`
              : `${fmtPct((ratio ?? 0) * 100)} מתוך ${shekel(expected)} צפויים`)}
        </span>
        <Delta now={now} before={before} goodWhenUp={goodWhenUp} money={money} />
      </div>
    </div>
  );
}

/**
 * E-wallet style header: what's actually free right now, and whether this month
 * is running ahead of or behind last month at the same point.
 */
export default function WalletHero() {
  const pace = cashflow.pace;
  const t = snapshot.totals;
  const free = t.bank_balances_sum - t.credit_card_debt;

  if (!pace) return null;
  const { current: cur, previous: prev, as_of_day } = pace;
  const exp = pace.expected ?? null;
  const monthDone = as_of_day / (pace.days_in_month || 30);
  const prevName = monthName(prev.month);
  const spendPct = change(cur.expense, prev.expense);
  const spentLess = spendPct != null && spendPct < 0;

  return (
    <section className="wallet">
      <Link to="/cashflow" className="wallet-card">
        <div className="wallet-top">
          <span className="wallet-label">פנוי אחרי חיובי אשראי</span>
          <span className="wallet-asof">נכון ל-{as_of_day} ב{monthName(cur.month)}</span>
        </div>
        <div className="wallet-balance">{shekel(free)}</div>
        <div className="wallet-sub">
          עו״ש {shekel(t.bank_balances_sum)} · אשראי לחיוב {shekel(t.credit_card_debt)}
        </div>

        {spendPct != null && (
          <div className={`wallet-chip ${spentLess ? "chip-good" : "chip-bad"}`}>
            {spentLess ? "▼" : "▲"} הוצאת {fmtPct(Math.abs(spendPct))}{" "}
            {spentLess ? "פחות" : "יותר"} מ{prevName} באותה נקודה
          </div>
        )}

        <PaceSpark cur={cur} prev={prev} />
        <div className="wallet-legend">
          <span><i className="lg-cur" /> {monthName(cur.month)}</span>
          <span><i className="lg-prev" /> {prevName} · סה״כ {shekel(prev.month_expense)}</span>
        </div>
      </Link>

      <div className="wallet-stats card">
        <div className="wallet-stats-title">
          <span>החודש מול הצפי</span>
          {exp && <span className="muted">{fmtPct(monthDone * 100)} מהחודש עבר</span>}
        </div>
        <Stat label="הכנסות" now={cur.income} before={prev.income} expected={exp?.income} monthDone={monthDone} goodWhenUp />
        <Stat label="הוצאות" now={cur.expense} before={prev.expense} expected={exp?.expense} monthDone={monthDone} goodWhenUp={false} />
        <Stat label="תזרים" now={cur.net} before={prev.net} expected={exp?.net} monthDone={monthDone} goodWhenUp money />
      </div>
      <div className="wallet-foot muted">
        ▲▼ מול 1–{as_of_day} ב{prevName} · הקו האנכי בפס = היום
      </div>
    </section>
  );
}
