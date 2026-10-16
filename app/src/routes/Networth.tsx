import { Card, CardLabel, Page } from "@/components/common";
import NetWorthChart from "@/components/NetWorthChart";
import Hero from "@/components/home/Hero";
import MortgageCard from "@/components/MortgageCard";
import { cashflow, pct, shekel, snapshot } from "@/lib/data";

export default function Networth() {
  const t = snapshot.totals;
  const liabilities: [string, number][] = [
    ["משכנתא", t.mortgage_balance],
    ['הלוואות צרכניות', t.consumer_loan_balance],
    ["חוב כרטיסי אשראי", t.credit_card_debt],
  ];
  const allLoans = snapshot.debt_profile?.all_loans ?? null;
  const savings = snapshot.savings ?? [];
  const assets: [string, number][] = [
    ["יתרות עו\"ש", t.bank_balances_sum],
    ...savings.map((s) => [s.label, s.balance] as [string, number]),
  ];

  return (
    <Page title="שווי נקי" wide>
      <Hero netToday={cashflow.projection?.net_worth_today ?? null} />

      <Card>
        <CardLabel>השווי הנקי לאורך החיים</CardLabel>
        <NetWorthChart height={280} showLoans />
      </Card>

      <div className="grid grid-2">
        <Card>
          <CardLabel>נכסים נמדדים</CardLabel>
          {assets.map(([k, v]) => (
            <div key={k} className="row">
              <span>{k}</span>
              <strong>{shekel(v)}</strong>
            </div>
          ))}
          {savings.length > 0 && (
            <div className="row">
              <span><strong>סך נכסים</strong></span>
              <strong>{shekel(t.bank_balances_sum + (t.long_term_savings ?? 0))}</strong>
            </div>
          )}
          <p className="muted mt-3">
            {savings.length > 0
              ? 'תיקי השקעות חיצוניים ונדל"ן עדיין לא נאספים — השווי הנקי עדיין מוערך בחסר.'
              : 'פנסיה / השתלמות / תיקים / נדל"ן עדיין לא נאספים — השווי הנקי מוערך בחסר.'}
          </p>
        </Card>
        <Card>
          <CardLabel>התחייבויות</CardLabel>
          {liabilities.map(([k, v]) => (
            <div key={k} className="row">
              <span>{k}</span>
              <strong style={{ color: "var(--lg-bad)" }}>{shekel(v)}</strong>
            </div>
          ))}
          <div className="row">
            <span>סך חוב</span>
            <strong style={{ color: "var(--lg-bad)" }}>{shekel(t.total_debt)}</strong>
          </div>
          {allLoans && (
            <div className="row">
              <span title="ממוצע משוקלל לפי יתרה, ריבית נומינלית כפי שהבנקים מדווחים">
                ריבית ממוצעת על הלוואות
              </span>
              <strong>{pct(allLoans.avg_rate_pct, 2)}</strong>
            </div>
          )}
        </Card>
      </div>

      <MortgageCard />

      <Card>
        <div className="row">
          <span>
            מצב נטו נזיל (עו"ש − חוב)
            <span className="muted"> · ללא חיסכון ארוך טווח</span>
          </span>
          <strong style={{ color: t.tracked_net_position >= 0 ? "var(--lg-good)" : "var(--lg-bad)" }}>
            {shekel(t.tracked_net_position)}
          </strong>
        </div>
        {t.net_position_with_savings !== undefined && (
          <div className="row">
            <span>
              מצב נטו כולל חיסכון
              <span className="muted"> · כולל פנסיה והשתלמות</span>
            </span>
            <strong
              style={{
                color: t.net_position_with_savings >= 0 ? "var(--lg-good)" : "var(--lg-bad)",
              }}
            >
              {shekel(t.net_position_with_savings)}
            </strong>
          </div>
        )}
        <div className="row">
          <span>שירות חוב חודשי</span>
          <strong>{shekel(t.monthly_loan_service)}</strong>
        </div>
      </Card>
    </Page>
  );
}
