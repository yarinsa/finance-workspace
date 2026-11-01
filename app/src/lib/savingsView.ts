import type { Horizon } from "./api";
import { overlayFor, type Overlay } from "./ledgerOverlay";
import type { PersonalGoal, Savings } from "./data";
import { addDays, type LedgerRow } from "./transactionsView";

/** The ledger category the scrapers use for money moved into or out of savings. */
export const SAVINGS_CATEGORY = "השקעה וחיסכון";

/** A holding unlocking within this many days is "current"; within NEAR_DAYS it is "near"; later is "future". */
export const CURRENT_DAYS = 365;
export const NEAR_DAYS = 5 * 365;

export const HORIZONS: readonly Horizon[] = ["current", "near", "future"];

export const KIND_LABEL: Record<string, string> = {
  pension: "פנסיה",
  study_fund: "קרן השתלמות",
  provident_fund: "קופת גמל",
  savings: "חיסכון",
  bank_deposit: "פיקדון",
};

export type SavingsGroupBy = "horizon" | "goal" | "kind" | "institution";

export function parseSavingsGroup(raw: string | null | undefined): SavingsGroupBy {
  return raw === "goal" || raw === "kind" || raw === "institution" ? raw : "horizon";
}

/**
 * The horizon a holding falls in, from when it can be withdrawn. Liquid money and a date already
 * past are current. No date means no answer: the user assigns it, never a guess.
 */
export function deriveHorizon(h: Pick<Savings, "liquid"> & { liquidity_date?: string | null }, today: string): Horizon | null {
  if (h.liquid) return "current";
  const date = h.liquidity_date?.slice(0, 10);
  if (!date) return null;
  if (date <= addDays(today, CURRENT_DAYS)) return "current";
  return date <= addDays(today, NEAR_DAYS) ? "near" : "future";
}

/** A fund or deposit with a balance: an asset as of `asOf`, not cashflow. */
export interface HoldingRow {
  type: "holding";
  id: string;
  institution: string;
  kind: string;
  label: string;
  balance: number;
  liquid: boolean;
  liquidityDate: string | null;
  asOf: string | null;
  horizon: Horizon | null;
  /** "derived" from the liquidity date; "manual" once the user assigns it. */
  horizonSource: "derived" | "manual" | null;
  goalId: number | null;
}

/** Money moved into (positive `flow`) or out of savings, from the ledger. */
export interface MovementRow {
  type: "movement";
  date: string;
  /** Into savings positive, out negative: the reverse of the ledger's sign. */
  flow: number;
  description: string;
  origin: string;
  horizon: Horizon | null;
  goalId: number | null;
  edited: boolean;
  /** The ledger amount, so the row can open the transaction edit sheet. */
  amount: number;
}

export type SavingsRow = HoldingRow | MovementRow;

/** Stable id of a holding: its institution and the vendor's topic id, else its label. */
export const holdingId = (s: Pick<Savings, "institution" | "label"> & { topic_id?: string | null }): string =>
  `${s.institution}:${s.topic_id ?? s.label}`;

/** Holdings with their derived horizon; `manual` (holding id → horizon / goal) wins when present. */
export function holdingRows(
  savings: readonly (Savings & { topic_id?: string | null; as_of?: string | null; liquidity_date?: string | null })[],
  today: string,
  manual: ReadonlyMap<string, { horizon?: Horizon | null; goalId?: number | null }> = new Map(),
): HoldingRow[] {
  return savings.map((s) => {
    const id = holdingId(s);
    const m = manual.get(id);
    const derived = deriveHorizon(s, today);
    const horizon = m?.horizon !== undefined ? m.horizon : derived;
    return {
      type: "holding",
      id,
      institution: s.institution,
      kind: s.kind,
      label: s.label,
      balance: s.balance,
      liquid: !!s.liquid,
      liquidityDate: s.liquidity_date?.slice(0, 10) ?? null,
      asOf: s.as_of?.slice(0, 10) ?? null,
      horizon,
      horizonSource: m?.horizon !== undefined ? "manual" : derived ? "derived" : null,
      goalId: m?.goalId ?? null,
    };
  });
}

/**
 * Savings movements: ledger rows in the savings category. The live overlay can move a row to
 * another horizon or goal, or exclude it; card-bill payments and internal transfers never count.
 */
export function movementRows(rows: readonly LedgerRow[], overlay: Overlay): MovementRow[] {
  const out: MovementRow[] = [];
  for (const t of rows) {
    if (t.card_bill_payment || t.internal_transfer) continue;
    const o = overlayFor(overlay, t);
    if (o?.excluded) continue;
    if ((o?.category || t.category) !== SAVINGS_CATEGORY) continue;
    const ledgerHorizon = (t as { horizon?: Horizon | null }).horizon ?? null;
    out.push({
      type: "movement",
      date: t.date.slice(0, 10),
      flow: -t.amount,
      amount: t.amount,
      description: t.description ?? t.merchant ?? "—",
      origin: t.origin ?? "other",
      horizon: o?.horizon !== undefined ? o.horizon ?? null : ledgerHorizon,
      goalId: o?.goal_id ?? null,
      edited: o ? o.overridden : !!t.overridden,
    });
  }
  return out;
}

