# חיסכון (Savings) screen — plan

Turns "יעדים וחיסכון" (`routes/Goals.tsx`, rendered by `Plan.tsx`) into a real savings screen shaped like תנועות:
filters, a widgets carousel, and a **group by** with the same bars and components. Decided with the user 2026-11-01.

## Target
- **Rows are mixed**: *holdings* (`snapshot.savings`: pension, study funds, provident fund, deposits; a balance) and
  *movements* (ledger rows in `השקעה וחיסכון`, ~35 today; a flow). Each row says which it is. Totals never add a
  balance to a flow: widgets and group headers show the balance and the flow side by side.
- **Group by**: horizon (current / near / future / לא משויך), goal, kind (pension / study fund / provident / deposit),
  institution (Harel, More, Analyst…). Default: horizon.
- **Time range chips** as on תנועות. They window the movements; holdings are as-of their `as_of` date and say so.
- **Widgets carousel**: total savings, liquid vs illiquid, next liquidity date, the former general targets
  (emergency fund, retirement coverage, inheritance) merged in as widgets, and the missing piece. Targets are
  household-level, so they ignore the range and say so, as the cycle figures do on תנועות.
- **Group header bar** (reuse `StackedBar` / `TransactionGroups` patterns): horizon → share of total vs the 33/67/100
  target; goal → progress vs amount, on-track flag; kind / institution → liquid vs illiquid split.
- **Horizon is derived, and can be set by hand**:
  - holding with `liquidity_date`: ≤ 1y current, ≤ 5y near, later future (thresholds to confirm, kept in one constant);
  - no date (Harel pension and study funds today): לא משויך until the user assigns it;
  - a manual assignment always wins, shown as edited (same mark as an edited transaction);
  - goals keep their existing horizon; movements keep `horizon` / `goal_id` overrides.
- **Goals merged in**: personal goals become a group (and their card the group header). Add / edit goal and the
  targets sheet stay reachable from the screen. `Horizons.tsx` (monthly split of income) is not part of this; it stays
  until the user decides.

## Steps (each shippable on its own)
1. **View model + screen on existing data.** `lib/savingsView.ts` (rows from `snapshot.savings` + savings-category
   ledger rows, derived horizon, `groupRows`-style grouping, widget stats) with tests from the real funds above;
   `routes/Savings.tsx` with range chips, group chips, carousel, groups. Reuses `Chip`, `WidgetsCarousel` and
   `TransactionGroups` where they fit, else extracts them to `components/shared`. Goals and targets sheets move over
   unchanged. No API change.
2. **Manual assignment of a holding** (horizon and goal). Needs a stored override keyed by fund (`institution` +
   `topic_id`): table in `finance/tables.py`, Alembic migration, tenant RLS, GraphQL mutation (schema first), overlay in
   the app. Skills: `schema-change`, `graphql-schema`, `tenant-mgmt`. **The migration is shown to the user before it is
   applied.** Until it ships, an unassigned holding stays לא משויך and the UI says assignment is coming.
3. **Retire the old layout**: route rename / redirect, tab label, `Plan.tsx`, docs and `app/CLAUDE.md`.

## Data gaps (separate ticket, UI built anyway)
- Liquid savings are ₪0: no deposit accounts scraped.
- `management_fee` and `yield_ytd` are null: fee and yield columns render "—" and the widgets hide until populated.
- Harel funds have no `liquidity_date`.

## Open
- Horizon thresholds for derived holdings (1y / 5y proposed).
- Route name and tab label (`/savings`, "חיסכון"?).
- Whether the cycle-based savings plan line (הלוואות וחיסכון on `/monthly`) links here.

UI goes through the `design-system` agent (Holst tokens only, calm Hebrew copy, tabular-nums).
