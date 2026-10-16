import { TransactionList, TransactionRow } from "@/components/TransactionRow";
import { useSearchParams } from "react-router-dom";
import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";
import { BarRow, Card, PageTitle } from "@/components/common";
import ExcludedSpendingCard from "@/components/ExcludedSpendingCard";
import { noAnim, useChartColors } from "@/components/chartTheme";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import TransactionEditSheet, { type EditTarget } from "@/components/TransactionEditSheet";
import HiddenTransactionsSheet from "@/components/HiddenTransactionsSheet";
import { Input } from "@/components/ui/input";
import { cashflow, monthYear, pct, shekel, useDataVersion } from "@/lib/data";
import { applyOverlay, overlayFor } from "@/lib/ledgerOverlay";
import { useLedgerApi } from "@/lib/useLedgerApi";

/** Case-insensitive match on merchant name, or on the amount's digits ("120" finds ₪1,205.50). */
function matchesQuery(t: { merchant: string; amount: number }, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  if (t.merchant.toLowerCase().includes(q)) return true;
  const digits = q.replace(/[^\d.]/g, "");
  return digits !== "" && String(Math.abs(t.amount)).includes(digits);
}

/** Month spending explorer (PRD 12 Phase 3): donut, transactions / categories / merchants. */
export default function Spending() {
  const C = useChartColors();
  useDataVersion(); // re-render when a published rebuild is re-fetched
  const { overlay, updating, rebuild } = useLedgerApi();
  const [editing, setEditing] = useState<EditTarget | null>(null);
  const [hiddenOpen, setHiddenOpen] = useState(false);
  const spending = cashflow.spending;
  const months = useMemo(() => applyOverlay(spending?.months ?? [], overlay), [spending, overlay]);
  // ?month=YYYY-MM&cat=<name> deep-links from the cashflow screen.
  const [params] = useSearchParams();
  const linked = (spending?.months ?? []).findIndex((m) => m.month === params.get("month"));
  const [idx, setIdx] = useState(linked >= 0 ? linked : 0); // 0 = newest month
  const [tab, setTab] = useState("transactions");
  const [cat, setCat] = useState<string | null>(params.get("cat"));
  const [merchant, setMerchant] = useState<string | null>(null);
  const [tag, setTag] = useState<string | null>(params.get("tag"));
  const [query, setQuery] = useState("");

  if (!months.length) {
    return (
      <div className="space-y-4">
        <PageTitle>הוצאות החודש</PageTitle>
        <Card>
          <div className="text-muted-foreground">אין נתוני הוצאות עדיין. הריצו את הפייפליין ופרסמו מחדש.</div>
        </Card>
      </div>
    );
  }

  const m = months[idx];
  const palette = [C.accent, "#1d3b6e", C.warn, "#8b7cf6", C.bad, C.good, "#e879a9"];
  const color = (i: number) => palette[i % palette.length];
  const catColor = (name: string) => {
    const i = m.by_category.findIndex((c) => c.name === name);
    return i < 0 ? C.muted : color(i);
  };
  const selected = cat ? m.by_category.find((c) => c.name === cat) ?? null : null;
  const txs = m.transactions.filter(
    (t) =>
      (!selected || t.category === selected.name) &&
      (!merchant || t.merchant === merchant) &&
      (!tag || (t.tags ?? []).includes(tag)) &&
      matchesQuery(t, query),
  );
  const maxCat = m.by_category[0]?.amount || 1;
  const maxMerchant = m.by_merchant[0]?.amount || 1;

  const go = (d: number) => {
    setIdx((i) => Math.min(months.length - 1, Math.max(0, i + d)));
    setCat(null);
    setMerchant(null);
  };
  const tagTotal = tag ? txs.reduce((s, t) => s + t.amount, 0) : 0;
  const pickMerchant = (name: string) => {
    setMerchant(name);
    setCat(null);
    setTab("transactions");
  };
  const pick = (name: string) => {
    setCat((c) => (c === name ? null : name));
    setMerchant(null);
    setTab("transactions");
  };

  const delta = m.vs_prev;
  const deltaText =
    delta == null
      ? null
      : delta === 0
        ? "זהה לחודש הקודם"
        : `${shekel(Math.abs(delta))} ${delta < 0 ? "פחות" : "יותר"} מהחודש הקודם`;

  return (
    <div className="space-y-4 md:space-y-[18px]">
      <div className="flex items-center justify-between gap-2">
        <PageTitle>הוצאות החודש</PageTitle>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          {updating ? <span>מתעדכן…</span> : rebuild.last_error ? <span className="text-bad">העדכון נכשל</span> : null}
          <button type="button" className="underline" onClick={() => setHiddenOpen(true)}>
            מוסתרות
          </button>
        </div>
      </div>

      <Card>
        <div className="mb-3 flex items-center justify-between">
          {/* RTL: "previous" sits on the right, so the right chevron goes back in time. */}
          <button
            type="button"
            aria-label="חודש קודם"
            disabled={idx >= months.length - 1}
            onClick={() => go(1)}
            className="rounded-full p-2 text-muted-foreground disabled:opacity-30"
          >
            <ChevronRight className="size-5" />
          </button>
          <div className="text-center">
            <div className="font-semibold">
              {monthYear(`${m.month}-01`)}
              {m.partial ? " · עד היום" : ""}
            </div>
            <div className="text-sm text-muted-foreground">
              <strong className="tabular-nums text-foreground">{shekel(m.total)}</strong>
              {deltaText ? (
                <>
                  {" · "}
                  <span style={{ color: delta! < 0 ? C.good : C.bad }}>{deltaText}</span>
                </>
              ) : null}
            </div>
          </div>
          <button
            type="button"
            aria-label="חודש הבא"
            disabled={idx <= 0}
            onClick={() => go(-1)}
            className="rounded-full p-2 text-muted-foreground disabled:opacity-30"
          >
            <ChevronLeft className="size-5" />
          </button>
        </div>

        {m.by_category.length ? (
          <div className="flex items-center gap-4">
            <div className="relative w-[150px] shrink-0">
              <ResponsiveContainer width="100%" height={150}>
                <PieChart>
                  <Pie
                    data={m.by_category}
                    dataKey="amount"
                    nameKey="name"
                    innerRadius="62%"
                    outerRadius="100%"
                    paddingAngle={2}
                    stroke="none"
                    onClick={(d) => pick((d as unknown as { name: string }).name)}
                    {...noAnim}
                  >
                    {m.by_category.map((c, i) => (
                      <Cell
                        key={c.name}
                        fill={color(i)}
                        fillOpacity={selected && selected.name !== c.name ? 0.3 : 1}
                        style={{ cursor: "pointer", outline: "none" }}
                      />
                    ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
                <span className="max-w-[80px] truncate text-[11px] text-muted-foreground">
                  {selected ? selected.name : "סה״כ"}
                </span>
                <strong className="text-[15px] tabular-nums">{shekel(selected ? selected.amount : m.total)}</strong>
                {selected ? (
                  <span className="text-[11px] text-muted-foreground">{pct(selected.pct)} מהחודש</span>
                ) : null}
              </div>
            </div>
            <ul className="flex min-w-0 flex-1 flex-col gap-1.5">
              {m.by_category.slice(0, 6).map((c, i) => (
                <li key={c.name}>
                  <button
                    type="button"
                    onClick={() => pick(c.name)}
                    className={`flex w-full items-center gap-2 text-start text-[13px] ${
                      selected && selected.name !== c.name ? "opacity-50" : ""
                    }`}
                  >
                    <i className="size-[9px] shrink-0 rounded-[3px]" style={{ background: color(i) }} />
                    <span className="min-w-0 flex-1 truncate">{c.name}</span>
                    <span className="text-muted-foreground">{pct(c.pct)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <div className="text-muted-foreground">אין הוצאות בחודש הזה.</div>
        )}
      </Card>

      <Card>
        <Tabs value={tab} onValueChange={setTab} dir="rtl">
          <TabsList className="w-full">
            <TabsTrigger value="transactions">תנועות</TabsTrigger>
            <TabsTrigger value="categories">קטגוריות</TabsTrigger>
            <TabsTrigger value="merchants">בתי עסק</TabsTrigger>
          </TabsList>

          <TabsContent value="transactions">
            <Input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="חיפוש בית עסק או סכום"
              aria-label="חיפוש תנועות"
              className="mb-2"
            />
            {tag ? (
              <button
                type="button"
                onClick={() => setTag(null)}
                className="mb-2 me-1.5 rounded-full border border-brand/40 px-3 py-1 text-xs text-brand"
              >
                #{tag} · {shekel(tagTotal)} ✕
              </button>
            ) : null}
            {selected || merchant ? (
              <button
                type="button"
                onClick={() => {
                  setCat(null);
                  setMerchant(null);
                }}
                className="mb-2 rounded-full bg-panel-2 px-3 py-1 text-xs"
              >
                {selected?.name ?? merchant} ✕
              </button>
            ) : null}
            {txs.length === 0 ? (
              <div className="py-3 text-muted-foreground">אין תנועות.</div>
            ) : (
              <TransactionList>
                {txs.map((t, i) => (
                  <TransactionRow
                    key={`${t.date}-${i}`}
                    merchant={t.merchant}
                    amount={-t.amount}
                    date={t.date}
                    category={t.category}
                    tags={t.tags}
                    onPickTag={setTag}
                    dotColor={catColor(t.category)}
                    edited={t.overridden || overlayFor(overlay, t)?.overridden}
                    onClick={() => setEditing(t)}
                  />
                ))}
              </TransactionList>
            )}
          </TabsContent>

          <TabsContent value="categories">
            {m.by_category.map((c) => (
              <button key={c.name} type="button" onClick={() => pick(c.name)} className="block w-full text-start">
                <BarRow
                  label={`${c.name} · ${pct(c.pct)}`}
                  value={shekel(c.amount)}
                  fraction={c.amount / maxCat}
                />
              </button>
            ))}
          </TabsContent>

          <TabsContent value="merchants">
            {m.by_merchant.map((x) => (
              <button key={x.name} type="button" onClick={() => pickMerchant(x.name)} className="block w-full text-start">
                <BarRow
                  label={x.count > 1 ? `${x.name} ×${x.count}` : x.name}
                  value={shekel(x.amount)}
                  fraction={x.amount / maxMerchant}
                />
              </button>
            ))}
          </TabsContent>
        </Tabs>
      </Card>

      <ExcludedSpendingCard excluded={m.excluded} />
      <TransactionEditSheet tx={editing} onClose={() => setEditing(null)} />
      <HiddenTransactionsSheet open={hiddenOpen} onClose={() => setHiddenOpen(false)} />
    </div>
  );
}
