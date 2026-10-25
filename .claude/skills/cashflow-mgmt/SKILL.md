---
name: cashflow-mgmt
description: Manage the household's month-to-month cashflow — where the checking balance will land after upcoming debits, when the overdraft (מסגרת) gets hit, available-to-spend until payday, how to reorganize timing and money flows before cutting, sinking funds for periodic costs, and which cuts/prepayments actually help. Activate when the user asks about overdraft/מינוס, "what will my balance be after the charges", how much they can spend, steady/predictable cashflow, reorganizing the budget, a payday/weekly/monthly money review, or whether to put spare cash toward an installment or loan.
---

# Cashflow management

> **Status: draft.** How this skill gets invoked is still open. It encodes the
> method from the 2026-10-10 session, built on
> [references/household-cashflow-research.md](references/household-cashflow-research.md)
> (CFPB / FDIC / Federal Reserve / Bank of Israel). That file is the evidence
> base; read its sections when a case below needs more depth.

Answers *"will there be enough cleared cash on each date, and how do I make
that steady?"*. A **monthly budget** catches *structural* deficits. A **dated
running balance** catches *timing* deficits: a month can be net-positive and
still overdraw for the four days before salary. Do both, and say which one
you're looking at.

Read `MEMORY.md` first. It holds household facts the data can't show: who pays
rent, which loans are effectively 0%, which charges are strategic and must
never be suggested as cuts.

## Core rules

- **Running balance:** `Ending cash = Starting cleared cash + Cash in − Cash out`,
  per account, by date. A projected breach is an action signal *before* the
  date it happens.
- **Cash floor, not zero.** Plan to stay above a floor that leaves room for
  processing order, forecast error and late income. The overdraft limit is
  **debt capacity, not cash** (Bank of Israel: overdraft is expensive and meant
  to be temporary). Default floor: ₪0 on the checking balance unless the user
  sets another.
- **Available to spend** = cleared cash − bills due before next salary −
  sinking-fund reserves − floor. Divide by the days until salary to get a daily
  or weekly allowance. **Subtract committed card purchases not yet billed**:
  in Israel they hit the account weeks later.
- **Four kinds of money.** Classify each movement as income (net, as received)
  / fixed / variable / periodic / true emergency / **transfer**. Transfers
  between own accounts and card-bill payments are never spending. Avoid counting
  them twice.
- **Paybacks are offsets, not income.** A refund, a friend's Bit for their share, or
  the ex-roommate's rent share is netted against its expense (`offsets[]`,
  `offset_amount` on both ledger rows; see "Offsets" in CLAUDE.md). For spend/income
  use the net (`amount ± offset_amount`, or `cashflow.json`, which is already net);
  for **balances and the runway** use the real `amount` — the money did arrive.
  PayBox load + cash-out pairs carry `round_trip` and are transfers.

## Data to read

| Question | Source |
|---|---|
| Balance, limit, available | `data/<bank>/raw/infoAndBalance.json`; `data/digested/snapshot.json` → `bank_accounts` |
| Overdraft interest tiers | `data/discount/raw/creditLine.json` |
| Debits the bank already knows about | `data/discount/raw/transactions.json` → `FutureTransactionEntry` (**incomplete**: misses mortgage and some card bills) |
| Running balance history | same file → `OperationEntry[].BalanceAfterOperation` |
| Next card bills | CAL `cal/raw/bigNumberAndDetails.json` (`nextDebit`); Amex `amex/raw/transactions_<last4>_<MM>-<YYYY>.json` → `totalIlsBillingDate` |
| Which account a card bills | the bank's card list, e.g. `discount/raw/creditCards_pastOrFutureDebitTotal.json` |
| Installment plans | CAL `cardTransactions_*` → `curPaymentNum`/`numOfPayments`; Amex `moreInfo` "תשלום X מ Y" |
| Recurring pattern by day of month | `data/digested/transactions.json`, last 2–3 months, filter by `origin` |
| Multi-month outlook | `data/digested/forecast.md` (all accounts combined, not per account) |

Always state the scrape timestamp. If debits may have posted since, tell the
user to check the live balance. Label every figure as **known**, **inferred**
or **missing**; never invent precision.

## Method

### 1. Safety triage
Before optimizing anything, check for arrears (`סילוק פיגור`), returned debits,
a balance already past the limit, or a housing payment at risk. If any are
present, protect housing, income, insurance and secured loans first, and
suggest calling the creditor *before* the due date. See the research's "Debt
and cash shortages" section.

### 2. Position now
For each checking account: balance, limit, available. Is it overdrawn now?
What was the recent low (min `BalanceAfterOperation`), and how much overdraft
interest has been paid?

### 3. Post-charges waterfall (30–45 days)
A dated table per account: start → each debit/credit in date order → running
balance → floor breach?
- Combine the bank's future list with last month's same-day debits (mortgage,
  card bills, standing orders). Mark inferred items *(probable)*.
