import { useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useIsMobile } from "@/hooks/use-mobile";
import { cashflow, shekel, shekelCompact } from "@/lib/data";

/** The lifetime net-worth curve from projection.focal_points (today → end age).
 *  Shared by Cashflow, Overview, Net worth and Summary screens.
 *
 *  On phones the Y axis is dropped (its labels collided with the curve) and a
 *  readout above the chart shows the point under your finger instead of a
 *  floating tooltip; height follows the width rather than a fixed px value. */
export default function NetWorthChart({ height = 260 }: { height?: number }) {
  const isMobile = useIsMobile();
  const [active, setActive] = useState<number | null>(null);

  const points = (cashflow.projection?.focal_points ?? [])
    .filter((p) => p.net_val != null)
    .map((p) => ({
      label: p.age != null ? `גיל ${p.age}` : (p.date ?? p.name ?? ""),
      net: p.net_val as number,
    }));

  if (points.length === 0) {
    return <div className="muted">אין נתוני תחזית להצגה.</div>;
  }

  const shown = points[active ?? 0];
  const tick = { fill: "#9aa3b2", fontSize: isMobile ? 11 : 12 };

  return (
    <div>
      {isMobile && (
        <div className="mb-2 flex items-baseline justify-between text-sm">
          <span className="text-muted-foreground">{shown.label}</span>
          <strong className="tabular-nums">{shekel(shown.net)}</strong>
        </div>
      )}
      <ResponsiveContainer width="100%" {...(isMobile ? { aspect: 1.6 } : { height })}>
        <AreaChart
          data={points}
          margin={isMobile ? { top: 4, right: 4, left: 4, bottom: 0 } : { top: 8, right: 8, left: 8, bottom: 0 }}
          onMouseMove={(s) => s.activeTooltipIndex != null && setActive(s.activeTooltipIndex)}
          onMouseLeave={() => setActive(null)}
        >
          <defs>
            <linearGradient id="nw" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#6c8cff" stopOpacity={0.5} />
              <stop offset="100%" stopColor="#6c8cff" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#2a2f3a" vertical={false} />
          <XAxis
            dataKey="label"
            tick={tick}
            reversed
            interval="preserveStartEnd"
            minTickGap={isMobile ? 24 : 8}
          />
          <YAxis
            hide={isMobile}
            tickFormatter={(v) => shekelCompact(v as number)}
            tick={tick}
            width={70}
            orientation="right"
          />
          <Tooltip
            {...(isMobile ? { content: () => null } : {})}
            cursor={{ stroke: "#9aa3b2", strokeDasharray: "3 3" }}
            formatter={(v) => shekel(v as number)}
            contentStyle={{ background: "#1f232c", border: "1px solid #2a2f3a", borderRadius: 10 }}
            labelStyle={{ color: "#e7e9ee" }}
          />
          <Area type="monotone" dataKey="net" stroke="#6c8cff" fill="url(#nw)" strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
