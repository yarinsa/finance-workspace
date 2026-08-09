import { Card, PageTitle } from "@/components/ui";
import NetWorthChart from "@/components/NetWorthChart";
import { shekel, snapshot } from "@/lib/data";

export default function Networth() {
  const t = snapshot.totals;
  const liabilities: [string, number][] = [
    ["משכנתא", t.mortgage_balance],
    ['הלוואות צרכניות', t.consumer_loan_balance],
    ["חוב כרטיסי אשראי", t.credit_card_debt],
  ];
  const assets: [string, number][] = [["יתרות עו\"ש", t.bank_balances_sum]];

  return (
    <div>
      <PageTitle>שווי נקי</PageTitle>

      <Card>
        <div className="card-title">השווי הנקי לאורך החיים</div>
        <NetWorthChart height={300} />
      </Card>

      <div className="grid grid-2 section-gap">
        <Card>
          <div className="card-title">נכסים נמדדים</div>
          {assets.map(([k, v]) => (
            <div key={k} className="row">
              <span>{k}</span>
              <strong>{shekel(v)}</strong>
            </div>
          ))}
          <p className="muted section-gap">
            פנסיה / השתלמות / תיקים / נדל"ן עדיין לא נאספים — השווי הנקי מוערך בחסר.
          </p>
        </Card>
        <Card>
          <div className="card-title">התחייבויות</div>
          {liabilities.map(([k, v]) => (
            <div key={k} className="row">
              <span>{k}</span>
              <strong style={{ color: "var(--bad)" }}>{shekel(v)}</strong>
            </div>
          ))}
          <div className="row">
            <span>סך חוב</span>
            <strong style={{ color: "var(--bad)" }}>{shekel(t.total_debt)}</strong>
          </div>
        </Card>
      </div>

      <Card className="section-gap">
        <div className="row">
          <span>מצב נטו נמדד (נכסים נמדדים − חוב)</span>
          <strong style={{ color: t.tracked_net_position >= 0 ? "var(--good)" : "var(--bad)" }}>
            {shekel(t.tracked_net_position)}
          </strong>
        </div>
        <div className="row">
          <span>שירות חוב חודשי</span>
          <strong>{shekel(t.monthly_loan_service)}</strong>
        </div>
      </Card>
    </div>
  );
}
