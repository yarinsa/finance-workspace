import { keyId, ledgerKey, type Row } from "./api";
import type { SpendingMonth, SpendingTransaction } from "./spending";

/** key ("date/abs_amount") -> the API's latest Row for that transaction. */
export type Overlay = ReadonlyMap<string, Row>;

/** The overlay row for a spending transaction, if the user edited it this session. */
export function overlayFor(overlay: Overlay, t: Pick<SpendingTransaction, "date" | "amount">): Row | undefined {
  return overlay.get(keyId(ledgerKey(t)));
}

/**
 * Apply not-yet-published edits on top of the static spending months, so the UI
 * reflects a PATCH immediately instead of after the rebuild:
 * - an excluded transaction leaves the list, its category, its merchant and the month total
 * - a re-categorised one moves its amount between categories
 * Percentages are recomputed and categories re-sorted. Months are returned as new
 * objects; the input is never mutated. With an empty overlay the input is returned as-is.
 */
export function applyOverlay(months: SpendingMonth[], overlay: Overlay): SpendingMonth[] {
  if (overlay.size === 0) return months;
  return months.map((m) => applyToMonth(m, overlay));
}

/** The overlay's tags win when the API returned them (an empty list clears them). */
function withTags(t: SpendingTransaction, o: Row): SpendingTransaction {
  return o.tags === undefined ? t : { ...t, tags: o.tags };
}

type Bucket = { name: string; amount: number; count: number };

function applyToMonth(m: SpendingMonth, overlay: Overlay): SpendingMonth {
  if (!m.transactions.some((t) => overlayFor(overlay, t))) return m;

  const cats = new Map(m.by_category.map((c) => [c.name, { ...c }]));
  const merchants = new Map(m.by_merchant.map((c) => [c.name, { ...c }]));
  let total = m.total;

  const take = (map: Map<string, Bucket>, name: string, amount: number) => {
    const e = map.get(name);
    if (!e) return;
    e.amount -= amount;
    e.count -= 1;
  };
  const give = (name: string, amount: number) => {
    const e = cats.get(name) ?? { name, amount: 0, pct: 0, count: 0 };
    e.amount += amount;
    e.count += 1;
    cats.set(name, e);
  };

  const transactions: SpendingTransaction[] = [];
  for (const t of m.transactions) {
    const o = overlayFor(overlay, t);
    if (!o) {
      transactions.push(t);
    } else if (o.excluded) {
      total -= t.amount;
      take(cats, t.category, t.amount);
      take(merchants, t.merchant, t.amount);
    } else if (o.category && o.category !== t.category) {
      take(cats, t.category, t.amount);
      give(o.category, t.amount);
      transactions.push(withTags({ ...t, category: o.category }, o));
    } else {
      transactions.push(withTags(t, o));
    }
  }

  const alive = (e: Bucket) => e.count > 0 && e.amount > 0.005;
  const by_category = [...cats.values()]
    .filter(alive)
    .map((c) => ({ ...c, pct: total > 0 ? (c.amount / total) * 100 : 0 }))
    .sort((a, b) => b.amount - a.amount);
  const by_merchant = [...merchants.values()].filter(alive).sort((a, b) => b.amount - a.amount);

  return { ...m, total, transactions, by_category, by_merchant };
}
