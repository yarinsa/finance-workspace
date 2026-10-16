# RiseUp coverage audit — why 1,380 of 2,112 ledger rows are RiseUp-only

Snapshot: `data/digested/transactions.json` and `data/*/raw` as of 2026-10-16.
Read-only analysis; no code or data changed, nothing scraped. Items marked
**(inference)** are not proven by the files on disk.

## 1. Headline

- Only **~4% of the RiseUp-only rows (53) are a dedup/parsing problem**. The
  other 96% are rows our scrapers never fetched: history we never pulled,
  a gap in the Discount feed, and one issuer (Max) we do not scrape at all.
- The direct feeds are thin by design: the refresh scripts pull a *window*, not
  history. CAL pulls the current billing cycle only, Amex the current and previous
  billing month, Discount a ~2-week "home page" list, Leumi ~3 months.
- Three normalizer bugs hide real matches and also put **wrong amounts** into the
  ledger (e.g. a ₪10,000 CAL row that is really a ₪500 installment). They are
  cheap to fix and should be fixed first, independent of RiseUp.
- RiseUp's own history in this repo only starts **2025-12** (the budget dumps on
  disk). A one-time backfill of ~11 months from the direct sources would cover
  everything RiseUp can show us today.
- Replacing the *ledger* is the easy half. Replacing RiseUp's **categories** and
  **budget envelopes** (which drive `forecast.py`, `bills.py`, `budgets.py`,
  `months_view.py`, `cashflow.py`) is the real work.

## 2. Summary table (ledger rows with `sources == ["riseup"]`)

Rows are ledger rows (after dedup). "Out" and "In" are the sum of negative and
positive amounts in ₪. Because RiseUp-only rows include transfers and card-bill
settlements, "counted spend" is the outflow that actually reaches `total_spent`
(rows not flagged `internal_transfer` / `card_bill_payment` / `savings`).

| Class | Meaning | Rows | Out ₪ | In ₪ | Counted spend ₪ | Fix |
|---|---|---:|---:|---:|---:|---|
| **A1** | Older than the direct scrape window | 816 | -177,171 | 165,727 | -154,974 | Deep backfill (§6) |
| **A2** | Inside the Discount feed's gap (Jun 13 - Sep 28) | 149 | -173,371 | 119,962 | -55,749 | Discount date-range backfill |
| **A3** | Newer than the last cycle cut-off (not yet billed/fetched) | 26 | -2,388 | 25 | -2,348 | Resolves itself next refresh |
| **B** | Account we do not scrape: Max cards | 250 | -31,133 | 29 | -31,133 | New `max` source (M) |
| **C1** | CAL normalizer uses the wrong amount field (FX, installments) | 20 | -3,621 | 0 | -3,621 | One-line fix in `cal/normalize.py` |
| **C2** | Installment date shift (original deal date vs. payment date) | 5 | -1,678 | 0 | -1,678 | Date rule in cal/amex normalize |
| **C3** | Amex rows in a raw list the normalizer ignores | 28 | -13,498 | 10,459 | -13,498 | Read `outOfStatementChargeDateVouchers` |
| **D1** | RiseUp zero-amount placeholder rows | 70 | 0 | 0 | 0 | Drop in RiseUp normalize (moot after cancel) |
| **D2** | Future-dated installment projections from RiseUp | 3 | -336 | 250 | -336 | None needed |
| **D3** | In window, no match found (incl. 1 false loose match, see §4) | 13 | -1,735 | 4,469 | -1,735 | Case by case |
| | **Total** | **1,380** | | | | |

Share: A (A1+A2+A3) = 991 rows (71.8%); B = 250 (18.1%); C = 53 (3.8%); D = 86 (6.2%).

Counted spend inside the RiseUp-only rows is ~₪265k, against `total_spent` of
₪561,585 in the summary block. So roughly 47% of the spend the app shows depends
on a RiseUp-only copy today **(derived; summary figure includes rows both sources hold)**.

Method: each ledger row was mapped back to its RiseUp raw record (via
`(date, abs(amount))`, first record on a collision; 89 of the 1,380 collide) to
recover the true RiseUp origin and account. The direct window per account was taken
from the actual date coverage of the normalized and raw files. Class order of
precedence: zero amount, Max, future-dated, in-window match attempts (corrected
fields, installment date, +-0.02 rounding, +-3 days), then outside-window.

