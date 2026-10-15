import { numCompact } from "@/lib/data";

/**
 * One look for every recharts chart. SVG presentation attributes can't read CSS
 * custom properties reliably, so the palette mirrors the :root tokens in
 * styles.css — change both together.
 *
 * Time always runs left→right (the universal chart convention, also what Israeli
 * bank apps do) even though the page is RTL; the value axis sits on the left.
 */
export const C = {
  accent: "#6c8cff",
  good: "#34d399",
  bad: "#f87171",
  warn: "#fbbf24",
  muted: "#9aa3b2",
  line: "#2a2f3a",
  panel2: "#1f232c",
  text: "#e7e9ee",
};

export const tick = { fill: C.muted, fontSize: 11 };

/** Shared value axis: compact numbers, no axis line, narrow enough for phones. */
export const yAxisProps = {
  tick,
  width: 40,
  axisLine: false,
  tickLine: false,
  tickFormatter: (v: number) => numCompact(v),
} as const;

export const xAxisProps = {
  tick,
  axisLine: { stroke: C.line },
  tickLine: false,
  minTickGap: 16,
} as const;

export const tooltipProps = {
  contentStyle: {
    background: C.panel2,
    border: `1px solid ${C.line}`,
    borderRadius: 10,
    direction: "rtl" as const,
    fontSize: 13,
  },
  labelStyle: { color: C.text, fontWeight: 700 },
  itemStyle: { padding: 0 },
  cursor: { stroke: C.line, fill: "rgba(255,255,255,.04)" },
};

/** recharts' draw-in animation stalls in throttled/background tabs — skip it. */
export const noAnim = { isAnimationActive: false } as const;