/** Movements in the inclusive window, newest first. */
export function movementsInRange(rows: readonly MovementRow[], range: { from: string; to: string }): MovementRow[] {
  return rows.filter((m) => m.date >= range.from && m.date <= range.to).sort((a, b) => b.date.localeCompare(a.date));
}

export interface SavingsGroup {
  key: string;
  label: string;
  holdings: HoldingRow[];
  movements: MovementRow[];
  /** Sum of holding balances: a stock, as of each holding's `asOf`. */
  balance: number;
  /** Net money moved in within the window: a flow. */
  flow: number;
  liquid: number;
  illiquid: number;
  /** Set on goal groups: the goal the header reports progress for. */
  goal?: PersonalGoal;
}

export const HORIZON_ORDER_LABEL: Record<Horizon | "none", string> = {
  current: "עכשיו",
  near: "בקרוב",
  future: "פרישה",
  none: "לא משויך",
};

function newGroup(key: string, label: string, goal?: PersonalGoal): SavingsGroup {
  return { key, label, holdings: [], movements: [], balance: 0, flow: 0, liquid: 0, illiquid: 0, goal };
}

/** Groups holdings and movements together. Empty groups are dropped; "none" goes last. */
export function groupSavings(
  holdings: readonly HoldingRow[],
  movements: readonly MovementRow[],
  by: SavingsGroupBy,
  opts: { goals?: readonly PersonalGoal[]; institutionLabel?: (institution: string) => string } = {},
): SavingsGroup[] {
  const groups = new Map<string, SavingsGroup>();
  const goalById = new Map((opts.goals ?? []).filter((g) => g.goal_id != null).map((g) => [g.goal_id as number, g]));
  const ensure = (key: string, label: string, goal?: PersonalGoal) => {
    let g = groups.get(key);
    if (!g) groups.set(key, (g = newGroup(key, label, goal)));
    return g;
  };

  if (by === "horizon") for (const h of HORIZONS) ensure(h, HORIZON_ORDER_LABEL[h]);
  if (by === "goal") for (const g of goalById.values()) ensure(String(g.goal_id), g.description, g);

  const place = (row: SavingsRow): SavingsGroup => {
    if (by === "horizon") return ensure(row.horizon ?? "none", HORIZON_ORDER_LABEL[row.horizon ?? "none"]);
    if (by === "goal") {
      const g = row.goalId != null ? goalById.get(row.goalId) : undefined;
      return g ? ensure(String(g.goal_id), g.description, g) : ensure("none", "ללא יעד");
    }
    if (by === "kind") {
      const kind = row.type === "holding" ? row.kind : "movement";
      return ensure(kind, kind === "movement" ? "הפקדות ומשיכות" : (KIND_LABEL[kind] ?? kind));
    }
    const inst = row.type === "holding" ? row.institution : row.origin;
    return ensure(inst, opts.institutionLabel?.(inst) ?? inst);
  };

  for (const h of holdings) {
    const g = place(h);
    g.holdings.push(h);
    g.balance += h.balance;
    if (h.liquid) g.liquid += h.balance;
    else g.illiquid += h.balance;
  }
  for (const m of movements) {
    const g = place(m);
    g.movements.push(m);
    g.flow += m.flow;
  }
  return [...groups.values()]
    .filter((g) => g.holdings.length > 0 || g.movements.length > 0 || by === "horizon" || (by === "goal" && g.goal))
    .sort((a, b) => Number(a.key === "none") - Number(b.key === "none"));
}

export interface SavingsStats {
  balance: number;
  liquid: number;
  illiquid: number;
  /** Net money moved in within the window. */
  flow: number;
  /** The earliest liquidity date of a locked holding, with what unlocks then. */
  nextUnlock: { date: string; amount: number } | null;
  /** The newest `asOf` among the holdings. */
  asOf: string | null;
}

export function savingsStats(holdings: readonly HoldingRow[], movements: readonly MovementRow[]): SavingsStats {
  let liquid = 0;
  let illiquid = 0;
  let asOf: string | null = null;
  const unlocks = new Map<string, number>();
  for (const h of holdings) {
    if (h.liquid) liquid += h.balance;
    else {
      illiquid += h.balance;
      if (h.liquidityDate) unlocks.set(h.liquidityDate, (unlocks.get(h.liquidityDate) ?? 0) + h.balance);
    }
    if (h.asOf && (!asOf || h.asOf > asOf)) asOf = h.asOf;
  }
  const first = [...unlocks.keys()].sort()[0];
  return {
    balance: liquid + illiquid,
    liquid,
    illiquid,
    flow: movements.reduce((s, m) => s + m.flow, 0),
    nextUnlock: first ? { date: first, amount: unlocks.get(first)! } : null,
    asOf,
  };
}
