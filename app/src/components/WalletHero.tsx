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
 * E-wallet style header: what's actually free right now, and whether this month
 * is running ahead of or behind last month at the same point.
 */
export default function WalletHero() {
  const pace = cashflow.pace;
  const t = snapshot.totals;
  const free = t.bank_balances_sum - t.credit_card_debt;

  if (!pace) return null;
  const { current: cur, previous: prev, as_of_day } = pace;
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

      <div className="wallet-stats">
        <div className="wstat">
          <span className="wstat-label">הכנסות</span>
          <strong>{shekel(cur.income)}</strong>
          <Delta now={cur.income} before={prev.income} goodWhenUp />
        </div>
        <div className="wstat">
          <span className="wstat-label">הוצאות</span>
          <strong>{shekel(cur.expense)}</strong>
          <Delta now={cur.expense} before={prev.expense} goodWhenUp={false} />
        </div>
        <div className="wstat">
          <span className="wstat-label">תזרים</span>
          <strong style={{ color: cur.net >= 0 ? "var(--good)" : "var(--bad)" }}>{shekel(cur.net)}</strong>
          <Delta now={cur.net} before={prev.net} goodWhenUp money />
        </div>
      </div>
      <div className="wallet-foot muted">השוואה ל-1–{as_of_day} ב{prevName}</div>
    </section>
  );
}