## 3. Who the RiseUp-only rows are

Aliases only; no card or account numbers.

| RiseUp origin (account) | Rows | Neg rows / Out ₪ | Pos rows / In ₪ | Direct scraper |
|---|---:|---:|---:|---|
| CAL card (main) | 792 | 732 / -118,779 | 16 / 14,084 | `cal`: current cycle only |
| Discount checking | 221 | 115 / -215,853 | 89 / 163,301 | `discount`: Jan 1 - Jun 12, Sep 29 - Oct 13 |
| Max card #1 | 192 | 188 / -21,576 | 2 / 29 | none |
| AMEX Platinum | 73 | 53 / -20,506 | 16 / 11,378 | `amex`: from ~May 10 |
| Max card #2 | 53 | 53 / -9,098 | 0 | none |
| Leumi loan account | 33 | 20 / -16,193 | 13 / 112,130 | `leumi`: from Jul 6 |
| Isracard Platinum MC | 9 | 6 / -2,467 | 0 | `amex`: from ~May 18 |
| Max card #3 | 7 | 7 / -459 | 0 | none |

By month (all ledger rows, share that has both a RiseUp and a direct copy):
Dec 2025 0%, Jan 27%, Feb 30%, Mar 30%, Apr 24%, May 38%, Jun 38%, Jul 25%,
Aug 33%, Sep 46%, Oct 53%. Direct coverage is best only in the latest cycle
because that is all the card scrapers fetch.

RiseUp-only rows per month are 101-208 from Dec 2025 to Sep 2026; the Dec 2025
spike (208) is Discount, Max and CAL history that predates every direct scrape.

Sign split: 1,174 outflow rows (-₪404,932 incl. transfers), 136 inflow rows
(+₪300,921), 70 zero-amount rows; the inflows are mostly Discount/Leumi transfers, salary, loan proceeds and the
Amex credit-line transfers.

## 4. Per-source findings

### CAL (`data/cal`)

- Roster: 16 cards, but only one has any transactions. `cardTransactions_<card>_*.json`
  is requested for the **current month/year only** (`dump.sh`: `month: now.getMonth()+1`),
  so the dump holds exactly one billing cycle: purchases 2026-09-10 to 2026-10-09,
  debit date 2026-10-10, 49 rows. Normalized: 49 rows, dates 2025-07-02 (an old
  installment deal) to 2026-10-08.
- The skill claims `filteredTransactions.json` is "all-card transactions, last 12
  months". It is not: the request uses `trnType: 6`, and the response is 50 rows
  of credits and club accruals only (24 refunds, 25 cash-back accruals, 1 standing
  order). `normalize.py` does not read it anyway. **(inference)** a different
  `trnType` value (or none) would return charges; untested.
- `monthlyDebitsSummary.json` has monthly billing totals from 2025-05 onward
  (22 months incl. future ones), so a month loop on `getCardTransactionsDetails`
  has a reconciliation target. **(inference)** the endpoint accepts older
  `month`/`year`; the dump script has never tried.
- **Bug (C1).** `normalize.py` stores `trnAmt` as the amount. For foreign
  purchases `trnAmt` is the foreign-currency figure and for installments it is the
  *deal total*. The ₪ charge for the cycle is `amtBeforeConvAndIndex`.
  Examples (date, description, RiseUp ₪ vs CAL ledger value):
  - 2026-09-11 UNTITLEDrubber: -2,047.41 vs -670.58 (USD amount)
  - 2026-09-27 PAYMOB*WARM SPA: -303.96 vs -5,100 (EGP amount)
  - 2026-09-29 ח.י אלקטרוניקה (payment 1 of 8): -230.75 vs -1,846 (deal total)
  - 2026-09-29 מחסני חשמל-אילת (payment 1 of 10): -114 vs -1,059
  - 2026-09-10 Am Wriezener Bahnhof: -141.96 vs -40 (EUR amount)
  
  All 22 `cal`-only ledger rows (₪-19,291) are these mirrors or the same class of
  error; **they also overstate the ledger today** (a -10,000 row dated 2025-07-02
  and -5,100 are counted as ₪). Using `amtBeforeConvAndIndex` recovers 20 rows
  strictly.
