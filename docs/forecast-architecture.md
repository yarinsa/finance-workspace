# Cashflow forecast — architecture decisions

`data/forecast.py` produces a next-month cashflow projection
(`data/digested/forecast.{json,md}`). This doc records *why* it is built the way
it is, because the non-obvious calls are about which source to trust and how to
avoid double-counting — not the code itself.

## What it answers

"What will next month's cashflow look like?" — projected income, projected
spending (fixed vs discretionary), and a projected net, plus two independent
cross-checks (committed card charges, recent ledger nets).

## Inputs

| Source | File | Role |
|---|---|---|
| RiseUp budget | `data/riseup/raw/budget_current.json` | **Primary** — forward-looking envelopes |
| Unified ledger | `data/digested/transactions.json` | Sanity band only (recent full-month nets) |
| CAL | `data/cal/raw/bigNumberAndDetails.json` | Committed next-month card billing |
| AMEX | `data/amex/raw/billingsOverview.json` | Committed next-month card billing |
| Discount mortgage | `data/discount-mortgage/raw/mortgage_details.json` | Authoritative next mortgage installment |

The forecast month is `budgetDate + 1` (RiseUp's `budgetDate` is the current
month; we project the following one).

## Decisions

### 1. RiseUp envelopes are the forecast, not raw ledger math
RiseUp's `budget_current.json` already carries per-category monthly *predictions*
as "envelopes". We use those directly rather than extrapolating the ledger:

- `type: "fixed"` → recurring bills + income (rent, mortgage, loan repayments,
  subscriptions, salary). `details.isIncome` flags the income rows.
- `type: "trackingCategory"` → discretionary spend predicted per category;
  `originalAmount` is the prediction, the human name lives in
  `trackingCategoryMetadata` (keyed by `trackingCategoryId`).
- `type: "variable" / "variableIncome"` → uncategorised misc; used for run-rate
  context only, not projected.

**Why not the ledger?** The unified ledger dedups on `(date, abs(amount))`
(see CLAUDE.md → Dedup rules). That key merges a card charge with its matching
bank debit and folds in internal transfers, so raw monthly ledger nets swing
wildly (e.g. June shows +49k purely from mid-month transfers). The ledger can't
be trusted for absolute monthly cashflow, so it is demoted to a **sanity band**:
the net of recent *full* calendar months, shown only as a reasonableness check.

### 2. Credit-card billings are a cross-check, NOT added to the net
CAL and AMEX each expose an already-committed next-month billing total
(CAL `bigNumbers[].totalDebit` by `debitDate`; AMEX `billingsOverview` by
`billingDate` "MM/YYYY"). These are real, locked-in numbers (installments +
posted transactions) — higher confidence than any prediction.

But they are **not summed into the forecast net**, because they are the
*settlement* of purchases RiseUp already counts inside its spend envelopes. The
same money viewed twice:

```
purchase  ──tracked──>  RiseUp envelope  (spend prediction, in the net)
   └──settled next month──> CAL/AMEX billing  (cross-check, NOT in the net)
```

Verified empirically: RiseUp's envelopes contain no card-billing line item
(only a small card *fee*), confirming the billing total and the envelope spend
are not independent quantities. Adding them would double-count.

So they render as a separate **"already-committed card charges"** section — a
confidence signal for how much of next month's spend is already fixed
(installments rolling in), independent of RiseUp's prediction.

### 3. Mortgage uses the authoritative installment, not RiseUp's envelope
RiseUp's mortgage envelope reads **₪1,700**, but the real recurring monthly
mortgage charge is **₪8,504**. The gap is a billing-cycle artifact, not a
disagreement:

- The mortgage `Summary.CurrentMonthTotalPayment` (₪1,707) and RiseUp's envelope
  both report the **residual of the current cycle** — once the month's
  installment is paid, that figure collapses to a few hundred ₪.
- The true recurring charge is **Σ per-loan `NextPayment`** across the 6 loans in
  `MortgageDetailsBlock.LoanEntry` (₪8,504), all sharing
  `NextPaymentDate: 20260710`. That is what actually debits next month.

So `forecast.py` **drops the RiseUp mortgage envelope** (the one tagged
`details.expense == "משכנתא"`, `MORTGAGE_EXPENSE`) and substitutes the
`sum(NextPayment)` from the mortgage dump. Suppressing the envelope is what
prevents double-counting the ₪1,700. This single substitution moves the July
projection from a ~₪2.7k surplus to a ~₪4.1k shortfall — it is the dominant line
in the forecast, so getting it from the hard source matters most here.

Same principle as the card cross-check (#2): when a direct source carries the
real committed number, prefer it over RiseUp's prediction and guard the overlap.

### 4. Money-sign convention preserved
Out is negative, income positive throughout intermediate handling (CLAUDE.md
convention); the report presents absolute ₪ in tables for readability.

## Idempotency / regeneration
`forecast.py` is pure read-only over already-scraped raw + digested files. It is
safe to re-run any time; it does no scraping and holds no state. Refresh the
underlying data first (`*-refresh` skills → `python3 data/digest.py`), then run
`python3 data/forecast.py`.

## Resolved: the mortgage step-up
The "~₪8.5k July mortgage" flagged in project memory was **verified** against
`data/discount-mortgage/raw/mortgage_details.json` and is now modelled — see
decision #3. It was not a one-off step-up but the normal recurring installment
that RiseUp's envelope under-reported (residual-cycle figure). No open gap
remains here.
