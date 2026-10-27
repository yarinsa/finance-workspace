import { useEffect, useState } from "react";
import { Area, ComposedChart, Line, ReferenceDot, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { noAnim } from "@/components/chartTheme";
import type { Lens } from "@/lib/lenses";

interface BandColors {
  text: string;
  muted: string;
  line: string;
}

/** The band's own tokens (--hero-*), read like chartTheme reads --lg-*: SVG attributes can't take var(). */
function readBand(): BandColors {
  const css = getComputedStyle(document.documentElement);
  const v = (n: string) => css.getPropertyValue(n).trim();
  return { text: v("--hero-text"), muted: v("--hero-muted"), line: v("--hero-line") };
}

function useBandColors(): BandColors {
  const [c, setC] = useState(readBand);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setC(readBand());
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return c;
}

function tickLabel(x: string): string {
  if (/^\d{4}-\d{2}-\d{2}$/.test(x)) return `${Number(x.slice(8, 10))}.${Number(x.slice(5, 7))}`;
  return x;
}

/**
 * A lens's line on the teal band: the measured part as a soft area, the forecast dashed after
 * the היום dot, last month's line dotted underneath. No value axis: the big number above is the
 * reading, the chart is the shape. Time runs left → right, today toward the right.
 */
export default function LensChart({ lens, height = 150 }: { lens: Lens; height?: number }) {
  const C = useBandColors();
  const today = lens.series[lens.todayIndex];
  const n = lens.series.length;
  const ticks = [0, Math.floor(n / 3), Math.floor((2 * n) / 3), n - 1].map((i) => lens.series[i]?.x).filter(Boolean);
  const values = lens.series.flatMap((p) => [p.actual, p.projected, p.compare]).filter((v): v is number => v != null);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = (max - min) * 0.12 || 1;

  return (
    <div dir="ltr" aria-hidden>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={lens.series} margin={{ top: 12, right: 14, bottom: 0, left: 14 }}>
          <defs>
            <linearGradient id={`band-fill-${lens.key}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={C.line} stopOpacity={0.45} />
              <stop offset="100%" stopColor={C.line} stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="x"
            ticks={ticks}
            tickFormatter={tickLabel}
            tick={{ fill: C.muted, fontSize: 12 }}
            axisLine={false}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis hide domain={[min - pad, max + pad]} />
          {lens.key === "cash" && min < 0 && (
            <ReferenceLine
              y={0}
              stroke={C.muted}
              strokeOpacity={0.5}
              strokeDasharray="1 4"
              label={{ value: "₪0", position: "insideTopLeft", fill: C.muted, fontSize: 11 }}
            />
          )}
          <Line dataKey="compare" stroke={C.muted} strokeOpacity={0.6} strokeWidth={1.5} strokeDasharray="2 4" dot={false} {...noAnim} />
          <Area dataKey="actual" stroke={C.text} strokeWidth={2.5} fill={`url(#band-fill-${lens.key})`} dot={false} {...noAnim} />
          <Line dataKey="projected" stroke={C.text} strokeOpacity={0.7} strokeWidth={2} strokeDasharray="5 5" dot={false} {...noAnim} />
          {today && (today.actual ?? today.projected) != null && (
            <ReferenceDot
              x={today.x}
              y={today.actual ?? today.projected}
              r={7}
              fill={C.line}
              stroke={C.text}
              strokeWidth={3}
              label={{ value: "היום", position: "top", fill: C.text, fontSize: 13, fontWeight: 600, offset: 12 }}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