- **Weekends/holidays:** anything due Fri/Sat posts on the next business day.
  Group same-day items and warn that the order within the day matters.
- If the salary transfer isn't confirmed, show the result **with and without**
  it.
- Report the **first breach date** and the **lowest point** (usually just
  before salary).

### 4. Rest of month and beyond
Roll forward with the recurring items still due. Then use the forecast's
monthly net to find the month the floor/limit is crossed. Correct for anything
`MEMORY.md` says the forecast misses (e.g. a scheduled mortgage step-up).

### 5. Repair in order: retime → reduce → negotiate → resources → income
**Reorganize first (no lifestyle cost):**
- **Bills before payday:** debits before salary are funded by last month's
  leftovers. Move standing orders to after salary day.
- **Money loops:** circular transfers between own accounts, card→PayBox/Bit→bank
  floats, mid-month early card payments. They hide the deficit and deepen the
  low point.
- **Account split:** purpose separation with **one source of truth**. Each
  account holds what it pays out, filled by one standing order. Arrears mean
  an account ran dry.
- **Too many cards:** more billing dates and more fees.

**Then cuts** (method in `CLAUDE.md` → "Saving money"): large recurring
commitments, fees and rates *before* tiny daily cuts. Use real Hebrew
descriptions and ₪, rate each trivial/easy/moderate, total the tiers. Prefer
**one or two high-impact changes** over a long list. Skip anything `MEMORY.md`
marks strategic. Close by saying plainly how much of the gap is still left for
income or housing to solve.

### 6. Payday allocation (when cash allows)
1. essentials and ability to earn
2. bills due before next salary
3. sinking funds
4. emergency buffer
5. required debt payments
6. extra debt / goals
7. flexible allowance until next review

### 7. Periodic costs → sinking funds
`Monthly provision = max(0, expected cost − saved now) / months remaining`.
For a bill due soon, use the catch-up amount, **not** annual ÷ 12. Candidates
from the ledger: ארנונה (bi-monthly), car insurance (`ביטוח חובה`), vehicle
licensing and service, annual card fees, income-tax payments (`מס הכנסה`).

### 8. Emergency buffer: staged
Transaction buffer → starter shock fund → 1 month of essentials → multiple
months. Size the later stages to the household's risk; the research shows no
universal number. Keep it liquid (e.g. נזיל יומי+). Overdraft headroom is
never the buffer.

### 9. "Should I put spare cash on X?"
Compare the target's rate with the overdraft rate the cash would otherwise
offset.
- **0% card installments:** prepaying saves nothing, only moves payments
  earlier while paying overdraft interest. Show the installment table (₪/mo,
  payments left, ends) and when relief arrives on its own.
- **Interest-bearing loans:** prefer highest effective rate first (avalanche).
  For monthly relief, ask the bank for הקטנת התשלום. Never prepay
  effectively-0% debt.
- **Loan to clear the overdraft:** only if the limit is also lowered and the
  recurring deficit is fixed. Otherwise debt grows (Bank of Israel).
- While overdrawn, the default is: keep the cash as the pre-salary buffer.

## Output contract
1. **One-line answer first** (a number, or yes/no).
2. **Next risk:** first projected breach and its date.
3. **Waterfall table** (start, in, out, ending, breach?).
4. **Actions,** dated: today / this week / next payday / this month.
5. **Assumptions:** inferred items, data age, what's missing.

Offer one next step, not a menu.

## Tone and boundaries
- Neutral, no judgment. Never imply a structural deficit is a discipline
  problem.
- Ask before making a value judgment on family support, gifts, or personal
  transfers to people.
- Separate the mathematically optimal from the behaviorally sustainable. Keep
  room for valued discretionary spending: the goal is control and resilience,
  not austerity.
- Not a licensed adviser. For eviction risk, litigation, insolvency or
  collections, point to qualified local help.

## Review cadence (if the user wants a routine)
- **Payday (~9th):** confirm salary landed, reserve bills through the next 9th,
  fund buffers, compute available-to-spend.
- **Weekly:** refresh, update the 30–45 day waterfall, one corrective action if
  a breach shows.
- **Monthly:** plan vs actual, check nothing was double-counted, review
  subscriptions and fees.
- **Annually:** Banking ID Card (תעודת זהות בנקאית), Bank of
  Israel Equalizer for rate comparison, Har HaKesef for dormant funds.

## Known data gotchas
- The ledger's dedup key is `(date, abs(amount))`, so a bank debit and its
  RiseUp copy one day apart are counted twice (e.g. card 7843). For balances,
  use the bank's own running balance, not summed ledger rows.
- CAL's bill total and the bank's pending debit for the same card can differ.
  Use the bank figure for the account balance and note the gap.

## References
- [household-cashflow-research.md](references/household-cashflow-research.md):
  evidence base, templates, failure modes, evaluation scenarios. Primary.
- [brex-cashflow-guide.md](references/brex-cashflow-guide.md): business-side
  framing (operating/investing/financing, 3–6 month reserve). Secondary.
