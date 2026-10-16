import { Card, CardLabel } from "@/components/common";
import { shekel, type Runway } from "@/lib/data";

/** Small Overview card: safe-to-spend until payday, linking to the full runway. */
export default function RunwayTeaser({ runway: r }: { runway: Runway }) {
  const safe = r.safe_to_spend;
  if (safe == null) return null;
  const ok = safe > 0;
  return (
    <Card to="/runway">
      <CardLabel>יתרה צפויה</CardLabel>
      <div className={`text-[22px] font-extrabold tabular-nums ${ok ? "" : "text-bad"}`}>
        {ok ? `${shekel(safe)} פנוי עד המשכורת` : `חסרים ${shekel(-safe)} עד המשכורת`}
      </div>
      <div className="mt-1 text-sm text-muted-foreground">
        {ok && r.safe_per_day != null && r.days_to_payday != null
          ? `${shekel(r.safe_per_day)} ליום · ${r.days_to_payday} ימים`
          : `היתרה הנמוכה: ${shekel(r.low_point.balance)}`}
      </div>
    </Card>
  );
}
