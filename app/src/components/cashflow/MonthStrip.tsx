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
 * Income/expense detail lives in the hero card below, which keeps the bars legible at 390px.
 */
export default function MonthStrip({
  months,
  selected,
  onSelect,
  forecast = false,
}: {
  months: MonthViewRow[];
  selected: string;
  onSelect: (month: string) => void;
  /** Forecast view: every bar is an expectation, so all are drawn light and dashed. */
  forecast?: boolean;
}) {
  const C = useChartColors();
  const P = chartProps(C);
  const idx = months.findIndex((m) => m.month === selected);
  // Near-zero months would be untappable slivers: plot them at a floor of 4% of the tallest bar.
  const floor = Math.max(...months.map((m) => Math.abs(m.net)), 1) * 0.04;
  const data = months.map((m) => ({
    ...m,
    bar: Math.abs(m.net) < floor ? (m.net < 0 ? -floor : floor) : m.net,
    label: shortMonth(m.month),
    caption: m.kind === "current" ? "החודש" : m.kind === "projected" ? "צפי" : "",
  }));
  const step = (d: number) => {
    const next = months[idx + d];
    if (next) onSelect(next.month);
  };

  return (
    <Card>
      <div className="chart" dir="ltr">
        <ResponsiveContainer width="100%" height={130}>
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
            <Bar dataKey="bar" radius={[3, 3, 3, 3]} maxBarSize={22} cursor="pointer" {...noAnim}>
              {data.map((m) => {
                const projected = forecast || m.kind === "projected";
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
      <div className="mt-2 flex items-center justify-between" dir="ltr">
        {/* Follows the bars (time runs left→right): the left button goes to the earlier month, the right one to the later. */}
        <button
          type="button"
          aria-label="החודש הקודם"
          disabled={idx <= 0}
          onClick={() => step(-1)}
          className="grid size-9 place-items-center rounded-full bg-panel-2 disabled:opacity-30"
        >
          <ChevronLeft className="size-5" />
        </button>
        <span className="text-xs text-muted-foreground" dir="rtl">
          {forecast ? "נטו צפוי לחודש" : "נטו לכל חודש"} · לחצו לבחירה
        </span>
        <button
          type="button"
          aria-label="החודש הבא"
          disabled={idx >= months.length - 1}
          onClick={() => step(1)}
          className="grid size-9 place-items-center rounded-full bg-panel-2 disabled:opacity-30"
        >
          <ChevronRight className="size-5" />
        </button>
      </div>
    </Card>
  );
}
