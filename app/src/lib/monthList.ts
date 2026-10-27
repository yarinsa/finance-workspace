import type { BillItem, Bills } from "./bills";
import type { BudgetCategory, Budgets } from "./budgets";
import type { FixedExpenses, FixedItem } from "./data";
import type { SpendingMonth, SpendingTransaction } from "./spending";

/** The month screen's sections, the same split as budgets.summary and months_view. */
export type SectionKey = "fixed" | "variable" | "debt_savings";

export const SECTION_LABEL: Record<SectionKey, string> = {
  fixed: "קבוע",
  variable: "משתנה",
  debt_savings: "הלוואות וחיסכון",
};

/** One fixed charge of the current cycle: a fixed-expense item and/or its bill status. */
export interface ChargeItem {
  name: string;
  category: string | null;
  amount: number;
  status?: BillItem["status"];
  due_day?: number | null;
  /** Amount is the median of the last bills (utility not charged yet). */
  estimated?: boolean;
  /** Monthly charge that has not hit yet (fixed_expenses). */
  expected?: boolean;
  duplicate?: boolean;
  duplicate_reason?: string | null;
  last_charged?: string | null;
  /** The "what can I cut?" lever of its fixed_expenses group (fees, subscriptions, …). */
  lever_key?: string;
  lever?: string;
}

/** Days without a charge after which a monthly service looks cancelled (bi-monthly bills are normal). */
const STALE_DAYS = 70;

const dayMonth = new Intl.DateTimeFormat("he-IL", {
  day: "numeric",
  month: "numeric",
});

/**
 * The one quiet saving hint for a fixed charge, or null: a duplicate service first,
 * then a service not charged for a while, then the easy lever of fees ("לבקש ויתור")
 * and subscriptions ("לבטל מה שלא בשימוש"). Bills, installments and debt get none.
 */
export function chargeHint(
  c: ChargeItem,
  today: Date = new Date(),
): string | null {
  if (c.duplicate)
    return `כפול${c.duplicate_reason ? ` · ${c.duplicate_reason}` : ""} — לבדוק אם אפשר לבטל אחד`;
  if (c.last_charged) {
    const at = new Date(`${c.last_charged}T12:00:00`);
    if ((today.getTime() - at.getTime()) / 864e5 > STALE_DAYS)
      return `לא חויב מאז ${dayMonth.format(at)} — אולי בוטל?`;
  }
  if ((c.lever_key === "fees" || c.lever_key === "subscriptions") && c.lever)
    return c.lever;
  return null;
}

/** A row of the list: a category (with its transactions) or, for fixed/debt in the current cycle, a charge. */
export interface Line {
  key: string;
  section: SectionKey;
  group: string;
  /** Display name: the category, the budget line or the charge. */
  name: string;
  /** Category the sheet filters on; null for the savings line. */
  category: string | null;
  /** A group-scope budget line (תחבורה) filters on the group instead. */
  scope: "category" | "group";
  /** ₪ actually spent this month (net of offsets). */
  amount: number;
  budget?: BudgetCategory;
  charge?: ChargeItem;
}

export interface GroupBlock {
  name: string;
  total: number;
  lines: Line[];
  /** Holds an over-budget line or an overdue charge: shown open by default. */
  alert: boolean;
}

export interface SectionBlock {
  key: SectionKey;
  label: string;
  /** Σ of the lines' amounts. */
  total: number;
  groups: GroupBlock[];
}

const OTHER_GROUP = "אחר";

/** ₪ a spending row counts for after paybacks (קיזוז). */
export const net = (t: SpendingTransaction) => t.amount - (t.offset ?? 0);

const sectionOf = (t: SpendingTransaction): SectionKey =>
  t.block ?? (t.kind as SectionKey | undefined) ?? "variable";

/** The month's transactions behind a line (newest first). */
export function lineTransactions(
  m: SpendingMonth | undefined,
  line: Pick<Line, "section" | "category" | "scope" | "group">,
) {
  if (!m || !line.category) return [];
  return m.transactions
    .filter((t) => {
      if (line.scope === "group")
        return (
          sectionOf(t) === line.section &&
          (t.group ?? OTHER_GROUP) === line.category
        );
      // a charge's sheet shows its whole category, in any section
      return (
        t.category === line.category &&
        (line.section === "variable" ? sectionOf(t) === "variable" : true)
      );
    })
    .sort((a, b) => b.date.localeCompare(a.date));
}

/** Pair each fixed-expense item with the bill of the same name (and roughly the same amount). */
export function mergeCharges(
  fixed: (FixedItem & { lever_key?: string; lever?: string })[],
  bills: BillItem[],
): (ChargeItem & { group: string | null; loan: boolean })[] {
  const left = [...bills];
  const out: (ChargeItem & { group: string | null; loan: boolean })[] = [];
  for (const f of fixed) {
    const i = left.findIndex(
      (b) =>
        b.name === f.name &&
        Math.abs(b.amount - f.amount) <= Math.max(f.amount * 0.15, 2),
    );
    const b = i >= 0 ? left.splice(i, 1)[0] : undefined;
    out.push({
      name: f.name,
      category: f.category ?? null,
      amount: f.amount,
      expected: f.expected,
      duplicate: f.duplicate,
      duplicate_reason: f.duplicate_reason,
      last_charged: f.last_charged,
      lever_key: f.lever_key,
      lever: f.lever,
      status: b?.status ?? (f.expected ? "upcoming" : "paid"),
      due_day: b?.due_day,
      estimated: b?.estimated,
      group: f.group ?? b?.group ?? null,
      loan: f.block === "debt_savings" || b?.kind === "loan",
    });
  }
  for (const b of left) {
    out.push({
      name: b.name,
      category: b.category,
      amount: b.amount,
      status: b.status,
      due_day: b.due_day,
      estimated: b.estimated,
      group: b.group ?? null,
      loan: b.kind === "loan",
    });
  }
  return out;
}

