import { ListRow } from "@/components/common";
import { monthYear, num, pct, shekel, type Loan } from "@/lib/data";
import { groupTracks, isoDate, rateOf } from "@/lib/loans";

/**
 * A group of loans at a glance (the home's הלוואות and משכנתא cards, under their total):
 * balance-weighted effective rate, monthly payment, payoff date, the fixed/variable/linked
 * mix, then each track with its rate and a bar of how much of it is paid off.
 */
export default function LoanDetails({ loans }: { loans: Loan[] }) {
  const live = loans.filter((l) => (l.balance ?? 0) > 0);
  const balance = live.reduce((n, l) => n + (l.balance ?? 0), 0);
  if (!balance) return null;
  const tracks = groupTracks(live);
  const share = (f: (l: Loan) => boolean) => live.filter(f).reduce((n, l) => n + (l.balance ?? 0), 0) / balance;
  const rated = live.filter((l) => l.rate_pct != null);
  const ratedBal = rated.reduce((n, l) => n + (l.balance ?? 0), 0);
  const avgRate = ratedBal ? rated.reduce((n, l) => n + (l.balance ?? 0) * rateOf(l), 0) / ratedBal : 0;
  const monthly = live.reduce((n, l) => n + (l.monthly_payment ?? 0), 0);
  const last = live.reduce<Loan | null>((m, l) => (isoDate(l.final_date) > isoDate(m?.final_date) ? l : m), null);
  const remaining = last?.payments_remaining ?? 0;
  const fixed = share((l) => l.rate_type === "fixed" && l.rate_pct != null);
  const variable = 1 - fixed;
  const linked = share((l) => !!l.index_linked);

  return (
    <>
      <div className="mini-stats">
        <div>
          <span>ריבית ממוצעת</span>
          <strong>{pct(avgRate, 2)}</strong>
        </div>
        <div>
          <span>החזר חודשי</span>
          <strong>{shekel(monthly)}</strong>
        </div>
        <div>
          <span>סיום</span>
          <strong>{last?.final_date ? monthYear(isoDate(last.final_date)) : "—"}</strong>
          {remaining > 0 && <em>{num(remaining)} תשלומים · ~{num(Math.round(remaining / 12))} שנים</em>}
        </div>
      </div>

      <div className="mix">
        <div className="mix-bar">
          <span className="mix-fixed" style={{ flexBasis: `${fixed * 100}%` }} />
          <span className="mix-var" style={{ flexBasis: `${variable * 100}%` }} />
        </div>
        <div className="mix-legend">
          <span><i className="mix-fixed" /> קבועה {pct(fixed * 100)}</span>
          <span><i className="mix-var" /> משתנה {pct(variable * 100)}</span>
          {linked > 0 && <span className="muted">צמוד מדד {pct(linked * 100)}</span>}
        </div>
      </div>

      {tracks.map((g) => {
        const paid = g.paidBal ? g.paidW / g.paidBal : null;
        return (
          <ListRow
            key={g.label}
            label={
              <>
                {g.label}
                {g.rated && <span className="rate-chip">{pct(g.balance ? g.rateW / g.balance : 0, 2)}</span>}
              </>
            }
            sub={
              g.monthly
                ? [
                    `${shekel(g.monthly)} לחודש`,
                    g.count > 1 && `${num(g.count)} מסלולים`,
                    g.end && `עד ${monthYear(g.end)}`,
                    paid != null && `שולם ${pct(paid * 100)}`,
                  ]
                    .filter(Boolean)
                    .join(" · ")
                : "הבנק מדווח רק את היתרה"
            }
            value={shekel(g.balance)}
            share={paid ?? undefined}
          />
        );
      })}
    </>
  );
}
