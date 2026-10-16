import { Bar, Cell, CartesianGrid, ComposedChart, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Card } from "@/components/common";
import { chartProps, noAnim, useChartColors } from "@/components/chartTheme";
import type { MonthViewRow } from "@/lib/data";

const shortMonth = (ym: string) =>
  new Intl.DateTimeFormat("he-IL", { month: "short" }).format(new Date(`${ym}-01T12:00:00`));

/**
 * Copilot-style month strip: one signed net bar per month (green up / red down),
 * time left→right. Projected months are lighter with a dashed edge and a "צפי"
 * caption; the current month is outlined. Tap a bar (or use ‹ ›) to select.
 * Income/expense detail lives in the result card below, which keeps 13 bars legible at 390px.
 */
export default function MonthStrip({
  months,
  selected,
  onSelect,
}: {
  months: MonthViewRow[];
  selected: string;
  onSelect: (month: string) => void;
}) {
  const C = useChartColors();
  const P = chartProps(C);
  const idx = months.findIndex((m) => m.month === selected);
  const data = months.map((m) => ({
    ...m,
    label: shortMonth(m.month),
    caption: m.kind === "projected" ? "צפי" : m.kind === "current" ? "החודש" : "",
  }));
  const step = (d: number) => {
    const next = months[idx + d];
    if (next) onSelect(next.month);
  };

  return (
    <Card>
      <div className="chart" dir="ltr">
        <ResponsiveContainer width="100%" height={190}>
          <ComposedChart
            data={data}
            margin={{ top: 8, right: 4, left: 0, bottom: 0 }}
            onClick={(s) => {
              const i = s?.activeTooltipIndex;
              if (typeof i === "number" && months[i]) onSelect(months[i].month);
            }}
          >
            <CartesianGrid stroke={C.line} vertical={false} />
            <XAxis
              dataKey="label"
              {...P.xAxis}
              interval={0}
              height={34}
              tickLine={false}
              tick={({ x, y, payload, index }: { x: number; y: number; payload: { value: string }; index: number }) => {
                const m = data[index];
                const sel = m?.month === selected;
                return (
                  <g transform={`translate(${x},${y})`}>
                    <text y={12} textAnchor="middle" fontSize={11} fill={sel ? C.text : C.muted} fontWeight={sel ? 700 : 400}>
                      {payload.value}
                    </text>
                    {m?.caption && (
                      <text y={25} textAnchor="middle" fontSize={9} fill={C.muted}>
                        {m.caption}
                      </text>
                    )}
                  </g>
                );
              }}
            />
            <YAxis {...P.yAxis} />
            <ReferenceLine y={0} stroke={C.line} />
            <Bar dataKey="net" radius={[3, 3, 3, 3]} maxBarSize={22} cursor="pointer" {...noAnim}>
              {data.map((m) => {
                const projected = m.kind === "projected";
                const isSel = m.month === selected;
                return (
                  <Cell
                    key={m.month}
                    fill={m.net >= 0 ? C.good : C.bad}
                    fillOpacity={projected ? 0.35 : isSel || m.kind === "current" ? 1 : 0.75}
                    stroke={isSel ? C.text : projected ? (m.net >= 0 ? C.good : C.bad) : m.kind === "current" ? C.text : "none"}
                    strokeWidth={isSel || m.kind === "current" ? 2 : 1}
                    strokeDasharray={projected && !isSel ? "3 2" : undefined}
                  />
                );
              })}
            </Bar>
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 flex items-center justify-between" dir="rtl">
        {/* RTL: the right-hand button goes back in time, the left-hand one forward. */}
        <button
          type="button"
          aria-label="החודש הקודם"
          disabled={idx <= 0}
          onClick={() => step(-1)}
          className="grid size-9 place-items-center rounded-full bg-panel-2 disabled:opacity-30"
        >
          <ChevronRight className="size-5" />
        </button>
        <span className="text-xs text-muted-foreground">תזרים נקי לכל חודש · לחצו על עמודה לבחירה</span>
        <button
          type="button"
          aria-label="החודש הבא"
          disabled={idx >= months.length - 1}
          onClick={() => step(1)}
          className="grid size-9 place-items-center rounded-full bg-panel-2 disabled:opacity-30"
        >
          <ChevronLeft className="size-5" />
        </button>
      </div>
    </Card>
  );
}
