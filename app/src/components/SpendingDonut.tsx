import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";
import { cashflow, pct, shekel } from "@/lib/data";
import { noAnim, useChartColors } from "./chartTheme";

/** Month-to-date spending by category (cashflow.pace.current.by_category). */
export default function SpendingDonut() {
  const C = useChartColors();
  const cats = cashflow.pace?.current.by_category ?? [];
  const total = cats.reduce((a, c) => a + c.amount, 0);
  if (!cats.length || total <= 0) return <div className="muted">אין הוצאות החודש.</div>;

  // Largest slices get the deepest greens; "אחר" is always the neutral one.
  const color = (name: string, i: number) => (name === "אחר" ? C.line : C.series[i % C.series.length]);

  return (
    <div className="donut">
      <div className="donut-chart">
        <ResponsiveContainer width="100%" height={150}>
          <PieChart>
            <Pie
              data={cats}
              dataKey="amount"
              nameKey="name"
              innerRadius="62%"
              outerRadius="100%"
              paddingAngle={2}
              stroke="none"
              {...noAnim}
            >
              {cats.map((c, i) => (
                <Cell key={c.name} fill={color(c.name, i)} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div className="donut-center">
          <span>סה״כ</span>
          <strong>{shekel(total)}</strong>
        </div>
      </div>
      <ul className="donut-legend">
        {cats.map((c, i) => (
          <li key={c.name}>
            <i style={{ background: color(c.name, i) }} />
            <span className="donut-name">{c.name}</span>
            <span className="muted">{pct((c.amount / total) * 100)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
