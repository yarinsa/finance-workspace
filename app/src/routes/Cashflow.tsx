import { useState } from "react";
import { Card, PageTitle } from "@/components/common";
import MonthStrip from "@/components/cashflow/MonthStrip";
import { CashflowLinks, MonthCategories, MonthResult, PlanVsActual } from "@/components/cashflow/MonthDetail";
import { cashflow } from "@/lib/data";

/**
 * "תזרים" hub: one month-by-month screen — month strip, the selected month's
 * income/expense/net, plan vs actual, and where the money went. Deep pages
 * (runway, timeline, metrics) hang off the link row at the bottom.
 */
export default function Cashflow() {
  const view = cashflow.months_view;
  const [picked, setPicked] = useState<string | null>(null);

  if (!view || !view.months.length) {
    return (
      <div className="space-y-4">
        <PageTitle>תזרים</PageTitle>
        <Card>
          <div className="text-muted-foreground">אין עדיין תצוגה חודשית — הריצו את הפייפליין ופרסמו מחדש.</div>
        </Card>
        <CashflowLinks />
      </div>
    );
  }

  const selected = view.months.some((m) => m.month === picked) ? picked! : view.current;
  const m = view.months.find((x) => x.month === selected) ?? view.months[view.months.length - 1];

  return (
    <div className="space-y-4 md:space-y-[18px]">
      <PageTitle>תזרים</PageTitle>
      <MonthStrip months={view.months} selected={m.month} onSelect={setPicked} />
      <MonthResult m={m} />
      <PlanVsActual m={m} />
      <MonthCategories m={m} />
      <CashflowLinks />
    </div>
  );
}
