import { useState } from "react";
import {
  Area,
  ComposedChart,
  CartesianGrid,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useIsMobile } from "@/hooks/use-mobile";
import { cashflow, shekel } from "@/lib/data";
import { chartProps, noAnim, useChartColors } from "./chartTheme";

interface Series {
  name: string;
  ds: number[];
}

interface Row {
  year: number;
  age: number;
  net: number;
  loans?: number;
}

/**
 * Yearly rows from the projection's `charts.net_worth` (one point per year to the
 * end age), anchored with today's point so the curve starts where you are now.
 */
function rows(): Row[] {
  const chart = cashflow.charts?.net_worth as { x_axis?: string[]; datasets?: Series[] } | undefined;
  const cfg = cashflow.projection?.config as { current_age?: number } | undefined;
  const today = cashflow.projection?.focal_points?.[0];
  if (!chart?.x_axis || !chart.datasets || cfg?.current_age == null) return [];

  const net = chart.datasets.find((d) => d.name === "שווי נקי")?.ds ?? [];
  const loans = chart.datasets.find((d) => d.name === "יתרת הלוואות")?.ds ?? [];
  const thisYear = new Date(cashflow.generated_at).getFullYear();
  const ageAt = (y: number) => Math.round(cfg.current_age! + (y - thisYear));

  const out: Row[] = chart.x_axis.map((y, i) => ({
    year: Number(y),
    age: ageAt(Number(y)),
    net: net[i],
    loans: loans[i],
  }));
  if (today?.net_val != null) {
    out.unshift({ year: thisYear, age: cfg.current_age, net: today.net_val, loans: today.loan_val });
  }
  return out;
}

/**
 * The lifetime net-worth curve, by age. `showLoans` overlays the loan balance
 * paying down. Shared by Overview, Cashflow, Net worth and Plan screens.
 *
 * On phones a readout above the chart shows the point under your finger instead
 * of a floating tooltip, and the height follows the width.
 */
export default function NetWorthChart({
  height = 240,
  showLoans = false,
}: {
  height?: number;
  showLoans?: boolean;
}) {
  const C = useChartColors();
  const P = chartProps(C);
  const isMobile = useIsMobile();
  const [active, setActive] = useState<number | null>(null);
  const data = rows();
  if (data.length === 0) return <div className="muted">אין נתוני תחזית להצגה.</div>;

  const retireAge = (cashflow.projection?.config as { retirement_age?: number } | undefined)?.retirement_age;
  const shown = data[active ?? 0];

  return (
    <div className="chart">
      {isMobile && (
        <div className="mb-2 flex items-baseline justify-between text-sm">
          <span className="text-muted-foreground">
            גיל {shown.age} · {shown.year}
          </span>
          <strong className="tabular-nums">{shekel(shown.net)}</strong>
        </div>
      )}
      <div dir="ltr">
        <ResponsiveContainer width="100%" {...(isMobile ? { aspect: 1.6 } : { height })}>
          <ComposedChart
            data={data}
            margin={{ top: 10, right: 6, left: 0, bottom: 0 }}
            onMouseMove={(s) => s.activeTooltipIndex != null && setActive(Number(s.activeTooltipIndex))}
            onMouseLeave={() => setActive(null)}
          >
            <defs>
              <linearGradient id="nw-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={C.accent} stopOpacity={0.45} />
                <stop offset="100%" stopColor={C.accent} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={C.line} vertical={false} />
            <XAxis dataKey="age" {...P.xAxis} tickFormatter={(a: number) => `${a}`} interval="preserveStartEnd" />
            <YAxis {...P.yAxis} />
            <ReferenceLine y={0} stroke={C.muted} strokeOpacity={0.5} />
            {retireAge != null && (
              <ReferenceLine
                x={retireAge}
                stroke={C.warn}
                strokeDasharray="4 4"
                label={{ value: "פרישה", fill: C.warn, fontSize: 11, position: "insideTopLeft" }}
              />
            )}
            <Tooltip
              {...P.tooltip}
              {...(isMobile ? { content: () => null } : {})}
              labelFormatter={(age, p) => `גיל ${age} · ${p?.[0]?.payload?.year ?? ""}`}
              formatter={(v, name) => [shekel(v as number), name === "net" ? "שווי נקי" : "יתרת הלוואות"]}
            />
            <Area type="monotone" dataKey="net" stroke={C.accent} strokeWidth={2} fill="url(#nw-fill)" {...noAnim} />
            {showLoans && (
              <Line type="monotone" dataKey="loans" stroke={C.bad} strokeWidth={1.5} strokeDasharray="5 4" dot={false} {...noAnim} />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="chart-legend">
        <span><i style={{ background: C.accent }} /> שווי נקי</span>
        {showLoans && <span><i className="dashed" style={{ borderColor: C.bad }} /> יתרת הלוואות</span>}
        <span className="muted">ציר אופקי: גיל</span>
      </div>
    </div>
  );
}
