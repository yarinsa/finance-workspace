import { useState } from "react";
import { Nudge, Page } from "@/components/common";
import GoalEditorSheet, { type GoalEditorTarget } from "@/components/GoalEditorSheet";
import PropertyEditorSheet from "@/components/PropertyEditorSheet";
import AccountCards from "@/components/home/AccountCards";
import HomeBand from "@/components/home/HomeBand";
import QuickActionsSheet, { type QuickAction } from "@/components/home/QuickActionsSheet";
import RecentTransactions from "@/components/home/RecentTransactions";
import WeekStrip from "@/components/home/WeekStrip";
import { cashflow, daysSince, num } from "@/lib/data";

/**
 * Home (docs/home-redesign.md): the teal band with one lens at a time, the account cards
 * rising out of it, the week ahead, and the latest transactions. To-dos live behind the bell.
 */
export default function Overview() {
  const age = daysSince(cashflow.generated_at);
  // A pipeline-emitted stale-data action replaces the generic nudge.
  const hasStaleAction = (cashflow.actions ?? []).some((a) => /stale|sync|refresh/i.test(a.id));
  const [quick, setQuick] = useState(false);
  const [property, setProperty] = useState(false);
  const [goal, setGoal] = useState<GoalEditorTarget | null>(null);

  const pick = (a: QuickAction) => {
    setQuick(false);
    if (a === "property") setProperty(true);
    else setGoal({});
  };

  return (
    <Page wide>
      <div className="max-w-[720px]">
        <HomeBand onQuickActions={() => setQuick(true)} />
        <div className="relative z-10 -mt-9">
          <AccountCards onEditProperty={() => setProperty(true)} />
        </div>
      </div>

      <div className="flex max-w-[720px] flex-col gap-6">
        {age > 7 && !hasStaleAction && (
          <Nudge action="לסנכרון">הנתונים מלפני {num(age)} ימים. כדאי לרענן את היתרות.</Nudge>
        )}
        <WeekStrip runway={cashflow.runway} />
        <RecentTransactions />
      </div>

      <QuickActionsSheet open={quick} onClose={() => setQuick(false)} onPick={pick} />
      <PropertyEditorSheet open={property} onClose={() => setProperty(false)} />
      <GoalEditorSheet goal={goal} onClose={() => setGoal(null)} />
    </Page>
  );
}
