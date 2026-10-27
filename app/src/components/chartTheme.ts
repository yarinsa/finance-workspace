import { useEffect, useState } from "react";
import { numCompact } from "@/lib/data";
import { mixHex } from "@/lib/color";

/**
 * One look for every recharts chart, following the CSS theme tokens in
 * styles.css (light by default, dark under prefers-color-scheme). SVG
 * presentation attributes can't reliably resolve var(), so the tokens are read
 * once per theme and passed down as plain colors.
 *
 * Time always runs left→right (the universal chart convention, also what Israeli
 * bank apps do) even though the page is RTL; the value axis sits on the left.
 */
export interface ChartColors {
  accent: string;
  good: string;
  bad: string;
  warn: string;
  muted: string;
  line: string;
  panel: string;
  text: string;
  /** Category series: the Holst greens darkest-first, then terracotta/ochre tints (never more greens). */
  series: string[];
}

const TOKENS: Record<Exclude<keyof ChartColors, "series">, string> = {
  accent: "--lg-accent",
  good: "--lg-good",
  bad: "--lg-bad",
  warn: "--lg-warn",
  muted: "--lg-muted",
  line: "--lg-line",
  panel: "--lg-panel",
  text: "--lg-text",
};

const SERIES_TOKENS = ["--holst-1", "--holst-3", "--holst-4", "--holst-2", "--holst-5"];

function readColors(): ChartColors {
  const css = getComputedStyle(document.documentElement);
  const read = (v: string) => css.getPropertyValue(v).trim();
  const base = Object.fromEntries(Object.entries(TOKENS).map(([k, v]) => [k, read(v)])) as Omit<ChartColors, "series">;
  const tint = (c: string) => mixHex(c, base.panel, 0.35);
  return { ...base, series: [...SERIES_TOKENS.map(read), tint(base.bad), tint(base.warn)] };
}

/** Theme colors for charts; re-reads when the OS switches light/dark. */
export function useChartColors(): ChartColors {
  const [c, setC] = useState(readColors);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setC(readColors());
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return c;
}

/** Shared axis/tooltip props for a given palette. */
export function chartProps(C: ChartColors) {
  const tick = { fill: C.muted, fontSize: 11 };
  return {
    yAxis: {
      tick,
      width: 40,
      axisLine: false,
      tickLine: false,
      tickFormatter: (v: number) => numCompact(v),
    },
    xAxis: { tick, axisLine: { stroke: C.line }, tickLine: false, minTickGap: 16 },
    tooltip: {
      contentStyle: {
        background: C.panel,
        border: `1px solid ${C.line}`,
        borderRadius: 12,
        direction: "rtl" as const,
        fontSize: 13,
        boxShadow: "var(--shadow)",
      },
      labelStyle: { color: C.text, fontWeight: 700 },
      itemStyle: { padding: 0 },
      cursor: { stroke: C.line, fill: "color-mix(in srgb, var(--lg-muted) 8%, transparent)" },
    },
  } as const;
}

/** recharts' draw-in animation stalls in throttled/background tabs — skip it. */
export const noAnim = { isAnimationActive: false } as const;