export interface MonthListInput {
  month?: SpendingMonth;
  /** Current-cycle blocks; pass only for the cycle they describe. */
  budgets?: Budgets | null;
  bills?: Bills | null;
  fixed?: FixedExpenses | null;
}

/**
 * The month as sections → category groups → lines. Categories come from the month's
 * transactions; in the current cycle variable lines are the budget lines (bars) and
 * fixed / debt lines are the cycle's charges with their bill status. Any block that is
 * missing (a past month) just falls back to the plain category lines.
 */
export function buildMonthList({
  month,
  budgets,
  bills,
  fixed,
}: MonthListInput): SectionBlock[] {
  const lines: Line[] = [];
  const txs = month?.transactions ?? [];

  // Plain category lines per section, from the transactions themselves.
  const sums = new Map<string, Line>();
  for (const t of txs) {
    const section = sectionOf(t);
    const key = `${section}|${t.category}`;
    const l = sums.get(key) ?? {
      key,
      section,
      group: t.group ?? OTHER_GROUP,
      name: t.category,
      category: t.category,
      scope: "category" as const,
      amount: 0,
    };
    l.amount += net(t);
    sums.set(key, l);
  }

  const charges =
    fixed || bills
      ? mergeCharges(
          fixed?.groups.flatMap((g) =>
            g.items.map((i) => ({ ...i, lever_key: g.key, lever: g.lever })),
          ) ?? [],
          bills?.items ?? [],
        )
      : null;
  if (charges) {
    for (const [i, c] of charges.entries()) {
      const section: SectionKey = c.loan ? "debt_savings" : "fixed";
      lines.push({
        key: `charge|${i}|${c.name}`,
        section,
        group: c.group ?? OTHER_GROUP,
        name: c.name,
        category: c.category,
        scope: "category",
        amount: c.amount,
        charge: c,
      });
    }
    // kindless debt rows (pension debits) and savings are not charges: keep their category lines
    for (const l of sums.values()) {
      if (
        l.section === "debt_savings" &&
        !charges.some((c) => c.loan && c.category === l.category)
      )
        lines.push(l);
    }
  } else {
    for (const l of sums.values()) if (l.section !== "variable") lines.push(l);
  }

  if (budgets?.categories.length) {
    const covered = new Set<string>();
    for (const b of budgets.categories) {
      lines.push({
        key: `budget|${b.name}`,
        section: "variable",
        group: b.group ?? (b.scope === "group" ? b.name : OTHER_GROUP),
        name: b.name,
        category: b.name,
        scope: b.scope ?? "category",
        amount: b.spent,
        budget: b,
      });
      covered.add(b.scope === "group" ? `g|${b.name}` : b.name);
    }
    for (const l of sums.values()) {
      if (
        l.section === "variable" &&
        !covered.has(l.name) &&
        !covered.has(`g|${l.group}`)
      )
        lines.push(l);
    }
  } else {
    for (const l of sums.values()) if (l.section === "variable") lines.push(l);
  }

  const savings = month?.excluded.savings;
  if (savings && savings.amount > 0) {
    lines.push({
      key: "savings",
      section: "debt_savings",
      group: "חיסכון",
      name: "חיסכון והפקדות",
      category: null,
      scope: "category",
      amount: savings.amount,
    });
  }

  const order: SectionKey[] = ["fixed", "variable", "debt_savings"];
  return order
    .map((key) => {
      const groups = new Map<string, GroupBlock>();
      for (const l of lines.filter(
        (x) => x.section === key && (x.amount > 0.005 || x.budget || x.charge),
      )) {
        const g = groups.get(l.group) ?? {
          name: l.group,
          total: 0,
          lines: [],
          alert: false,
        };
        g.lines.push(l);
        g.total += l.amount;
        if (l.budget?.over || l.charge?.status === "overdue") g.alert = true;
        groups.set(l.group, g);
      }
      const list = [...groups.values()];
      for (const g of list) g.lines.sort((a, b) => b.amount - a.amount);
      list.sort((a, b) => b.total - a.total);
      return {
        key,
        label: SECTION_LABEL[key],
        total: list.reduce((s, g) => s + g.total, 0),
        groups: list,
      };
    })
    .filter((s) => s.groups.length > 0);
}

/** Merchant totals of the month's (overlaid) transactions, biggest first. */
export function byMerchant(m: SpendingMonth | undefined) {
  const map = new Map<
    string,
    { name: string; amount: number; count: number }
  >();
  for (const t of m?.transactions ?? []) {
    const e = map.get(t.merchant) ?? { name: t.merchant, amount: 0, count: 0 };
    e.amount += net(t);
    e.count += 1;
    map.set(t.merchant, e);
  }
  return [...map.values()].sort((a, b) => b.amount - a.amount);
}

/** The line a `?category=` deep link names (budget line first, then a category or charge). */
export function findLine(
  sections: SectionBlock[],
  name: string,
): { section: SectionKey; group: string; line: Line } | null {
  const all = sections.flatMap((s) =>
    s.groups.flatMap((g) =>
      g.lines.map((line) => ({ section: s.key, group: g.name, line })),
    ),
  );
  return (
    all.find((x) => x.line.budget?.name === name) ??
    all.find((x) => x.line.category === name && !x.line.charge) ??
    all.find((x) => x.line.category === name || x.line.name === name) ??
    null
  );
}
