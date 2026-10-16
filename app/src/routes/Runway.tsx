import { Area, AreaChart, CartesianGrid, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BigNumber, Card, CardLabel, PageTitle, Section } from "@/components/common";
import { chartProps, noAnim, useChartColors } from "@/components/chartTheme";
import { cashflow, shekel, shekelSigned, type Runway as RunwayData } from "@/lib/data";

const shortDate = (iso: string) =>
  new Intl.DateTimeFormat("he-IL", { day: "numeric", month: "short" }).format(new Date(`${iso.slice(0, 10)}T12:00:00`));

const KIND_LABEL: Record<RunwayData["events"][number]["kind"], string> = {
  income: "הכנסה",
  loan: "הלוואה",
  card: "אשראי",
  housing: "דיור",
  bill: "חשבון",
};

/** Hero: how much can be spent before payday, or how short the account is. */
function Hero({ r }: { r: RunwayData }) {
  const safe = r.safe_to_spend;
  const over = r.headroom_to_limit != null && r.headroom_to_limit < 0;
  const ok = safe != null && safe > 0;
  return (
    <Card>
      <CardLabel>כמה אפשר להוציא</CardLabel>
      {safe == null ? (
        <BigNumber>—</BigNumber>
      ) : ok ? (
        <>
          <BigNumber tone="good">{shekel(safe)} פנוי עד המשכורת</BigNumber>
          {r.safe_per_day != null && r.days_to_payday != null && (
            <div className="mt-1 text-sm text-muted-foreground">
              {shekel(r.safe_per_day)} ליום · {r.days_to_payday} ימים
            </div>
          )}
        </>
      ) : (
        <>
          <BigNumber tone="bad">חסרים {shekel(-safe)} עד המשכורת</BigNumber>
          {r.headroom_to_limit != null && (
            <div className={`mt-1 text-sm font-semibold ${over ? "text-bad" : "text-warn"}`}>
              {over ? `חריגה מהמסגרת: ${shekel(-r.headroom_to_limit)}` : `מרווח עד סוף המסגרת: ${shekel(r.headroom_to_limit)}`}
            </div>
          )}
        </>
      )}
      <div className="mt-2 text-xs text-muted-foreground">
        {r.next_payday && `משכורת ${shortDate(r.next_payday.date)} · ${shekel(r.next_payday.amount)} · `}
        נכון ל-{shortDate(r.as_of)} · יתרה {shekel(r.start_balance)}
      </div>
    </Card>
  );
}

function RunwayChart({ r }: { r: RunwayData }) {
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
      <ResponsiveContainer width="100%" height={240}>
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

function Alerts({ r }: { r: RunwayData }) {
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

function EventRow({ e, limit }: { e: RunwayData["events"][number]; limit: number }) {
  const breach = e.balance_after < -Math.abs(limit);
  return (
    <div className="flex items-center gap-3 border-b border-line py-2.5 last:border-b-0">
      <span className="w-12 shrink-0 text-sm text-muted-foreground tabular-nums">{shortDate(e.date)}</span>
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="truncate">{e.name}</span>
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className="rounded-full bg-panel-2 px-2 py-0.5">{KIND_LABEL[e.kind] ?? e.kind}</span>
          {e.confidence === "inferred" && <span>משוער</span>}
        </span>
      </div>
      <div className="flex shrink-0 flex-col items-end">
        <strong className={`tabular-nums ${e.amount > 0 ? "text-good" : ""}`}>{shekelSigned(e.amount)}</strong>
        <span className={`text-xs tabular-nums ${breach ? "font-semibold text-bad" : "text-muted-foreground"}`}>
          {shekel(e.balance_after)}
        </span>
      </div>
    </div>
  );
}

export default function Runway() {
  const r = cashflow.runway;
  if (!r) {
    return (
      <div className="feed">
        <PageTitle>יתרה צפויה</PageTitle>
        <p className="muted">אין עדיין תחזית יתרה — הריצו את הפייפליין לעדכון.</p>
      </div>
    );
  }
  const buffer = r.liquid_buffer.reduce((a, b) => a + b.balance, 0);
  return (
    <div className="feed">
      <PageTitle>יתרה צפויה</PageTitle>
      <Hero r={r} />

      <Section title="מסלול היתרה">
        <Card>
          <RunwayChart r={r} />
        </Card>
      </Section>

      <Alerts r={r} />

      {r.events.length > 0 && (
        <Section title="תנועות קרובות">
          <Card>
            {r.events.map((e, i) => (
              <EventRow key={`${e.date}-${e.name}-${i}`} e={e} limit={r.overdraft_limit} />
            ))}
          </Card>
        </Section>
      )}

      {buffer > 0 && (
        <Card className="text-muted-foreground">
          יש {shekel(buffer)} בפיקדון נזיל — אפשר לכסות מכאן
        </Card>
      )}

      <p className="text-xs leading-relaxed text-muted-foreground">
        התחזית כוללת הוצאות קבועות בלבד (ללא הוצאות יומיומיות); חיובי האשראי מוערכים לפי החודש הקודם.
      </p>
    </div>
  );
}
