# תנועות (Transactions) screen — plan

Replaces the "החודש" hub (`/monthly`) with a simple transactions screen. Decided with the user 2026-10-31.

## Target
- Rename the tab החודש → **תנועות**; new hub route `/transactions`.
- **One flat list** of all transactions, newest first (no category sections by default).
- **Stats/widgets above the list in a horizontal carousel.** Widgets recalculate for the active filters.
- **Time range:** default last 30 days; chips 30 / 60 / 90 / 180 / 360 days + custom from/to.
- **Account filter**, e.g. "Amex" shows only Amex transactions.
- **Group by** (optional): account, category, fixed vs variable. Each group header gets a stacked bar with a metric for that grouping:
  - account (credit card): usage vs credit limit
  - account (checking): total vs limit (overdraft)
  - category: spent vs planned (the existing `StackedBar` from `MonthList`)
  - fixed vs variable: split per kind
- Credit limits: use them if the data has them; if not, open a GitHub issue to add them and ship the rest.

## Steps (each shippable on its own)
1. **Screen + flat list + time range + account filter.** `/transactions` becomes the group hub; `/monthly` stays as a non-hub page (still "החודש") so budget cards and תחזית remain reachable. Point `/monthly?group=none` links (RecentTransactions, QuickActionsSheet) to `/transactions`.
2. **Widgets carousel** — move the בפועל stats (free money, income / קבוע / משתנה) into a horizontal carousel that respects the filters. Done: net/in/out, קבוע/משתנה/אחר (by ledger `kind`) and top categories follow the filters; free money is a budget-cycle figure, so it shows only under "הכל" and says it does not follow the filter.
3. **Group by category and fixed/variable**, reusing the spent-vs-planned bars, plan editor sheet and bill statuses from `MonthList` / `lib/monthList.ts`.
4. **Group by account** with the limit bars; per-card granularity (`card_last4`, `account_id`) instead of institution.
Then retire `/monthly` (redirect to `/transactions`), once תחזית has a home.

## Data notes (from the repo, 2026-10-31)
- Source: `transactions.transactions` in `app/src/lib/data.ts` (`data/digested/transactions.json`, ~2.2k rows). Money out is negative.
- Every row has `origin` (cal, amex, max, discount, discount-business, leumi) → use it for the step-1 account filter, labelled with `sourceLabel(origin)`.
- Only ~590 rows have `card_last4` and ~540 have `account_id` (RiseUp-only rows lack them) → per-card filtering/grouping is step 4.
- Hide `card_bill_payment` and `internal_transfer` rows (they duplicate card rows). Show income and spending.
- Apply live edits with `overlayFor(overlay, {date, amount})` from `useLedgerApi()` (drop `excluded`, take category/tags/overridden).
- Reuse `TransactionRow` / `TransactionList`, `TransactionEditSheet`, `useQuickEdit().swipeProps`.
- `snapshot.credit_cards` has `owed` but **no credit limit** → GitHub issue needed for step 4. `snapshot.bank_accounts` has `overdraft_limit` only for Discount checking.
- UI goes through the `design-system` agent rules (Holst tokens only, calm copy, tabular-nums).

## Open questions
- Where does תחזית (forecast) live once `/monthly` is retired: a carousel widget or its own page under the tab?
- Credit limit source: scraper field vs manual entry.
