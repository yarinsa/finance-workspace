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
import { cashflow, shekel } from "@/lib/data";
import { C, noAnim, tooltipProps, xAxisProps, yAxisProps } from "./chartTheme";

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

/** The lifetime net-worth curve, by age. `showLoans` overlays the loan balance
 *  paying down. Shared by Overview, Cashflow, Net worth and Summary screens. */
export default function NetWorthChart({
  height = 240,
  showLoans = false,
}: {
  height?: number;
  showLoans?: boolean;
}) {
  const data = rows();
  if (data.length === 0) return <div className="muted">אין נתוני תחזית להצגה.</div>;

  const retireAge = (cashflow.projection?.config as { retirement_age?: number } | undefined)?.retirement_age;

  return (
    <div className="chart" dir="ltr">
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 10, right: 6, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="nw-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={C.accent} stopOpacity={0.45} />
              <stop offset="100%" stopColor={C.accent} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke={C.line} vertical={false} />
          <XAxis dataKey="age" {...xAxisProps} tickFormatter={(a: number) => `${a}`} interval="preserveStartEnd" />
          <YAxis {...yAxisProps} />
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
            {...tooltipProps}
            labelFormatter={(age, p) => `גיל ${age} · ${p?.[0]?.payload?.year ?? ""}`}
            formatter={(v, name) => [shekel(v as number), name === "net" ? "שווי נקי" : "יתרת הלוואות"]}
          />
          <Area type="monotone" dataKey="net" stroke={C.accent} strokeWidth={2} fill="url(#nw-fill)" {...noAnim} />
          {showLoans && (
            <Line type="monotone" dataKey="loans" stroke={C.bad} strokeWidth={1.5} strokeDasharray="5 4" dot={false} {...noAnim} />
          )}
        </ComposedChart>
      </ResponsiveContainer>
      <div className="chart-legend" dir="rtl">
        <span><i style={{ background: C.accent }} /> שווי נקי</span>
        {showLoans && <span><i className="dashed" style={{ borderColor: C.bad }} /> יתרת הלוואות</span>}
        <span className="muted">ציר אופקי: גיל</span>
      </div>
    </div>
  );
}
