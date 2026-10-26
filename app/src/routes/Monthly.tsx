import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { Card, Page } from "@/components/common";
import BillsCard from "@/components/BillsCard";
import { RunwayCard, RunwayEvents, RunwayFootnote } from "@/components/RunwayChart";
import CategoryBreakdown from "@/components/CategoryBreakdown";
import MonthStrip from "@/components/cashflow/MonthStrip";
import MonthHero, { type MonthViewMode } from "@/components/cashflow/MonthHero";
import { MonthGroups, MonthLinks } from "@/components/cashflow/MonthDetail";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cashflow } from "@/lib/data";

/** How many months the "בפועל" strip shows, ending with the current one. */
const ACTUAL_MONTHS = 6;

/**
 * "החודש": one month-by-month screen with a בפועל | תחזית toggle. The strip, hero and
 * plan-vs-actual rows follow the selected month; sections below are view-specific.
 * View and month live in the URL (?view=forecast&month=YYYY-MM) so back-navigation
 * from /spending restores them.
 */
export default function Monthly() {
  const view = cashflow.months_view;
  const [params, setParams] = useSearchParams();
  const months = view?.months ?? [];

  const mode: MonthViewMode = params.get("view") === "forecast" ? "forecast" : "actual";
  const forecast = mode === "forecast";

  // Strip rows per view. Forecast bars show where each month is expected to land, so the
  // current month's bar uses its end-of-month net rather than the net so far.
  const strip = forecast
    ? months
        .filter((m) => m.kind !== "actual")
        .map((m) => (m.kind === "current" && m.projected_end ? { ...m, net: m.projected_end.net } : m))
    : months.filter((m) => m.kind !== "projected").slice(-ACTUAL_MONTHS);

  // The picked month survives a view switch when the other view has it; otherwise fall back to now.
  const picked = params.get("month");
  const selected = strip.some((m) => m.month === picked) ? picked! : view?.current;

  /** The one URL writer: merges into the current params so view and month never drop each other. */
  const update = (next: Record<string, string>) =>
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        for (const [k, v] of Object.entries(next)) p.set(k, v);
        return p;
      },
      { replace: true },
    );

  // Keep the URL honest: a ?month the current view cannot show (invalid, or only in the other view) is clamped.
  useEffect(() => {
    if (picked && selected && picked !== selected) update({ month: selected });
  });

  if (!view || !months.length) {
    return (
      <Page title="החודש">
        <Card>
          <div className="text-muted-foreground">אין עדיין תצוגה חודשית — הריצו את הפייפליין ופרסמו מחדש.</div>
        </Card>
      </Page>
    );
  }
  const m = months.find((x) => x.month === selected) ?? months[months.length - 1];

  return (
    <Page title="החודש">
      <Tabs value={mode} onValueChange={(v) => update({ view: v })} dir="rtl">
        <TabsList className="w-full">
          <TabsTrigger value="actual">בפועל</TabsTrigger>
          <TabsTrigger value="forecast">תחזית</TabsTrigger>
        </TabsList>
      </Tabs>

      <MonthStrip months={strip} selected={m.month} onSelect={(month) => update({ month })} forecast={forecast} />
      <MonthHero m={m} mode={mode} />
      <MonthGroups m={m} mode={mode} />

      {forecast ? (
        <>
          {m.kind === "current" && <RunwayCard r={cashflow.runway} />}
          <RunwayEvents r={cashflow.runway} month={m.month} current={m.kind === "current"} />
          <MonthLinks
            links={[
              { to: "/timeline", label: "ציר זמן" },
              { to: "/fixed", label: "הוצאות קבועות" },
              { to: "/metrics", label: "התקדמות" },
            ]}
          />
          <RunwayFootnote r={cashflow.runway} />
        </>
      ) : (
        <>
          <CategoryBreakdown key={m.month} month={m.month} />
          {m.kind === "current" && <BillsCard compact />}
          <MonthLinks
            links={[
              ...(m.kind === "current" ? [{ to: "/budgets", label: "תקציב מפורט" }] : []),
              { to: "/fixed", label: "הוצאות קבועות" },
            ]}
          />
        </>
      )}
    </Page>
  );
}