- **Installment date (C2).** RiseUp dates payment *n* at the deal date plus
  *n-1* months; CAL/Amex give the original purchase date for every installment.
  Example: RiseUp 2026-10-02 -500 מטרו מוטור (payment 16 of 20); CAL raw says
  purchase 2025-07-02. Rule `date + (payment-1) months` recovers 5 rows (2 CAL, 3 Amex).
  Installments are also the only place the ledger has RiseUp rows dated in the
  future (D2: 3 rows).
- Dedup key note: `RISEUP_ORIGIN` maps RiseUp `leumicard` to `cal`
  ("both are CAL-cleared"). RiseUp's credential list shows **Max and CAL as two
  separate logins**, and the `leumicard` cards are the Max ones **(inference from
  the credential names)**. Result: 252 Max rows carry `origin: "cal"` in the
  ledger, which is wrong and would let a CAL direct row falsely merge with a Max
  row on `(date, amount)`. Observed collisions today: 0.

### Amex / Isracard (`data/amex`)

- Raw is `transactions_<card>_<billing-month>.json` for the current and previous
  billing month per active card. Present: AMEX Platinum Jun-Oct, Isracard
  Platinum MC Jun-Oct, plus two inactive cards. Purchases reach back to ~May 10
  (AMEX) and ~May 18 (Isracard). 322 normalized rows, 2025-12-26 to 2026-10-09.
- **C3.** Each monthly file has two lists. `normalize.py` only reads
  `vouchers.israelAbroadVouchersList`; the sibling
  `israelAbroadVouchers.outOfStatementChargeDateVouchers` holds 29 more rows:
  cash withdrawals, credit-line transfers (`העברות לקרדיט`) and their repayments
  (`פרעון ...`), loan interest, a self-employed tax payment, tax-free refunds.
  Recovered by reading that list (28 matches; amounts are unsigned or sign-flipped
  in that list, so a sign rule is needed). Examples:
  - 2026-09-24 משיכת מזומנים -1,000
  - 2026-08-09 פרעון העברות לקרדיט -5,212.89 (paired with a +5,212.89 on 2026-07-10)
  - 2026-08-09 פרעון מס הכנסה עצמאי -1,157
  - 2026-08-09 פרעון ריבית הלוואה -3.92
  
  The credit-line pairs are cash-in/cash-out pairs, so their net effect on spend
  is ~0, but today only RiseUp sees them.
- Installments (C2): 3 more rows (קינג אקספרס -558.06, מטרו -125, אושר עד -465.10).
- 37 Amex-only ledger rows (₪-4,503) exist because RiseUp's date or amount differs
  by an installment shift or +-0.01. Mirror image of C2.
- Fetch window: `dump.sh` fetches month 0 and month 1 only. **(inference)** the
  same `billingMonth` call can go further back; the skill notes the SPA pages
  per-card history.

### Discount checking (`data/discount`)

- Two inputs. (1) Legacy MCP dumps `fetch-transactions_2026-01-01.json` and
  `_2026-05-01.json`, written Jun 13: they cover **Jan 1 - Jun 12**. (2) The CDP
  `transactions.json` (`forHomePage`, `NumberOfTransactions=500`) returned only
  34 entries, **2026-09-29 to 2026-10-13** (`AdditionalTransactions: "False"`).
  Requesting 500 does not widen it: the endpoint is time-capped, not count-capped
  **(inference, ~2 weeks)**.
- So the ledger has **no Discount data for Jun 13 - Sep 28** (A2: 149 rows, ₪-173k
  out / +120k in; mostly the monthly card bills, deposit moves, salary and tax
  refund) and none before 2026-01-01 (A1: 50 rows, the Dec 2025 salary, mortgage
  and card bills). Normalized months present: Jan-Jun, Sep (8), Oct (26).
- Anything that is not refreshed within about two weeks silently falls out of the
  feed. This is why the gap exists and it will recur unless a date-range endpoint
  is used.
- The raw rows carry `CategoryDescription` (the bank's own category, e.g.
  `פיקדונות וחסכונות`); `normalize.py` drops it.
