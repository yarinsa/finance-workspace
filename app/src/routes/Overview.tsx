import { BigNumber, Card, CardLabel, Kpi, KpiGrid, ListRow, Nudge, Section } from "@/components/common";
import NetWorthChart from "@/components/NetWorthChart";
import RunwayTeaser from "@/components/RunwayTeaser";
import WalletHero from "@/components/WalletHero";
import MortgageCard from "@/components/MortgageCard";
import SpendingDonut from "@/components/SpendingDonut";
import { cashflow, daysSince, formatMetric, formatMetricCompact, num, pct, shekel, snapshot, type Savings } from "@/lib/data";

const KIND_LABEL: Record<Savings["kind"], string> = {
  pension: "קרן פנסיה",
  study_fund: "קרנות השתלמות",
  provident_fund: "קופות גמל",
  savings: "חיסכון",
  bank_deposit: "פיקדון נזיל",
};

function greeting(hour: number): string {
  if (hour < 5) return "לילה טוב";
  if (hour < 12) return "בוקר טוב";
  if (hour < 17) return "צהריים טובים";
  if (hour < 21) return "ערב טוב";
  return "לילה טוב";
}

/** Long-term savings folded by vehicle kind, largest first. */
function savingsByKind(savings: Savings[]) {
  const groups = new Map<Savings["kind"], { label: string; balance: number; count: number; liquid: boolean }>();
  for (const s of savings) {
    const g = groups.get(s.kind) ?? { label: KIND_LABEL[s.kind] ?? s.label, balance: 0, count: 0, liquid: !!s.liquid };
    g.balance += s.balance;
    g.count += 1;
    groups.set(s.kind, g);
  }
  return [...groups.values()].sort((a, b) => b.balance - a.balance);
}

export default function Overview() {
  const { metrics, projection } = cashflow;
  const t = snapshot.totals;
  const netToday = projection?.net_worth_today ?? null;
  const netRetire = projection?.net_worth_at_retirement ?? null;
  const age = daysSince(cashflow.generated_at);

  const savings = savingsByKind(snapshot.savings ?? []);
  const savingsTotal = savings.reduce((a, g) => a + g.balance, 0);

  const allLoans = snapshot.debt_profile?.all_loans ?? null;
  const debts = [
    { label: "משכנתא", value: t.mortgage_balance },
    { label: "הלוואות", value: t.consumer_loan_balance },
    { label: "כרטיסי אשראי", sub: "לחיוב הקרוב", value: t.credit_card_debt },
  ].filter((d) => d.value > 0);

  // Already shown in a section above — keep the metrics grid to what's left.
  const shown = new Set(["net_cashflow", "income", "expense", "net_worth", "net_worth_at_retirement"]);
  const healthMetrics = metrics.filter((m) => !shown.has(m.key)).slice(0, 4);

  return (
    <div className="feed">
      {age > 7 && (
        <Nudge action="לעדכון יתרות ▸">
          🕑 הגיע זמן לעדכן את היתרות שלך — הנתונים מלפני {num(age)} ימים.
        </Nudge>
      )}

      <header className="greeting">
        <h1>{greeting(new Date().getHours())} 👋</h1>
        <p className="muted">הכסף שלך, ברור יותר כל יום</p>
      </header>

      {cashflow.runway && <RunwayTeaser runway={cashflow.runway} />}

      <Section title="תזרים" to="/cashflow">
        <WalletHero />
      </Section>

      <Section title="הוצאות לפי קטגוריה" to="/cashflow">
        <Card>
          <SpendingDonut />
        </Card>
      </Section>

      {savings.length > 0 && (
        <Section title="חסכונות" to="/portfolio">
          <Card>
            <CardLabel>סה״כ חסכונות</CardLabel>
            <BigNumber>{shekel(savingsTotal)}</BigNumber>
            {savings.map((g) => (
              <ListRow
                key={g.label}
                label={g.label}
                sub={[g.count > 1 ? `${num(g.count)} קופות` : null, g.liquid ? "נזיל" : null]
                  .filter(Boolean)
                  .join(" · ") || undefined}
                value={shekel(g.balance)}
                share={g.balance / savingsTotal}
              />
            ))}
          </Card>
        </Section>
      )}

      <Section title="חובות" to="/networth">
        <Card>
          <CardLabel>סה״כ חובות</CardLabel>
          <BigNumber>{shekel(t.total_debt)}</BigNumber>
          {debts.map((d) => (
            <ListRow
              key={d.label}
              label={d.label}
              sub={d.sub}
              value={shekel(d.value)}
              share={d.value / t.total_debt}
            />
          ))}
          <div className="list-foot">
            <span className="muted">החזר חודשי</span>
            <strong>{shekel(t.monthly_loan_service)}</strong>
          </div>
          {allLoans && (
            <div className="list-foot no-rule">
              <span className="muted" title="ממוצע משוקלל לפי יתרה, ריבית נומינלית כפי שהבנקים מדווחים">
                ריבית ממוצעת על הלוואות
              </span>
              <strong>{pct(allLoans.avg_rate_pct, 2)}</strong>
            </div>
          )}
        </Card>
      </Section>

      {snapshot.debt_profile?.mortgage && (
        <Section title="משכנתא" to="/networth">
          <MortgageCard />
        </Section>
      )}

      <Section title="שווי נקי" to="/networth">
        <Card>
          <CardLabel>שווי נקי נוכחי</CardLabel>
          <BigNumber>{netToday != null ? shekel(netToday) : "—"}</BigNumber>
          {t.net_position_with_savings != null && (
            <div className="muted">כולל חסכונות: {shekel(t.net_position_with_savings)}</div>
          )}
          <NetWorthChart height={180} />
          {netRetire != null && (
            <div className="muted">בפרישה צפוי שווי נקי של כ-{shekel(netRetire)}</div>
          )}
        </Card>
      </Section>

      <Section title="מדדים" to="/metrics">
        <KpiGrid cols={4}>
          {healthMetrics.map((m) => (
            <Card key={m.key} to="/metrics">
              <Kpi
                label={m.name}
                value={formatMetric(m.value, m.units)}
                compactValue={formatMetricCompact(m.value, m.units)}
                rank={m.rank}
                hint={m.description}
              />
            </Card>
          ))}
        </KpiGrid>
      </Section>
    </div>
  );
}
