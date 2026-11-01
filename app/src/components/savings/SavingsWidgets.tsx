import { BigNumber, Card, CardLabel, StackedBar } from "@/components/common";
import { Legend, Slide } from "@/components/transactions/WidgetsCarousel";
import { GeneralCard } from "@/routes/Goals";
import { shekel, shekelSigned } from "@/lib/data";
import type { DisplayGeneral } from "@/lib/goalsOverlay";
import type { SavingsStats } from "@/lib/savingsView";

/** "31.12.2030": liquidity dates sit years ahead, so the year stays. */
export const fullDate = (iso: string): string =>
  new Intl.DateTimeFormat("he-IL", { day: "numeric", month: "numeric", year: "numeric" }).format(new Date(`${iso.slice(0, 10)}T12:00:00`));

/**
 * The חיסכון stats, one card per slide. Balances are as of the holdings' read date; the net
 * movement follows the range chips (a flow, never added to a balance); the household targets
 * and the missing piece ignore the range and say so, as free money does on תנועות.
 */
export default function SavingsWidgets({
  stats,
  general,
  missingPiece,
}: {
  stats: SavingsStats;
  general: DisplayGeneral[];
  missingPiece: number;
}) {
  const hasBalance = stats.balance > 0;
  return (
    <div className="-mx-1 flex snap-x snap-mandatory gap-3 overflow-x-auto px-1 pb-1" role="region" aria-label="סיכומים">
      <Slide>
        <Card>
          <CardLabel>סך החיסכון</CardLabel>
          <BigNumber>{shekel(stats.balance)}</BigNumber>
          <div className="mt-2 text-xs text-muted-foreground tabular-nums">
            {stats.asOf ? `נכון ל־${fullDate(stats.asOf)}` : "יתרות, לא לפי הטווח"}
          </div>
        </Card>
      </Slide>
      {hasBalance && (
        <Slide>
          <Card>
            <CardLabel>נזיל ונעול</CardLabel>
            <StackedBar fixed={stats.illiquid} variable={stats.liquid} total={stats.balance} className="mb-3" />
            <div className="flex flex-col gap-1.5">
              <Legend tone="var(--holst-1)" label="נעול" value={stats.illiquid} />
              <Legend tone="var(--holst-4)" label="נזיל" value={stats.liquid} />
            </div>
          </Card>
        </Slide>
      )}
      {hasBalance && (
        <Slide>
          <Card>
            <CardLabel>הפתיחה הקרובה</CardLabel>
            {stats.nextUnlock ? (
              <>
                <BigNumber>{shekel(stats.nextUnlock.amount)}</BigNumber>
                <div className="mt-2 text-xs text-muted-foreground tabular-nums">מתפנה ב־{fullDate(stats.nextUnlock.date)}</div>
              </>
            ) : (
              <div className="text-sm text-muted-foreground">אין תאריך נזילות ידוע בקרנות.</div>
            )}
          </Card>
        </Slide>
      )}
      <Slide>
        <Card>
          <CardLabel>הפקדות נטו בטווח</CardLabel>
          <BigNumber>{stats.flow > 0 ? shekelSigned(stats.flow) : shekel(stats.flow)}</BigNumber>
          <div className="mt-2 text-xs text-muted-foreground">תזרים בטווח שנבחר, לא יתרה</div>
        </Card>
      </Slide>
      {general.map((c) => (
        <Slide key={c.key}>
          <GeneralCard c={c} />
          <div className="mt-1.5 px-1 text-xs text-muted-foreground">יעד משק הבית, לא לפי הטווח</div>
        </Slide>
      ))}
      {missingPiece > 0 && (
        <Slide>
          <Card>
            <CardLabel>החתיכה החסרה</CardLabel>
            <BigNumber>{shekel(missingPiece)}</BigNumber>
            <div className="mt-2 text-xs text-muted-foreground">פער למימון כל היעדים, לא לפי הטווח</div>
          </Card>
        </Slide>
      )}
    </div>
  );
}