- The discount normalized file also holds 34 rows under a second `account_id`
  (a short branch string) from the legacy dump; same account, no data issue.
- Direct-only: 1 Discount row (₪-779).

### Leumi (`data/leumi`)

- The scraped account is the loan account. `transactions.json`: 40 rows,
  2026-07-06 to 2026-10-11, from `OperationsNumber: 500` with empty from/to dates
  (the bank returns its default recent window, about 3 months **(inference)**).
- RiseUp has 27 older rows (A1) with large amounts: salary transfers, the ₪50,000
  loan disbursement on 2026-06-02, card settlements. Net +₪92.9k, which is why
  this class matters for balances and loan history despite few rows.
- C4: one apparent +-3 day match (Leumi `העברה לפיגור`) is a **false positive**: it
  pairs a RiseUp inflow with an opposite-sign loan repayment 3 days earlier. It is
  counted in D3. A +-3 day rule recovers **zero** true rows.

### Discount business (`data/discount-business`)

- 32 rows, 2026-04-10 to 2026-10-02. RiseUp has no business account at all, so
  22 ledger rows (₪-8,540) are direct-only. Not a RiseUp gap; the reverse.

### Max (not scraped)

- RiseUp's Max (`leumicard`) credential has three cards with 252 rows in the ledger
  (₪-31.1k outflow, 2025-12-01 to 2026-10-15; 206 on the busiest card). There is
  no `max` source and the Leumi skill states Leumi Card/Max lives on a separate
  portal. This is the only class where more history will not help; a new
  scraper is required.
- Active debt: RiseUp reports the Max card balance in `current-credit-card-debt`,
  which `digest.py` uses for card-debt totals. Without a Max scraper that debt has
  no direct source.

### RiseUp itself

- Open-banking credentials (Discount, Max, CAL, Leumi, Amex, Isracard) all
  report `valid`, last scraped 2026-10-16 03:56. Pepper bank is in the account list
  but has no transactions in the dump.
- Transaction history on disk: 2,215 records, **2025-01-13** (1 row) / 2025-11-25
  (1 row) / otherwise **2025-12 onward**; built from `budget_2026-06..10_6.json`
  plus `budget_current.json`. `budget_oldest.json` is empty (7 bytes).
- 170 records have amount 0 (84 CAL, 51 Discount, 35 Amex/Isracard/Max). 138 have
  no `scraperSourceType` and look like merged or placeholder entries. 70 appear as
  RiseUp-only rows (D1).
- Subscription state: active, since 2026-01-27, `until` 2027-07-16, auto-renew on.
  **Check the actual billing date before cancelling.**

## 5. Would a looser match recover them? (task 3)

Applied to RiseUp-only rows that fall inside a direct window:

| Rule | Rows recovered | Comment |
|---|---:|---|
| Strict `(date, abs amount)` | 0 (by definition) | |
| +-0.02 amount tolerance | 0 beyond the below | Not the problem |
| +-3 days | 0 true, 1 false positive | Opposite-sign loan repayment (Leumi) |
| Correct CAL amount field (`amtBeforeConvAndIndex`) | 20 | FX + installments |
| Installment date = deal date + (n-1) months | 5 | cal + amex |
| Read Amex `outOfStatementChargeDateVouchers` | 28 | Parsing, not matching |
| **Total** | **53** | |

Conclusion: do not loosen the dedup key. The failures are wrong fields and
unread lists. A date window would add false merges (the key is already the
documented tradeoff in `CLAUDE.md`). The remaining 13 D3 rows are unrelated
single cases: a standing-order charge billed in the *next* CAL cycle (2026-10-05
Strauss -102, billed 2026-11-10), loan-arrears transfers in Leumi, two Discount
transfers from an outside bank, a CAL transfer to Leumi (-712).

## 6. History depth: can a one-time backfill replace RiseUp's history? (task 5)

