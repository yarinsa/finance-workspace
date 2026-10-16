import { Card, CardLabel } from "@/components/common";
import { shekel } from "@/lib/data";
import type { Budgets } from "@/lib/budgets";

/** Small Overview card: what is left of this cycle's budget, linking to /budgets. */
export default function BudgetsTeaser({ budgets: b }: { budgets: Budgets }) {
  const over = b.left < 0;
  return (
    <Card to="/budgets">
      <CardLabel>תקציב</CardLabel>
      <div className={`text-[22px] font-extrabold tabular-nums ${over ? "text-bad" : ""}`}>
        {over ? `חריגה ${shekel(-b.left)}` : `${shekel(b.left)} נותרו`}
      </div>
      <div className="mt-1 text-sm text-muted-foreground">
        {b.per_day != null ? `${shekel(b.per_day)} ליום · ${b.days_left} ימים` : `${shekel(b.total_spent)} מתוך ${shekel(b.total_planned)}`}
      </div>
    </Card>
  );
}
