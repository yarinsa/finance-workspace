import { TransactionList, TransactionRow } from "@/components/TransactionRow";
import { useState } from "react";
import { BigNumber, Card, CardLabel, Section } from "@/components/common";
import TransactionEditSheet, { HORIZON_LABEL, type EditTarget } from "@/components/TransactionEditSheet";
import { useQuickEdit } from "@/components/QuickEditSheets";
import type { Horizon } from "@/lib/api";
import { cashflow, shekel, type Horizons as HorizonsData } from "@/lib/data";

type Month = HorizonsData["months"][number];

const monthName = (ym: string) =>
  new Intl.DateTimeFormat("he-IL", { month: "long", year: "numeric" }).format(new Date(`${ym}-15T12:00:00`));

const BAR: Record<Horizon | "unallocated", string> = {
  current: "bg-brand",
  near: "bg-warn",
  future: "bg-good",
  unallocated: "bg-muted-foreground/40",
};

/** Within ±5 points of target counts as on track. */
const ON_TRACK = 5;

/** The biggest miss this month, as one sentence. */
function verdict(m: Month, target: number, order: Horizon[]): { text: string; ok: boolean } {
  if (m.income <= 0) return { text: "עדיין אין הכנסה החודש, אז אין חלוקה להשוות", ok: true };
  const gapOf = (h: Horizon) => m.buckets[h].gap_pts ?? 0;
  const worst = order.reduce((a, b) => (Math.abs(gapOf(b)) > Math.abs(gapOf(a)) ? b : a));
  const gap = gapOf(worst);
  if (Math.abs(gap) <= ON_TRACK) return { text: "החלוקה קרובה ליעד", ok: true };
  const pts = Math.abs(gap).toFixed(0);
  const amount = shekel((Math.abs(gap) / 100) * m.income);
  return gap > 0
    ? { text: `${HORIZON_LABEL[worst]} מקבל ${pts} נק׳ מעל ${target}% (${amount})`, ok: false }
    : { text: `${HORIZON_LABEL[worst]} חסר ${pts} נק׳ מתחת ל-${target}% (${amount})`, ok: false };
}

/** One stacked bar of the month: each bucket's share of net income, target marks at 33/67/100. */
function SplitBar({ m, order }: { m: Month; order: Horizon[] }) {
  const parts = [...order.map((h) => [h, m.buckets[h].pct ?? 0] as const), ["unallocated", m.unallocated.pct ?? 0] as const];
  const total = Math.max(100, parts.reduce((s, [, p]) => s + Math.max(0, p), 0));
  return (
    <div className="relative mt-3 flex h-3 overflow-hidden rounded-full bg-panel-2" dir="ltr">
      {parts.map(([k, p]) => (
        <div key={k} className={BAR[k]} style={{ width: `${(Math.max(0, p) / total) * 100}%` }} />
      ))}
      {[1, 2, 3].map((i) => (
        <div
          key={i}
          className="absolute inset-y-0 w-px bg-foreground/60"
          style={{ left: `${((i * 100) / 3 / total) * 100}%` }}
        />
      ))}
    </div>
  );
}

const editTarget = (t: { date: string; amount: number; description: string; category?: string | null; overridden?: boolean; tags?: string[] }): EditTarget => ({
  date: t.date,
  amount: t.amount,
  merchant: t.description,
  category: t.category ?? "",
  overridden: t.overridden,
  tags: t.tags,
});