| Source | Today's window | Depth the script exposes | What a backfill needs |
|---|---|---|---|
| CAL | Current cycle (Sep 10 - Oct 9) | `getCardTransactionsDetails` takes `month`/`year`; script loops cards, not months. Billing totals exist from 2025-05 | Loop months back to 2025-12 or earlier (S). Reconcile each month to `monthlyDebitsSummary` |
| Amex / Isracard | Current + previous billing month | `billingMonth` param on `GetTransactionsList` | Loop `billingMonth` back to 2025-12; depth limit unknown **(inference: probably ~12+ months)** (S) |
| Discount | `forHomePage` ~2 weeks | `NumberOfTransactions` does not widen it. Legacy MCP reached Jan 1 via `startDate` | Find the date-range endpoint in DevTools, or reuse the MCP with `startDate=2025-12-01` (M) |
| Leumi | ~3 months | `FromDateUTC`/`ToDateUTC` request fields exist, left empty | Pass from-date back to 2025-12 (S) |
| Discount business | Home page list (32 rows since Apr) | Same endpoint as personal | Same fix as Discount (S) |
| Max | none | No scraper | New source (M) |

Yes: RiseUp history on disk only reaches Dec 2025 (~11 months), so a single
backfill of **Dec 2025 to today** across the six sources plus Max covers everything
RiseUp can show. It must run once with all logins live, and should be followed by
the standing refresh so the Discount gap does not reopen (refresh at least every
~14 days until a date-range endpoint replaces `forHomePage`).

## 7. What RiseUp provides that the pipeline uses (task 4)

