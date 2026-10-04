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
  const savings = snapshot.savings ?? [];
  const assets: [string, number][] = [
    ["יתרות עו\"ש", t.bank_balances_sum],
    ...savings.map((s) => [s.label, s.balance] as [string, number]),
  ];

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
          {savings.length > 0 && (
            <div className="row">
              <span><strong>סך נכסים</strong></span>
              <strong>{shekel(t.bank_balances_sum + (t.long_term_savings ?? 0))}</strong>
            </div>
          )}
          <p className="muted section-gap">
            {savings.length > 0
              ? 'תיקי השקעות חיצוניים ונדל"ן עדיין לא נאספים — השווי הנקי עדיין מוערך בחסר.'
              : 'פנסיה / השתלמות / תיקים / נדל"ן עדיין לא נאספים — השווי הנקי מוערך בחסר.'}
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
          <span>
            מצב נטו נזיל (עו"ש − חוב)
            <span className="muted"> · ללא חיסכון ארוך טווח</span>
          </span>
          <strong style={{ color: t.tracked_net_position >= 0 ? "var(--good)" : "var(--bad)" }}>
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
                color: t.net_position_with_savings >= 0 ? "var(--good)" : "var(--bad)",
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
    </div>
  );
}
