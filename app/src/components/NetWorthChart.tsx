import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { cashflow, shekel, shekelCompact } from "@/lib/data";

/** The lifetime net-worth curve from projection.focal_points (today → end age).
 *  Shared by Cashflow, Overview, Net worth and Summary screens. */
export default function NetWorthChart({ height = 260 }: { height?: number }) {
  const points = (cashflow.projection?.focal_points ?? [])
    .filter((p) => p.net_val != null)
    .map((p) => ({
      label: p.age != null ? `גיל ${p.age}` : (p.date ?? p.name ?? ""),
      net: p.net_val as number,
    }));

  if (points.length === 0) {
    return <div className="muted">אין נתוני תחזית להצגה.</div>;
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={points} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
        <defs>
          <linearGradient id="nw" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#6c8cff" stopOpacity={0.5} />
            <stop offset="100%" stopColor="#6c8cff" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#2a2f3a" vertical={false} />
        <XAxis dataKey="label" tick={{ fill: "#9aa3b2", fontSize: 12 }} reversed />
        <YAxis
          tickFormatter={(v) => shekelCompact(v as number)}
          tick={{ fill: "#9aa3b2", fontSize: 12 }}
          width={70}
          orientation="right"
        />
        <Tooltip
          formatter={(v) => shekel(v as number)}
          contentStyle={{ background: "#1f232c", border: "1px solid #2a2f3a", borderRadius: 10 }}
          labelStyle={{ color: "#e7e9ee" }}
        />
        <Area type="monotone" dataKey="net" stroke="#6c8cff" fill="url(#nw)" strokeWidth={2} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
