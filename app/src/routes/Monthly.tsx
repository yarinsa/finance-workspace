import { BarRow, Card, CardLabel, PageTitle, Section } from "@/components/common";
import BillsCard from "@/components/BillsCard";
import FixedExpenses from "@/components/FixedExpenses";
import BudgetsTeaser from "@/components/BudgetsTeaser";
import WalletHero from "@/components/WalletHero";
import GroupLinks from "@/components/GroupLinks";
import { cashflow, monthYear, shekel } from "@/lib/data";

/** Compact month-spending summary from cashflow.spending (full explorer lives at /spending). */
function SpendingSummary() {
  const m = cashflow.spending?.months?.[0];
  if (!m) return null;
  const top = m.by_category.slice(0, 4);
  const max = top[0]?.amount || 1;
  const delta = m.vs_prev;
  return (
    <Card to="/spending">
      <CardLabel>הוצאות {monthYear(`${m.month}-01`)}</CardLabel>
      <div className="text-[28px] leading-tight font-extrabold tabular-nums">{shekel(m.total)}</div>
      {delta != null && delta !== 0 && (
        <div className="mt-1 text-sm text-muted-foreground">
          {shekel(Math.abs(delta))} {delta < 0 ? "פחות" : "יותר"} מהחודש הקודם{m.partial ? " (עד כה)" : ""}
        </div>
      )}
      <div className="mt-3 space-y-2">
        {top.map((c) => (
          <BarRow key={c.name} label={c.name} value={shekel(c.amount)} fraction={c.amount / max} />
        ))}
      </div>
    </Card>
  );
}

/** Mint "Monthly": budgets, bills & subscriptions and month spending in one scroll. */
export default function Monthly() {
  return (
    <div className="feed">
      <PageTitle>החודש</PageTitle>
      <WalletHero />
      {cashflow.budgets && (
        <Section title="תקציב" to="/budgets">
          <BudgetsTeaser budgets={cashflow.budgets} />
        </Section>
      )}
      <BillsCard />
      <FixedExpenses />
      <Section title="הוצאות" to="/spending">
        <SpendingSummary />
      </Section>
      <GroupLinks group="monthly" />
    </div>
  );
}
