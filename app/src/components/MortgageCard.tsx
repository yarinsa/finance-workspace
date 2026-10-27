import { BigNumber, Card, CardLabel, ListRow } from "@/components/common";
import { monthYear, num, pct, shekel, snapshot, type Loan } from "@/lib/data";

/** Treat Discount's 0.0001% placeholder (subsidised מתווה tracks) as zero. */
const rateOf = (l: Loan) => ((l.rate_pct ?? 0) < 0.01 ? 0 : l.rate_pct ?? 0);

/** A short, human track name from its terms — bank names are long and inconsistent. */
function trackLabel(l: Loan): string {
  if ((l.name ?? "").includes("מתווה")) return "מסלול מתווה";
  const linkage = l.index_linked ? "צמוד מדד" : "לא צמוד";
  const kind = l.rate_type === "fixed" ? "קבועה" : "משתנה";
  return `${linkage} · ${kind}`;
}

/** Tracks with the same label folded together (the three מתווה tranches → one row). */
function groupTracks(loans: Loan[]) {
  const groups = new Map<string, { label: string; balance: number; monthly: number; rateW: number; count: number; end: string }>();
  for (const l of loans) {
    const label = trackLabel(l);
    const g = groups.get(label) ?? { label, balance: 0, monthly: 0, rateW: 0, count: 0, end: "" };
    const bal = l.balance ?? 0;
    g.balance += bal;
    g.monthly += l.monthly_payment ?? 0;
    g.rateW += bal * rateOf(l);
    g.count += 1;
    const end = String(l.final_date ?? "").replace(/^(\d{4})(\d{2})(\d{2})$/, "$1-$2-$3");
    if (end > g.end) g.end = end;
    groups.set(label, g);
  }
  return [...groups.values()].sort((a, b) => b.balance - a.balance);
}

/**
 * The mortgage at a glance: balance, balance-weighted average interest, monthly
 * installment, payoff date, the fixed/variable/linked mix, and each track.
 */
export default function MortgageCard() {
  const profile = snapshot.debt_profile?.mortgage;
  if (!profile) return null;
  return (
    <Card>
      <CardLabel>יתרת משכנתא</CardLabel>
      <BigNumber>{shekel(profile.balance)}</BigNumber>
      <MortgageDetails />
    </Card>
  );
}

/** Everything under the balance: the three stats, the rate mix and the tracks. Also the
 *  body of the home's משכנתא card, whose header already shows the balance. */
export function MortgageDetails() {
  const profile = snapshot.debt_profile?.mortgage;
  if (!profile) return null;
  const tracks = groupTracks(snapshot.loans.filter((l) => l.category === "mortgage" && (l.balance ?? 0) > 0));
  const mix = profile.rate_mix;
  const years = Math.round(profile.payments_remaining / 12);

  return (
    <>
      <div className="mini-stats">
        <div>
          <span>ריבית ממוצעת</span>
          <strong>{pct(profile.avg_rate_pct, 2)}</strong>
        </div>
        <div>
          <span>החזר חודשי</span>
          <strong>{shekel(profile.monthly_payment)}</strong>
        </div>
        <div>
          <span>סיום</span>
          <strong>{profile.final_date ? monthYear(profile.final_date) : "—"}</strong>
          <em>{num(profile.payments_remaining)} תשלומים · ~{num(years)} שנים</em>
        </div>
      </div>

      <div className="mix">
        <div className="mix-bar">
          <span className="mix-fixed" style={{ flexBasis: `${mix.fixed * 100}%` }} />
          <span className="mix-var" style={{ flexBasis: `${mix.variable * 100}%` }} />
        </div>
        <div className="mix-legend">
          <span><i className="mix-fixed" /> קבועה {pct(mix.fixed * 100)}</span>
          <span><i className="mix-var" /> משתנה {pct(mix.variable * 100)}</span>
          {mix.index_linked > 0 && <span className="muted">צמוד מדד {pct(mix.index_linked * 100)}</span>}
        </div>
      </div>

      {tracks.map((g) => (
        <ListRow
          key={g.label}
          label={
            <>
              {g.label}
              <span className="rate-chip">{pct(g.balance ? g.rateW / g.balance : 0, 2)}</span>
            </>
          }
          sub={`${shekel(g.monthly)} לחודש${g.count > 1 ? ` · ${num(g.count)} מסלולים` : ""}${
            g.end ? ` · עד ${monthYear(g.end)}` : ""
          }`}
          value={shekel(g.balance)}
          share={g.balance / profile.balance}
        />
      ))}
    </>
  );
}