/** The income split across today / near / retirement, as one section of the plan hub. */
export default function Horizons() {
  const data = cashflow.horizons;
  const [idx, setIdx] = useState(0);
  const [editing, setEditing] = useState<EditTarget | null>(null);
  const { swipeProps, sheets } = useQuickEdit();

  if (!data || data.months.length === 0) {
    return (
      <Section title="היום · קרוב · פרישה">
        <Card>אין עדיין נתוני חלוקה. הריצו את ה-digest כדי ליצור אותם.</Card>
      </Section>
    );
  }

  const order = data.horizons;
  const target = data.target_pct;
  const m = data.months[Math.min(idx, data.months.length - 1)];
  const future = m.buckets.future;
  const v = verdict(m, target, order);

  return (
    <Section title="היום · קרוב · פרישה">
      <div className="flex flex-col gap-5 md:gap-6">
      {data.months.length > 1 && (
        <div className="flex gap-1.5 overflow-x-auto">
          {data.months.map((x, i) => (
            <button
              key={x.month}
              type="button"
              onClick={() => setIdx(i)}
              className={`shrink-0 rounded-full border px-3 py-1 text-sm ${
                i === idx ? "border-brand bg-brand/15 font-semibold" : "border-line"
              }`}
            >
              {monthName(x.month)}
            </button>
          ))}
        </div>
      )}

      <Card className="h-auto">
        <CardLabel>לאני של העתיד (פרישה) · יעד {target}%</CardLabel>
        <BigNumber tone={Math.abs(future.gap_pts ?? 0) <= ON_TRACK ? "good" : "bad"}>{future.pct == null ? "—" : `${future.pct.toFixed(0)}% מההכנסה`}</BigNumber>
        <div className={`mt-1 text-sm font-semibold ${v.ok ? "text-good" : "text-warn"}`}>{v.text}</div>
        <SplitBar m={m} order={order} />
        <div className="mt-2 text-xs text-muted-foreground">
          הכנסה נטו {shekel(m.income)} · {monthName(m.month)} · קווים = שליש, שני שלישים, 100%
        </div>
      </Card>

      <Section title="החלוקה">
        <Card className="h-auto">
          {[...order, "unallocated" as const].map((k) => {
            const b = k === "unallocated" ? null : m.buckets[k];
            const pct = b ? b.pct : m.unallocated.pct;
            const gap = b?.gap_pts ?? null;
            const amount = b ? b.amount : m.unallocated.amount;
            return (
              <div key={k} className="flex items-center gap-3 border-line py-2 [&+&]:border-t">
                <span className={`size-2.5 shrink-0 rounded-full ${BAR[k]}`} />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-semibold">{k === "unallocated" ? "לא מוקצה" : HORIZON_LABEL[k]}</div>
                  <div className="text-xs text-muted-foreground tabular-nums">
                    {shekel(amount)}
                    {b && ` · ${b.count} תנועות`}
                  </div>
                </div>
                <div className="text-end tabular-nums">
                  <div className="text-sm font-semibold">{pct == null ? "—" : `${pct.toFixed(1)}%`}</div>
                  {gap != null && (
                    <div className={`text-xs ${Math.abs(gap) <= ON_TRACK ? "text-good" : "text-warn"}`}>
                      {gap > 0 ? "+" : ""}
                      {gap.toFixed(1)} נק׳ מהיעד
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </Card>
      </Section>

      {order.map((h) => (
        <Section key={h} title={HORIZON_LABEL[h]}>
          <div className="flex flex-col gap-4 md:gap-[18px]">
            {(data.goals?.[h]?.length ?? 0) > 0 && (
              <Card className="h-auto">
                <CardLabel>יעדים</CardLabel>
                {data.goals![h].map((g) => (
                  <div key={g.id} className="flex items-center gap-3 border-line py-1.5 [&+&]:border-t">
                    <div className="min-w-0 flex-1 truncate text-sm">{g.description}</div>
                    {g.end_date && (
                      <div className="text-xs text-muted-foreground">
                        עד {g.end_date.split("-").reverse().slice(1).join("/")}
                      </div>
                    )}
                    <div className="text-sm font-semibold tabular-nums">{shekel(g.amount)}</div>
                  </div>
                ))}
              </Card>
            )}
            <Card>
              {m.buckets[h].top.length === 0 ? (
                <div className="text-sm text-muted-foreground">אין תנועות החודש. סמנו תנועה כ״{HORIZON_LABEL[h]}״ בעריכה.</div>
              ) : (
                <TransactionList>
                  {m.buckets[h].top.map((t) => (
                    <TransactionRow
                      key={`${t.date}/${t.amount}/${t.description}`}
                      merchant={t.description}
                      amount={t.amount}
                      date={t.date}
                      category={t.category}
                      tags={t.tags}
                      meta={t.goal || undefined}
                      edited={t.overridden}
                      offset={t.offset}
                      onClick={() => setEditing(editTarget(t))}
                      {...swipeProps(editTarget(t), t.amount)}
                    />
                  ))}
                </TransactionList>
              )}
            </Card>
          </div>
        </Section>
      ))}

      <TransactionEditSheet tx={editing} onClose={() => setEditing(null)} />
      {sheets}
      </div>
    </Section>
  );
}