| Capability | Consumers | Dependency today | Replacement approach | Effort |
|---|---|---|---|:--:|
| **Transaction categories** (39 labels) | `cashflow.py` bucket maps, `spending.py`, `months_view.py`, `runway.py`, `bills.py`, app category views | 1,976 of 2,030 RiseUp-touched ledger rows have a category from RiseUp (54 have none). Direct categories are weak: CAL has an issuer category, Amex's "category" is the transaction type (`עסקאות רגילות`), Discount/Leumi drop theirs | Merchant-to-category dictionary and rules built from the RiseUp-labelled history, issuer category as a hint, optional LLM fallback for unseen merchants; keep a user override file. Evaluate on a held-out month | **L** |
| **Rule/AI provenance** | Not used in code | Of 2,215 records: rules 1,185, AI 816, customer rules (exclusions) 304, personal/customer-moves 12, unknown 64 | Treat the 304 user exclusion rules and 12 personal overrides as must-port | S |
| **Budget envelopes** (64 in current month: 38 fixed, 23 category, 1 variable, 1 variable income, 1 goal) | `forecast.py` (reads `budget_current.json`; fixed + `trackingCategory` envelopes), `bills.py` (fixed envelopes, due day, paid/upcoming/overdue), `budgets.py` ("left this month" per category, plus 4 cycles history from `budget_20*_6.json`), `months_view.py` (past months), `actions.py` | Hard dependency; these files are RiseUp-only | Fixed items: `runway.infer_recurring` already infers recurring charges from the ledger (confidence "inferred"). Category budgets: planned amount = trailing 3-month median per category, with the existing `data/budgets/budgets.json` override. Forecast: rebase on recurring items + category run-rate; keep mortgage/loan substitutions (already off RiseUp) | **L** |
| **Cycle start day** | `budgets.py` | `cashflowStartDay` = 1 | Constant | S |
| **Income / salary detection** | `digest.py` snapshot (`salary = income[0].monthly_amount` from RiseUp `insights_all`), `runway.py` payday (`category == "משכורת"`) | Soft; bank descriptions already contain `משכורת` | Detect the largest recurring monthly inflow in the ledger | S |
| **Credit-card debt (`owed`)** | `digest.py` snapshot totals (RiseUp's four debt-bearing cards) | Hard for Max; CAL/Amex have `bigNumberAndDetails` / `cardList` totals in raw | Read issuer balances directly; Max needs its scraper | S (+M for Max) |
| **Bank balances** | `digest.py` | Already prefers direct (`available_balance`); RiseUp only fills gaps | None | S |
| **Transfer / zero-sum matching** | Not used; `digest.py` has its own `internal_transfer` rules | RiseUp's 34 `zeroSum` and 304 customer-rule exclusions are ignored today | None; optionally compare | S |
| **Subscriptions entity** | `riseup/normalize.py` emits `subscription` (RiseUp's *own* plan status, not the household's subscriptions) | Informational | Drop the entity; "subscription" bill kind comes from categories `דיגיטל`/`ספר` in `bills.py` | S |
| **Automatic daily open-banking refresh** | Operational, not in code | RiseUp refreshed all six credentials at 03:56 with no login. Direct scraping needs a manual login/OTP per source (`CLAUDE.md`: the user logs in) | Accept it, or keep a lower-cost aggregator; this is a convenience cost, not a data gap | decision |

Notes: `plugin/scripts/` holds copies of `digest.py`, `forecast.py`, `cashflow.py`
that must be changed in step.

## 8. Recommended plan to turn RiseUp off safely

Ordered; each step has an exit check. Per `CLAUDE.md`, each bug below gets a
failing regression test using the real description and amount first.

1. **Fix what is already scraped (no new logins).**
   - CAL: use `amtBeforeConvAndIndex`, add installment date rule, keep `trnAmt` as
     `original_amount` and currency as `original_currency`.
   - Amex: read `outOfStatementChargeDateVouchers` with a sign rule; installment
     date rule.
   - Discount: keep `CategoryDescription`.
   - `RISEUP_ORIGIN`: stop mapping `leumicard` to `cal`; give Max its own id.
   - Exit: the 53 recoverable rows dedup; the 22 CAL-only and 37 Amex-only rows
     fall to near zero; no ledger row carries a foreign-currency or deal-total
     amount as ₪.
2. **Add the Max source** (`add-bank-source` skill; 3 cards; roster + transactions +
   balance). Exit: the 250 Max rows have a direct copy; Max card debt comes from
   Max, not RiseUp.
3. **Deep backfill, once, all logins live** to 2025-12-01: CAL and Amex month loops,
   Leumi from-date, Discount (personal + business) date-range or MCP `startDate`.
   Exit: per source and month, `ledger rows with a direct copy / RiseUp rows
   (non-zero, non-future) >= 98%` for Dec 2025 to the last closed month, with the
   remainder itemised (like D3); and card months reconcile to the issuer billing
   totals (CAL `monthlyDebitsSummary`, Amex `billingSumSekel`).
4. **Close the recurring gap**: refresh cadence at most every 14 days until the
   Discount feed is date-range based; add a check in `refresh-all` that fails
   when a source's newest-minus-oldest window has a hole.
5. **Build the categorizer and prove it on RiseUp's own labels.** Hold out the two
   most recent full months. Gate: >= 95% agreement by value on the 6 cashflow
   buckets, >= 90% row-level on the 39 labels, and no unlabelled row above ₪500.
   Port the 304 exclusion rules and 12 personal overrides. Freeze the
   merchant-to-category dictionary into the repo (gitignored data) **before** cancelling.
6. **Replace the envelope consumers** (`forecast.py`, `bills.py`, `budgets.py`,
   `months_view.py`, `actions.py`). Gate: two full cycles in which month-1 forecast
   and bills match RiseUp's within an agreed tolerance (suggest 5% of monthly
   outflow) or differences are explained (MEMORY.md already notes RiseUp is stale
   on the partner move-out, so the new forecast may be *more* right).
7. **Parallel run for two closed months with both on.** Gate: step-3 coverage still
   >= 98% on new months; balances match bank balances to the shekel; no
   `total_spent` change > 1% vs. the RiseUp-primary build, after the C-class
   corrections.
8. **Flip dedup priority** (direct becomes primary; category from the new
   categorizer), keep RiseUp raw dumps on disk as a frozen archive, then cancel.
   Check the real renewal date in RiseUp billing; the dump says `until` 2027-07-16
   with auto-renew on. Delete the RiseUp refresh steps from `refresh-all`.

Rough size: steps 1 and 4 small, 2 and 3 medium, 5 and 6 the bulk of the work.

## 9. What is not known

- Whether Amex, CAL and Leumi accept dates earlier than 2025-12 (untested; no
  scraping was done).
- The real Discount `forHomePage` cap (~2 weeks inferred from one dump).
- Whether the `trnType` of `getFilteredTransactions` can return charges.
- Whether Max cards share the CAL clearing in any way that makes the old
  `leumicard -> cal` mapping partly right; the credential names say they are
  separate logins.
- RiseUp's `excluded`/zero-sum flags were not compared with `digest.py`'s own
  transfer detection.
