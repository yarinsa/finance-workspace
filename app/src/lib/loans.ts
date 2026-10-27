// Pure loan breakdown logic for LoanDetails (no data fetch, so it is testable).
import type { Loan } from "./data";

/**
 * A loan's effective rate. Discount's 0.0001% placeholder (subsidised מתווה tracks) is zero,
 * and so is a loan the bank itself names "ללא ריבית" (its nominal rate is refunded).
 */
export const rateOf = (l: Loan) =>
  (l.rate_pct ?? 0) < 0.01 || (l.name ?? "").includes("ללא ריבית") ? 0 : (l.rate_pct ?? 0);

/** Bank names carry RTL/LTR marks and stray spaces. */
export const clean = (s?: string) => (s ?? "").replace(/[‎‏]/g, "").replace(/\s+/g, " ").trim();

/**
 * A short, human track name from its terms — Discount's names are the product's full
 * description. A name that is not one of those ("ללא ריבית הצטרפות 2529-1/3") is kept.
 */
export function trackLabel(l: Loan): string {
  const name = clean(l.name);
  if (name.includes("מתווה")) return "מסלול מתווה";
  if (!/^הלו?ואה/.test(name)) return name;
  const linkage = l.index_linked ? "צמוד מדד" : "לא צמוד";
  const kind = l.rate_type === "fixed" ? "קבועה" : "משתנה";
  return `${linkage} · ${kind}`;
}

/**
 * How much of a loan is paid off, 0..1, or null when nothing says. Principal paid when the
 * original amount explains the balance; else payments made of the schedule (an index-linked
 * balance grows past the original, and the מתווה originals are not the amount lent). A bank
 * that reports no payment made yet says nothing, so that is unknown too.
 */
export function paidShare(l: Loan): number | null {
  const bal = l.balance ?? 0;
  const orig = Number(l.original_amount ?? 0);
  if (orig > 0 && bal <= orig && !l.index_linked) return 1 - bal / orig;
  const total = Number(l.payments_total ?? 0);
  const made = total - Number(l.payments_remaining ?? 0);
  return total > 0 && made > 0 ? made / total : null;
}

/** "2053-08-10" from Discount's '20530810' or Leumi's '2028-12-02'. */
export const isoDate = (d?: string) => String(d ?? "").replace(/^(\d{4})(\d{2})(\d{2})$/, "$1-$2-$3");

export interface Track {
  label: string;
  balance: number;
  monthly: number;
  rateW: number;
  rated: boolean;
  count: number;
  end: string;
  paidW: number;
  paidBal: number;
}

/** Tracks with the same label folded together (the three מתווה tranches → one row). */
export function groupTracks(loans: Loan[]): Track[] {
  const groups = new Map<string, Track>();
  for (const l of loans) {
    const label = trackLabel(l);
    const g = groups.get(label) ?? { label, balance: 0, monthly: 0, rateW: 0, rated: false, count: 0, end: "", paidW: 0, paidBal: 0 };
    const bal = l.balance ?? 0;
    g.balance += bal;
    g.monthly += l.monthly_payment ?? 0;
    g.rateW += bal * rateOf(l);
    g.rated ||= l.rate_pct != null;
    g.count += 1;
    const paid = paidShare(l);
    if (paid != null) {
      g.paidW += paid * bal;
      g.paidBal += bal;
    }
    const end = isoDate(l.final_date);
    if (end > g.end) g.end = end;
    groups.set(label, g);
  }
  return [...groups.values()].sort((a, b) => b.balance - a.balance);
}
