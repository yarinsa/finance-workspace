# PRD 12 — Mint-style cashflow features

> Native feature set, modelled on Mint (iOS) as captured on Mobbin. References and
> screen links are in [../ux-references.md](../ux-references.md) → "Mint deep-dive".
> Hebrew RTL, ₪. Planned 2026-10-16, after the balance runway (`/runway`) shipped.

## 1. Goal

Mint answers four monthly questions on one "Monthly" tab. We want the same, from
data we already scrape:

| Mint surface | Question it answers | Our data |
|---|---|---|
| **Bills and subscriptions** (dated list) | What's due, what's already paid? | RiseUp `fixed` envelopes (`actuals` non-empty means paid this cycle) + runway events for the dates |
| **Budgets** ("₪X left", per-category bars) | Am I inside my plan this month? | RiseUp `trackingCategory` / `variable` envelopes: planned amount vs `actuals` |
| **Month spending** (donut + Transactions / Categories / Merchants tabs) | Where did it go? | `transactions.json` (deduped ledger, RiseUp categories) |
| **Budget editor** (± amount over the last 4 months' bars) | What budget is realistic? | Ledger history per category; user overrides in a local store |

Out of scope: Mint's weekly bubble targets, and anything that writes back to RiseUp.

## 2. Phases

Each phase ships on its own. Phases 1–3 are independent and can run in parallel
sessions: each one adds a separate block in `cashflow.py` and a separate component.

### Phase 1 — Bills & subscriptions (`bills` block)
- **Data** (`data/bills.py`, called from `cashflow.py`, like `runway.py`): for the
  current RiseUp cycle, one row per `fixed` envelope: `name` (cleaned businessName),
  `category`, `amount` (expense positive), `due_day` (from the runway recurrence day
  or the envelope's actual date), `status`: `paid` | `upcoming` | `overdue` (past due
  day with no actual), `paid_on`, `kind` (bill / subscription / loan), from the
  taxonomy (`categories.bill_kind`; was the `FIXED_GROUPS` mapping). Totals: `paid_total`,
  `upcoming_total`. Exclude income envelopes and internal transfers (reuse
  `digest.is_internal_transfer` on businessName).
- **UI**: a Copilot/Mint-style card. A "₪X left to pay / ₪Y paid" ring, then rows
  ordered by day with ✓ on paid rows and amber on overdue. Goes on `/cashflow` under
  the KPIs, plus a "Bills" link from the runway.
- **Tests**: rent "הו\"ק לעיין ניהול נכסי" paid 10-11 → `paid`; "חב החשמל" with no
  actual and its due day passed → `overdue`; the "מענק בנק לאומי" income envelope is
  excluded; "הו\"ק לששון ירין" (own account) is excluded.

### Phase 2 — Budgets (`budgets` block)
- **Data** (`data/budgets.py`): from RiseUp `trackingCategory` + `variable` envelopes,
  per category: `planned`, `spent` (sum of actuals), `left`, `pct`, `over`.
  Header: `total_planned`, `total_spent`, `left`, `days_left` in the cycle, and
  `per_day = left / days_left`. Use RiseUp's `cashflowStartDay` for the cycle bounds,
  not the calendar month. Optional user overrides come from `data/budgets/budgets.json`
  (gitignored; same pattern as `data/goals/`): `{category: amount}` replaces RiseUp's
  planned amount.
- **UI**: new route `/budgets` (תקציב). Mint hero "₪X נותרו" with a progress bar and
  "₪Y/day for N days", then per-category bars ("₪49 נותרו · ₪51 מתוך ₪100"), with
  over-budget rows in red. Teaser on Overview.
- **Tests**: a real envelope (amount 200, one actual) gives the correct
  left/pct; overrides win over RiseUp; a category over plan sets `over: true`; cycle
  bounds respect `cashflowStartDay`.

### Phase 3 — Month spending explorer (`spending_month` block)
- **Data**: for each of the last 6 months, from the ledger, excluding
  card-bill / internal / savings rows (same rules as `aggregate_by_month`):
  `by_category[]`, `by_merchant[]` (normalized description), `transactions[]`
  (date, merchant, amount, category), and `vs_prev_month`.
- **UI**: route `/spending`. A month switcher (‹ ›), the donut (reuse
  `SpendingDonut`) with the selected category's ₪ and %, then
  Transactions / Categories / Merchants tabs (shadcn `tabs` already exists). Tapping
  a category filters the transactions. Add Monzo's **"Excluded from spending"** card
  (card bills, transfers, savings with ₪ totals) so the numbers can be trusted.
- **Tests**: a card-bill row ("אמריקן אקס,חיוב") is excluded and listed in the
  `excluded` totals; merchant normalization groups "APPLE.COM/BILL CORK" rows.

### Phase 4 — Budget editor (needs Phase 2)
- **Data**: `budgets.py` emits `history[category] = last 4 months' spend` so
  the editor can draw bars against the budget line.
- **Write path**: the app stays a static reader (PRD 11 §5). Phase 4a is a CLI,
  `python3 data/budgets.py set <category> <amount>`, plus the
  `finance-copilot:finance-goal`-style skill wording. Phase 4b (later) is an in-app
  ± editor once a write-back mechanism exists (shared with the goals editor).
- **UI**: a sheet from a budget row with history bars, a dashed current-budget line,
  and the ± stepper, read-only until 4b.

### Phase 5 — Overview polish
- Mint's Net worth / Spending toggle on the Overview hero (the cumulative spend vs
  last month already exists in `pace`).
- Bottom-tab IA: consider a Mint-like "Monthly" grouping
  (Bills · Budgets · Spending) in place of separate nav items. Decide after 1–3 ship.

## 3. Conventions (all phases)
- A new generator is a pure module with docstrings, called from `cashflow.py` and
  allowlisted in `.gitignore` (`!data/<name>.py`). `deploy.sh` needs no change.
- Real-case pytest in `data/tests/test_<name>.py`, written before the fix (CLAUDE.md
  "Bugs → tests").
- Each new block is optional in `data.ts`, and the UI renders an empty state when it
  is missing.
- Verify at 390px in dark mode (the `dashboard-screenshots` skill), then
  `deploy-app` + `sync-data`.
