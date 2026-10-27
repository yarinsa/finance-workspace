import { useState } from "react";
import { Bar, BarChart, Cell, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { shekel } from "@/lib/data";
import type { BudgetCategory } from "@/lib/budgets";
import { noAnim, useChartColors } from "./chartTheme";

const STEP = 50;

/** "2026-07" -> "07/26" for compact bar labels. */
const cycleLabel = (c: string) => `${c.slice(5)}/${c.slice(2, 4)}`;

/** Round to the nearest ₪10 so the suggestion reads like a budget, not a statistic. */
const round10 = (n: number) => Math.round(n / 10) * 10;

/**
 * Read-only budget editor (Mint-style): last cycles' spend vs. the planned line,
 * a suggested amount, and the CLI command that applies a new amount. The app is a
 * static reader, so the stepper only changes the copied command; the budget
 * changes once `data/budgets.py set` runs (or Claude runs it) and data is synced.
 */
export default function BudgetEditorSheet({
  category,
  onClose,
}: {
  category: BudgetCategory | null;
  onClose: () => void;
}) {
  return (
    <Sheet open={category != null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="bottom" className="max-h-[90dvh] overflow-y-auto" dir="rtl">
        {category && <Body key={category.name} c={category} />}
      </SheetContent>
    </Sheet>
  );
}

function Body({ c }: { c: BudgetCategory }) {
  const C = useChartColors();
  const [amount, setAmount] = useState(Math.round(c.planned));
  const [copied, setCopied] = useState(false);

  const history = c.history ?? [];
  const avg = history.length ? history.reduce((s, h) => s + h.spent, 0) / history.length : null;
  const suggested = avg != null ? round10(avg) : null;
  const data = [
    ...history.map((h) => ({ label: cycleLabel(h.cycle), spent: h.spent, current: false })),
    { label: "החודש", spent: c.spent, current: true },
  ];
  const command = `python3 data/budgets.py set "${c.name}" ${amount}`;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable: the command stays selectable */
    }
  };

  return (
    <>
      <SheetHeader>
        <SheetTitle className="text-lg font-bold">{c.name}</SheetTitle>
        <SheetDescription className="tabular-nums">
          {c.source === "unplanned" ? "לא מתוכנן עדיין" : `מתוכנן ${shekel(c.planned)}`}
          {c.source === "riseup" && (
            <span className="ms-2 rounded-full bg-brand/15 px-2 py-0.5 text-xs font-semibold">מ-RiseUp</span>
          )}
        </SheetDescription>
      </SheetHeader>

      <div className="px-4">
        <div className="h-44" dir="ltr">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 16, right: 8, left: 8, bottom: 0 }}>
              <XAxis dataKey="label" tick={{ fill: C.muted, fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis hide domain={[0, (max: number) => Math.max(max, c.planned) * 1.1]} />
              <ReferenceLine
                y={c.planned}
                stroke={C.warn}
                strokeDasharray="4 4"
                label={{ value: shekel(c.planned), fill: C.warn, fontSize: 11, position: "insideTopRight" }}
              />
              <Bar dataKey="spent" radius={[4, 4, 0, 0]} label={{ position: "top", fill: C.muted, fontSize: 10, formatter: (v: number) => shekel(v) }} {...noAnim}>
                {data.map((d, i) => (
                  <Cell key={i} fill={d.current ? C.accent : C.muted} fillOpacity={d.current ? 1 : 0.55} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        {history.length === 0 && <div className="text-xs text-muted-foreground">אין היסטוריה לקטגוריה הזו.</div>}

        <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
          <div>
            <div className="text-xs text-muted-foreground">ממוצע {history.length} חודשים</div>
            <div className="font-bold tabular-nums">{avg != null ? shekel(avg) : "—"}</div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">תקציב מומלץ</div>
            <div className="font-bold tabular-nums">{suggested != null ? shekel(suggested) : "—"}</div>
            {suggested != null && suggested !== amount && (
              <button type="button" className="text-xs text-brand underline" onClick={() => setAmount(suggested)}>
                השתמש בסכום
              </button>
            )}
          </div>
        </div>

        <div className="mt-4 rounded-xl border border-line p-3">
          <div className="mb-2 text-sm font-semibold">איך משנים את התקציב?</div>
          <div className="mb-3 flex items-center justify-center gap-4">
            <button
              type="button"
              aria-label="הפחת"
              className="size-9 rounded-full border border-line text-lg"
              onClick={() => setAmount((a) => Math.max(0, a - STEP))}
            >
              −
            </button>
            <div className="min-w-24 text-center text-xl font-extrabold tabular-nums">{shekel(amount)}</div>
            <button
              type="button"
              aria-label="הוסף"
              className="size-9 rounded-full border border-line text-lg"
              onClick={() => setAmount((a) => a + STEP)}
            >
              +
            </button>
          </div>
          <div className="mb-3 text-xs text-muted-foreground">
            התקציב בכל חודש מתחיל מחדש עם הסכום הזה. האפליקציה היא לקריאה בלבד: הרץ את הפקודה (או בקש מ-Claude להריץ),
            והשינוי יופיע אחרי סנכרון הנתונים.
          </div>
          <div className="flex items-center gap-2" dir="ltr">
            <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap rounded-lg bg-line/40 px-2 py-2 text-xs">{command}</code>
            <button type="button" className="shrink-0 rounded-lg bg-brand px-3 py-2 text-xs font-semibold text-white" onClick={copy}>
              {copied ? "הועתק" : "העתק"}
            </button>
          </div>
        </div>
      </div>
      <div className="h-4" />
    </>
  );
}
