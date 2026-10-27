import { describe, expect, it } from "vitest";
import type { Loan } from "@/lib/data";
import { paidShare } from "@/lib/loans";

// The 2026-10-27 snapshot's loans.
describe("paid-off share", () => {
  it("is principal paid when the original amount explains the balance", () => {
    const discount = { balance: 24443.65, original_amount: 100000, payments_total: 120, payments_remaining: 99 } as Loan;
    expect(paidShare(discount)).toBeCloseTo(0.7556, 3);
  });

  it("falls back to payments made when the balance is index-linked past the original", () => {
    const linked = { balance: 482725.65, original_amount: 449000, index_linked: true, payments_total: 357, payments_remaining: 322 } as Loan;
    expect(paidShare(linked)).toBeCloseTo(35 / 357, 4);
  });

  it("falls back to payments made when the original is not the amount lent (מתווה)", () => {
    const mitve = { balance: 14311.34, original_amount: 1824.03, payments_total: 48, payments_remaining: 31 } as Loan;
    expect(paidShare(mitve)).toBeCloseTo(17 / 48, 4);
  });

  it("is unknown for Leumi's unread remainder, which has no schedule", () => {
    const unread = { balance: 30568.91, original_amount: null, payments_total: 0, payments_remaining: 0 } as Loan;
    expect(paidShare(unread)).toBeNull();
  });
});
