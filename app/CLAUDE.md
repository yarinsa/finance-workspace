# Dashboard app

Loaded when working under app/. UI work goes through the design-system subagent.

### UX references

The app's calm design system (Holst palette, Frank Ruhl Libre + Heebo, primitives, calm copy)
is owned by the **`design-system` subagent** (`.claude/agents/design-system.md`), which holds
the decisions and the checks. Use it for any UI work.

Before designing a dashboard screen, read `docs/ux-references.md`: Mobbin
patterns per feature, what the app has vs. lacks, and the design principles
(one number + verdict first, balance-after per row, label confidence).


**The תנועות tab's hub is `/transactions`** (`routes/Transactions.tsx`, logic in `lib/transactionsView.ts`):
every ledger row in a window, newest first, card-bill payments and internal transfers hidden, the live
overlay applied. Range chips 30/60/90/180/360 days ending today or a custom from/to, account chips per
`origin` with counts, a quiet count / out / in line, 100 rows then "הצג עוד". URL: `?days=` or
`?from=&to=`, `?account=<origin>`. Rollout plan (widgets carousel, group-by) in
`docs/transactions-screen-plan.md`. `/monthly` stays in the same group as a non-hub page until it is retired.

**The month screen is one screen: `/monthly`** (there is no `/budgets`, `/spending` or `/fixed`).
בפועל: free money (`budgets.summary.left`) and income / קבוע / משתנה on top (a figure scrolls to its
section; past months show their net and `months_view` actuals instead), then the month's spending
as **one card per category** across קבוע and משתנה (`buildCards` in `app/src/lib/monthList.ts`;
categories are flat, no group level: תחבורה holds Metro Motor's installments and the fuel).
Each card is one list, every row marked קבוע or משתנה on the row itself (no sub-sections). Each card shows actual of planned (fixed paid + fixed still
expected + the variable plan) on a `StackedBar` split into fixed (dark) and variable (light). Inside:
the fixed charges (`fixed_expenses` items merged with `bills` by name: status, due day) with one
quiet saving hint each when there is one (`chargeHint`: duplicate service, not charged in 70+ days,
or the fees/subscriptions lever — also shown in its sheet), then the variable budget lines with
their bars (unplanned: average only; a group-scope line like תחבורה is named by the categories it
covers, not the group again). The cuttable total (fees + subscriptions) sits under the הוצאות
header; הלוואות וחיסכון (loans plus savings) stays its own list. Cards start collapsed unless they
hold an over-budget line or an overdue charge. A line
opens a sheet with the plan editor and its transactions (tap → the edit sheet). Rows with no category group sit in a "לא משויך" card at the top (tap → the
edit sheet to pick a category, or leave them). Past months have no budget/bill data: their cards show only the split.
Deep links: `/monthly?category=<name>` opens that line, `?section=fixed|variable` scrolls to the
cards and `?section=debt_savings` to the loans; `actions.py` CTAs use them. תחזית keeps the hero, plan rows and runway.

