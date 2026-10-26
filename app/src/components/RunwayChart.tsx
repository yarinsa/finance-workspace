import { Area, AreaChart, CartesianGrid, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, Section } from "@/components/common";
import { chartProps, noAnim, useChartColors } from "@/components/chartTheme";
import { shekel, type Runway as RunwayData } from "@/lib/data";

const shortDate = (iso: string) =>
  new Intl.DateTimeFormat("he-IL", { day: "numeric", month: "short" }).format(new Date(`${iso.slice(0, 10)}T12:00:00`));

/** Day-by-day checking balance (stepped) with the floor, overdraft limit, payday and low point marked. */
export function RunwayChart({ r, height = 240 }: { r: RunwayData; height?: number }) {
  const C = useChartColors();
  const P = chartProps(C);
  const limit = -Math.abs(r.overdraft_limit);
  const vals = r.days.map((d) => d.balance);
  const hi = Math.max(0, ...vals);
  const lo = Math.min(limit, ...vals);
  const pad = (hi - lo) * 0.12 || 100;
  const top = hi + pad;
  const bottom = lo - pad;
  // Colour split at y=0 in the area's own bbox (which spans max(0,hi)..min(0,lo)).
  const aTop = Math.max(0, ...vals);
  const aBot = Math.min(0, ...vals);
  const zeroAt = aTop === aBot ? 1 : aTop / (aTop - aBot);
  const payday = r.next_payday?.date;
  const inRange = (d?: string | null) => !!d && r.days.some((x) => x.date === d);

  return (
    <div className="chart" dir="ltr">
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={r.days} margin={{ top: 16, right: 8, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="rw-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={C.accent} stopOpacity={0.28} />
              <stop offset={`${zeroAt * 100}%`} stopColor={C.accent} stopOpacity={0.05} />
              <stop offset={`${zeroAt * 100}%`} stopColor={C.bad} stopOpacity={0.05} />
              <stop offset="100%" stopColor={C.bad} stopOpacity={0.32} />
            </linearGradient>
            <linearGradient id="rw-stroke" x1="0" y1="0" x2="0" y2="1">
              <stop offset={`${zeroAt * 100}%`} stopColor={C.accent} />
              <stop offset={`${zeroAt * 100}%`} stopColor={C.bad} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke={C.line} vertical={false} />
          <XAxis dataKey="date" {...P.xAxis} tickFormatter={shortDate} minTickGap={36} />
          <YAxis {...P.yAxis} domain={[bottom, top]} allowDataOverflow />
          <Tooltip
            {...P.tooltip}
            labelFormatter={(d) => shortDate(String(d))}
            formatter={(v) => [shekel(v as number), "יתרה"]}
          />
          <ReferenceLine y={r.floor} stroke={C.muted} strokeWidth={1}
            label={{ value: "רצפה", position: "insideTopRight", fill: C.muted, fontSize: 11 }} />
          {r.overdraft_limit > 0 && (
            <ReferenceLine y={limit} stroke={C.bad} strokeDasharray="4 4"
              label={{ value: "סוף המסגרת", position: "insideBottomRight", fill: C.bad, fontSize: 11 }} />
          )}
          {payday && inRange(payday) && (
            <ReferenceLine x={payday} stroke={C.good} strokeDasharray="3 3"
              label={{ value: "משכורת", position: "insideTopLeft", fill: C.good, fontSize: 11 }} />
          )}
          <Area dataKey="balance" type="stepAfter" baseValue={0} stroke="url(#rw-stroke)" strokeWidth={2}
            fill="url(#rw-fill)" dot={false} {...noAnim} />
          {inRange(r.low_point.date) && (
            <ReferenceDot x={r.low_point.date} y={r.low_point.balance} r={4}
              fill={r.low_point.balance < 0 ? C.bad : C.accent} stroke={C.panel} strokeWidth={2}
              label={{ value: shekel(r.low_point.balance), position: "bottom", fill: C.text, fontSize: 11, fontWeight: 700 }} />
          )}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Pills for the first overdraft-limit and below-zero days, if any. */
export function RunwayAlerts({ r }: { r: RunwayData }) {
  const chips: { text: string; cls: string }[] = [];
  if (r.first_limit_breach) chips.push({ text: `בחריגה מהמסגרת מ-${shortDate(r.first_limit_breach)}`, cls: "border-bad/40 bg-bad/10 text-bad" });
  if (r.first_floor_breach) chips.push({ text: `במינוס מ-${shortDate(r.first_floor_breach)}`, cls: "border-warn/40 bg-warn/10 text-warn" });
  if (!chips.length) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {chips.map((c) => (
        <span key={c.text} className={`rounded-full border px-3 py-1 text-sm font-semibold ${c.cls}`}>{c.text}</span>
      ))}
    </div>
  );
}

/** The runway chart as a section for the home and forecast screens, linking to the full /runway page. */
export function RunwayCard({ r }: { r: RunwayData | undefined }) {
  if (!r || r.days.length === 0) return null;
  return (
    <Section title="יתרה צפויה" to="/runway">
      <Card>
        <RunwayChart r={r} height={200} />
      </Card>
      <div className="mt-2">
        <RunwayAlerts r={r} />
      </div>
    </Section>
  );
}
