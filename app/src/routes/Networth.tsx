import { Card, CardLabel, Page } from "@/components/common";
import NetWorthChart from "@/components/NetWorthChart";
import Hero from "@/components/home/Hero";
import { cashflow, shekel, snapshot } from "@/lib/data";

export default function Networth() {
  const t = snapshot.totals;

  return (
    <Page title="שווי נקי" wide>
      <Hero netToday={cashflow.projection?.net_worth_today ?? null} />

      <Card>
        <CardLabel>השווי הנקי לאורך החיים</CardLabel>
        <NetWorthChart height={280} showLoans />
      </Card>

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
