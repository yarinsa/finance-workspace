import { Nudge } from "@/components/common";
import AccountRows from "@/components/home/AccountRows";
import ActionList from "@/components/home/ActionList";
import RecentTransactions from "@/components/home/RecentTransactions";
import StatusTiles from "@/components/home/StatusTiles";
import UpcomingChips from "@/components/home/UpcomingChips";
import { cashflow, daysSince, num, snapshot } from "@/lib/data";

function greeting(hour: number): string {
  if (hour < 5) return "לילה טוב";
  if (hour < 12) return "בוקר טוב";
  if (hour < 17) return "צהריים טובים";
  if (hour < 21) return "ערב טוב";
  return "לילה טוב";
}

/** Action-first home: status tiles, to-do list, next 14 days, accounts, recent spending. */
export default function Overview() {
  const age = daysSince(cashflow.generated_at);
  // A pipeline-emitted stale-data action replaces the generic nudge.
  const hasStaleAction = (cashflow.actions ?? []).some((a) => /stale|sync|refresh/i.test(a.id));
  const netWorth = snapshot.totals.net_position_with_savings ?? cashflow.projection?.net_worth_today ?? null;

  return (
    <div className="feed flex flex-col gap-6 [&>*]:!mt-0">
      {age > 7 && !hasStaleAction && (
        <Nudge action="לעדכון יתרות ▸">
          🕑 הגיע זמן לעדכן את היתרות שלך — הנתונים מלפני {num(age)} ימים.
        </Nudge>
      )}

      <header className="greeting">
        <h1>{greeting(new Date().getHours())} 👋</h1>
      </header>

      <StatusTiles />
      <ActionList actions={cashflow.actions} />
      <UpcomingChips runway={cashflow.runway} />
      <AccountRows netWorth={netWorth} />
      <RecentTransactions />
    </div>
  );
}
