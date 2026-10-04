import { Card, Kpi, PageTitle, StubNotice } from "@/components/common";
import { shekel, snapshot } from "@/lib/data";

const KIND_LABEL: Record<string, string> = {
  pension: "קרן פנסיה",
  study_fund: "קרן השתלמות",
  savings: "חיסכון",
};

export default function Portfolio() {
  const savings = snapshot.savings ?? [];
  const total = snapshot.totals.long_term_savings ?? 0;

  if (savings.length === 0) {
    return (
      <div>
        <PageTitle>השקעות</PageTitle>
        <StubNotice status="חסום · דורש מקור נתונים חדש">
          לא נמצאו נתוני חיסכון. הריצו <code>/harel-refresh</code> ואז{" "}
          <code>python3 data/digest.py</code>.
        </StubNotice>
      </div>
    );
  }

  return (
    <div>
      <PageTitle>השקעות</PageTitle>

      <div className="grid grid-2">
        <Kpi label="סך חיסכון ארוך טווח" value={shekel(total)} />
        <Kpi label="מספר פוליסות" value={String(
          savings.reduce((n, s) => n + (s.policies_count ?? 0), 0))} />
      </div>

      <Card className="section-gap">
        <div className="card-title">החזקות</div>
        {savings.map((s) => (
          <div key={`${s.institution}-${s.kind}-${s.label}`} className="row">
            <span>
              {s.label}
              <span className="muted">
                {" · "}{KIND_LABEL[s.kind] ?? s.kind}
                {s.policies_count ? ` · ${s.policies_count} פוליסות` : ""}
              </span>
            </span>
            <strong style={{ color: "var(--lg-good)" }}>{shekel(s.balance)}</strong>
          </div>
        ))}
        <div className="row">
          <span><strong>סה"כ</strong></span>
          <strong style={{ color: "var(--lg-good)" }}>{shekel(total)}</strong>
        </div>
      </Card>

      <StubNotice status="חלקי · חסר פירוט ברמת פוליסה">
        דמי ניהול, תשואה ומסלול השקעה אינם נאספים — הם מוצגים בהראל דרך דוח
        SharePoint ולא דרך ה-API. כמו כן {savings.find((s) => s.kind === "study_fund")
          ?.policies_count ?? 0} קרנות ההשתלמות מוצגות כסכום אחד ולא בנפרד.
        נדל"ן ותיקי השקעות חיצוניים עדיין לא נאספים.
      </StubNotice>
    </div>
  );
}
