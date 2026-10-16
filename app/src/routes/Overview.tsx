import { useState } from "react";
import { BigNumber, Card, CardLabel, Kpi, KpiGrid, ListRow, Nudge, Section } from "@/components/common";
import NetWorthChart from "@/components/NetWorthChart";
import RunwayTeaser from "@/components/RunwayTeaser";
import BudgetsTeaser from "@/components/BudgetsTeaser";
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

/** Mint-style hero: toggles between net worth and this month's spending vs. last month. */
function Hero({ netToday }: { netToday: number | null }) {
  const [view, setView] = useState<"net" | "spend">("net");
  const pace = cashflow.pace;
  const net = snapshot.totals.net_position_with_savings ?? netToday;
  const spend = pace?.current.expense ?? null;
  const prev = pace?.previous.expense ?? null;
  const diff = spend != null && prev != null ? spend - prev : null;
  return (
    <Card>
      <div className="mb-3 inline-flex rounded-full bg-panel-2 p-0.5 text-sm font-semibold" role="tablist">
        {([["net", "שווי נקי"], ["spend", "הוצאות"]] as const).map(([k, l]) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={view === k}
            onClick={() => setView(k)}
            className={`rounded-full px-4 py-1 ${view === k ? "bg-background shadow-sm" : "text-muted-foreground"}`}
          >
            {l}
          </button>
        ))}
      </div>
      {view === "net" ? (
        <>
          <BigNumber tone={net != null && net < 0 ? "bad" : undefined}>{net != null ? shekel(net) : "—"}</BigNumber>
          <div className="mt-1 text-sm text-muted-foreground">כולל חסכונות</div>
        </>
      ) : (
        <>
          <BigNumber>{spend != null ? shekel(spend) : "—"}</BigNumber>
          {diff != null && (
            <div className="mt-1 text-sm text-muted-foreground">
              {shekel(Math.abs(diff))} {diff <= 0 ? "פחות" : "יותר"} מאותה נקודה בחודש שעבר
            </div>
          )}
        </>
      )}
    </Card>
  );
}

/** Cash / credit cards / loans — the three account-type cards. */
function AccountTypes() {
  const t = snapshot.totals;
  const items = [
    { label: "מזומן", value: t.bank_balances_sum, to: "/runway", bad: t.bank_balances_sum < 0 },
    { label: "כרטיסי אשראי", value: -t.credit_card_debt, to: "/cashflow", bad: false },
    { label: "הלוואות ומשכנתא", value: -(t.mortgage_balance + t.consumer_loan_balance), to: "/networth", bad: false },
  ];
  return (
    <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
      {items.map((i) => (
        <Card key={i.label} to={i.to}>
          <CardLabel>{i.label}</CardLabel>
          <div className={`text-[22px] font-extrabold tabular-nums ${i.bad ? "text-bad" : ""}`}>{shekel(i.value)}</div>
        </Card>
      ))}
    </div>
  );
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

      <Hero netToday={netToday} />
      <AccountTypes />

      {cashflow.runway && <RunwayTeaser runway={cashflow.runway} />}
      {cashflow.budgets && <BudgetsTeaser budgets={cashflow.budgets} />}

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
