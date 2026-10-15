import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { cashflow, shekel } from "@/lib/data";
import { C, noAnim, tooltipProps, xAxisProps, yAxisProps } from "./chartTheme";

interface MonthRow {
  month: string;
  income: number;
  expense: number;
  net: number;
}

const shortMonth = (ym: string) =>
  new Intl.DateTimeFormat("he-IL", { month: "short" }).format(new Date(`${ym}-01T12:00:00`));

/**
 * Income vs spending per month with the net as a line — the last `months`
 * months that actually have ledger data. The month in progress is marked "*"
 * because it is partial.
 */
export default function MonthlyTrendChart({ months = 8, height = 220 }: { months?: number; height?: number }) {
  const all = (cashflow.months ?? []) as MonthRow[];
  const data = all
    .filter((m) => m.income > 0 || m.expense > 0)
    .slice(-months)
    .map((m) => ({
      ...m,
      label: shortMonth(m.month) + (m.month === cashflow.current_month ? "*" : ""),
    }));
  if (data.length === 0) return <div className="muted">אין נתוני תזרים.</div>;

  const names: Record<string, string> = { income: "הכנסות", expense: "הוצאות", net: "תזרים" };
  return (
    <div className="chart" dir="ltr">
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 10, right: 6, left: 0, bottom: 0 }} barGap={2}>
          <CartesianGrid stroke={C.line} vertical={false} />
          <XAxis dataKey="label" {...xAxisProps} interval={0} />
          <YAxis {...yAxisProps} />
          <Tooltip
            {...tooltipProps}
            labelFormatter={(_, p) => p?.[0]?.payload?.month ?? ""}
            formatter={(v, k) => [shekel(v as number), names[k as string] ?? k]}
          />
          <Bar dataKey="income" fill={C.good} radius={[3, 3, 0, 0]} maxBarSize={14} {...noAnim} />
          <Bar dataKey="expense" fill={C.bad} radius={[3, 3, 0, 0]} maxBarSize={14} {...noAnim} />
          <Line dataKey="net" stroke={C.accent} strokeWidth={2} dot={{ r: 2.5, fill: C.accent }} {...noAnim} />
        </ComposedChart>
      </ResponsiveContainer>
      <div className="chart-legend" dir="rtl">
        <span><i style={{ background: C.good }} /> הכנסות</span>
        <span><i style={{ background: C.bad }} /> הוצאות</span>
        <span><i style={{ background: C.accent }} /> תזרים</span>
        <span className="muted">* חודש בתהליך</span>
      </div>
    </div>
  );
}
