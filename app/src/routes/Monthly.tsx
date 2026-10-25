import { useSearchParams } from "react-router-dom";
import { Card, Page, Section } from "@/components/common";
import BillsCard from "@/components/BillsCard";
import CategoryBreakdown from "@/components/CategoryBreakdown";
import MonthStrip from "@/components/cashflow/MonthStrip";
import MonthHero, { type MonthViewMode } from "@/components/cashflow/MonthHero";
import { MonthGroups, MonthLinks } from "@/components/cashflow/MonthDetail";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cashflow, shekel } from "@/lib/data";

/** How many months the "בפועל" strip shows, ending with the current one. */
const ACTUAL_MONTHS = 6;
/** Upcoming debits listed in the forecast view. */
const UPCOMING_LIMIT = 5;

const shortDate = (iso: string) =>
  new Intl.DateTimeFormat("he-IL", { day: "numeric", month: "short" }).format(new Date(`${iso.slice(0, 10)}T12:00:00`));

/** The largest future debits of the selected month from the balance runway (card bills, mortgage, loans…), in date order. */
function UpcomingDebits({ month }: { month: string }) {
  const r = cashflow.runway;
  if (!r) return null;
  const events = r.events
    .filter((e) => e.amount < 0 && e.date >= r.as_of && e.date.startsWith(month))
    .sort((a, b) => a.amount - b.amount)
    .slice(0, UPCOMING_LIMIT)
    .sort((a, b) => a.date.localeCompare(b.date));
  if (!events.length) return null;
  return (
    <Section title="חיובים גדולים צפויים" to="/runway">
      <Card>
        {events.map((e, i) => (
          <div key={`${e.date}-${e.name}-${i}`} className="flex items-center gap-3 border-b border-line py-2.5 last:border-b-0">
            <span className="w-12 shrink-0 text-sm text-muted-foreground tabular-nums">{shortDate(e.date)}</span>
            <span className="min-w-0 flex-1 truncate">{e.name}</span>
            <strong className="shrink-0 tabular-nums">צפוי {shekel(-e.amount)}</strong>
          </div>
        ))}
      </Card>
    </Section>
  );
}

/**
 * "החודש": one month-by-month screen with a בפועל | תחזית toggle. The strip, hero and
 * plan-vs-actual rows follow the selected month; sections below are view-specific.
 * View and month live in the URL (?view=forecast&month=YYYY-MM) so back-navigation
 * from /spending restores them.
 */
export default function Monthly() {
  const view = cashflow.months_view;
  const [params, setParams] = useSearchParams();

  if (!view || !view.months.length) {
    return (
      <Page title="החודש">
        <Card>
          <div className="text-muted-foreground">אין עדיין תצוגה חודשית — הריצו את הפייפליין ופרסמו מחדש.</div>
        </Card>
      </Page>
    );
  }

  const mode: MonthViewMode = params.get("view") === "forecast" ? "forecast" : "actual";
  const forecast = mode === "forecast";

  // Strip rows per view. Forecast bars show where each month is expected to land, so the
  // current month's bar uses its end-of-month net rather than the net so far.
  const strip = forecast
    ? view.months
        .filter((m) => m.kind !== "actual")
        .map((m) => (m.kind === "current" && m.projected_end ? { ...m, net: m.projected_end.net } : m))
    : view.months.filter((m) => m.kind !== "projected").slice(-ACTUAL_MONTHS);

  // The picked month survives a view switch when the other view has it; otherwise fall back to now.
  const picked = params.get("month");
  const selected = strip.some((m) => m.month === picked) ? picked! : view.current;
  const m = view.months.find((x) => x.month === selected) ?? view.months[view.months.length - 1];

  const update = (next: Record<string, string>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) p.set(k, v);
    setParams(p, { replace: true });
  };

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
          <UpcomingDebits month={m.month} />
          <MonthLinks
            links={[
              { to: "/runway", label: "יתרה צפויה" },
              { to: "/timeline", label: "ציר זמן" },
              { to: "/fixed", label: "הוצאות קבועות" },
              { to: "/metrics", label: "התקדמות" },
            ]}
          />
        </>
      ) : (
        <>
          {m.kind === "current" && <BillsCard />}
          <CategoryBreakdown key={m.month} month={m.month} />
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
