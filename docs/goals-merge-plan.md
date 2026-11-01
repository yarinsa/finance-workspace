# Goals merge — plan

General targets (emergency fund, retirement, inheritance: `plan_targets`) and personal goals (`goals`) are one thing:
an amount wanted, backed by savings. Decided with the user 2026-11-01. Nothing here is built yet.

## Target
- **One `goals` table.** The three defaults are goal rows every household is seeded with, each with a stable `key`
  (`emergency_fund`, `retirement`, `inheritance`) and a Hebrew name. Defaults can be edited and hidden, not deleted.
- **Assigned funds are the current balance.** Any holding goes to any goal (`holding_assignments.goal_id`: one goal
  per holding, many holdings per goal). A goal's current amount is the sum of its assigned holdings; a hand-set amount
  applies only when none is assigned. A liquid study fund assigned to the emergency fund counts there.
- **Projection.** Each goal gets a `projected_amount` and a `projection_source` (empty until the logic exists).
  The UI shows current, projected and target on one bar with a marker for the projection. Empty projection: the bar
  shows current against target only, no 0%, no invented number.
- **One editor, one card.** `TargetsSheet` and `GeneralCard` fold into `GoalEditorSheet` and the goal group; the
  carousel and the goal groups read the same list.

## Steps
1. **Schema (live migration, shown before applying):** `goals.key`, `goals.hidden`, `goals.projected_amount`,
   `goals.projection_source`; seed the three defaults per tenant; copy `plan_targets` amounts into them; drop
   `plan_targets`. Update `finance/tables.py`, `db/goal_store.py`, `data/goals.py`, the GraphQL SDL and codegen.
2. **Current from assigned funds** in `lib/goalsOverlay.ts` / `lib/savingsView.ts`; tests from the real funds.
3. **UI:** merged list, projection marker, one editor; retire `TargetsSheet` and `GeneralCard`.
4. **Later:** projection logic (yield, contributions, the pension forecast) and linking transactions to goals
   (issue #72).

## Open
- Retirement keeps its projection as the default's measure; assigned pension funds feed it. Logic is a later piece.
