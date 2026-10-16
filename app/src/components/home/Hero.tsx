import { useState } from "react";
import { BigNumber, Card } from "@/components/common";
import { cashflow, shekel, snapshot } from "@/lib/data";

type HeroView = "liquid" | "net" | "spend";
const HERO_TABS: [HeroView, string][] = [["liquid", "מצב נזיל"], ["net", "שווי נקי"], ["spend", "הוצאות"]];

/** Mint-style hero. Defaults to the liquid position (no mortgage, no long-term
 *  savings) because net worth without the apartment's value reads as a
 *  misleadingly deep hole; net worth stays one tap away with that caveat. */
export default function Hero({ netToday }: { netToday: number | null }) {
  const [view, setView] = useState<HeroView>("liquid");
  const t = snapshot.totals;
  const cash = t.bank_balances_sum + (t.liquid_savings ?? 0);
  const liquid = cash - t.credit_card_debt - t.consumer_loan_balance;
  const net = t.net_position_with_savings ?? netToday;
  const pace = cashflow.pace;
  const spend = pace?.current.expense ?? null;
  const prev = pace?.previous.expense ?? null;
  const diff = spend != null && prev != null ? spend - prev : null;
  return (
    <Card>
      <div className="mb-3 inline-flex rounded-full bg-panel-2 p-0.5 text-sm font-semibold" role="tablist">
        {HERO_TABS.map(([k, l]) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={view === k}
            onClick={() => setView(k)}
            className={`rounded-full px-3.5 py-1 ${view === k ? "bg-background shadow-sm" : "text-muted-foreground"}`}
          >
            {l}
          </button>
        ))}
      </div>
      {view === "liquid" && (
        <>
          <BigNumber tone={liquid < 0 ? "bad" : undefined}>{shekel(liquid)}</BigNumber>
          <div className="mt-1 text-sm text-muted-foreground tabular-nums">
            מזומן ופיקדון נזיל {shekel(cash)} · אשראי {shekel(-t.credit_card_debt)} · הלוואות {shekel(-t.consumer_loan_balance)}
          </div>
          <div className="mt-0.5 text-xs text-muted-foreground">ללא משכנתא וחסכון ארוך טווח</div>
        </>
      )}
      {view === "net" && (
        <>
          <BigNumber tone={net != null && net < 0 ? "bad" : undefined}>{net != null ? shekel(net) : "—"}</BigNumber>
          <div className="mt-1 text-sm text-muted-foreground">כולל חסכונות ומשכנתא</div>
          <div className="mt-0.5 text-xs text-muted-foreground">שווי הדירה אינו נכלל — לכן המספר נמוך מהשווי האמיתי</div>
        </>
      )}
      {view === "spend" && (
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
