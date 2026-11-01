# Taxonomy and offsets

Loaded when working under finance/. Project overview: the root CLAUDE.md.

### Views — `finance/views/`

Every figure the app shows is computed by a pure builder in `finance/views/` (snapshot, runway,
bills, budgets, spending, months_view, history, horizons, projection, forecast, goals, actions,
cashflow's pace/charts/metrics). A builder takes explicit inputs plus `today`: no file, table
or clock reads inside it. `household.py` holds `Inputs` (everything the views read) and
`Household(inputs, today)`, which computes each view once, lazily. The pipeline builds `Inputs`
from the digested files (`data/inputs.py`); as inputs move to Postgres the loader changes and
the views do not (docs/json-to-db-migration.md). Shared rules the views need live beside them:
`finance/transfers.py` (own-account transfers), `finance/origins.py` (RiseUp origin → source).

### Offsets — קיזוז (paybacks net against expenses)

Money that only pays back an expense (a friend's Bit for dinner, a merchant refund, the
ex-roommate's share of the rent) is netted against that expense instead of counting as
income. Logic: `finance/offsets.py` (shared by the digest and the API).

- **Three layers.** `auto_offsets` (digest, on the scraped payback row): a same-merchant
  **card** refund (all-or-nothing, ≤180 days after the purchase) or a household rule from
  the `offset_rules` table (`db/input_store.py`; `[{"payer": …, "against": [...]}]`, same month first;
  the old `data/offsets/rules.json` is read only until `db/input_store.py import rules`).
  `manual_offsets` (DB `transaction_offsets`, attached by `db/ledger.py materialize`): a payback
  with any manual row ignores auto; a row with null expense = "offsets nothing".
  `resolve` turns them into `offsets` + `offset_amount` on both rows (manual gets the ₪ first).
- **Counts in the expense's month and category.** `amount` never changes: balances, runway,
  bills and validation read the real money; `Household.transactions` (`finance/views/household.py`)
  is `offsets.cashflow_view` (amount = net, fully-offset paybacks dropped), which spending,
  months, pace, horizons and the summary read. Spending/horizon rows keep the gross `amount` (it is the ledger key) plus `offset`.
- **PayBox round trips** (`digest.mark_round_trips`): a card `PAYBOX` load and the same-amount
  `פייבוקס` bank credit 0–3 days later are both `internal_transfer` + `round_trip`.
- **UI:** the expense's edit sheet → "קזז מול החזר" (GraphQL `linkOffset` / `unlinkOffset` /
  `resetOffsets`); a closed month shows a warning, since the offset changes its totals.

### Categories and kind — one system (important)

`finance/categories.py` is the **only** category list. Every ledger row gets a
`category` under a group (`category_group`: דיור, תחבורה, אוכל, …) and every expense a
`kind`: **`fixed` (קבוע)** — the same or almost the same amount on a schedule (rent,
loans, Metro Motor, subscriptions) — or **`variable` (משתנה)** — needed but usage-driven,
so estimated (fuel, groceries, electricity). "What's left" is not a kind: it is income −
fixed − variable. Non-spending rows (income, card bills, own transfers, savings) have none.

- **Sources' labels are inputs, not the taxonomy.** RiseUp's `expense` label, CAL/Max's
  sector and RiseUp's tracking envelope (the household's own budget lines, e.g. עציצים —
  now real categories) map in through `SOURCE_ALIASES` / `TRACKING_ALIASES`; the raw
  label stays on the row as `source_category`. "תשלומים" says *how* it was paid, not
  what it is, so it maps to nothing and the merchant decides.
- **Defaults** (`categories.stamp`, run by the digest): category = tracking envelope >
  `MERCHANTS` default > source label > the merchant's usual category. Kind = merchant
  default > usage-based category (always variable) > recurring (same merchant + amount
  ±5% on about the same day, ≥3 months) > one-off (the merchant recurs, this charge
  doesn't: a ₪52k loan payoff) > RiseUp fixed envelope > category default. `kind_source`
  says which one decided.
- **Categories are flat = the budget's unit**, the household's own division (RiseUp's, sorted
  by hand: כלכלה, אוכל בחוץ, תחבורה…). `category_group` is only an internal tag (non-spending,
  the cut-lever), never shown. Tags are for filtering and analysis. A dropped category becomes
  an alias (רכב / דלק / תחבורה ציבורית → תחבורה, 2026-10-28): `sync_taxonomy` moves its edits.
  A category can be **merged** into another from the app (a category card → "מיזוג לקטגוריה
  אחרת"; GraphQL `categoryMerge` / `categoryUnmerge`, `db/overrides.merge_category`,
  `categories.merged_into_id`, one level): `transaction_kinds` counts its rows as the target,
  the digest writes the merges to `transactions.json` → `category_merges`, and `budgets.py`
  adds its plan to the target's. Unmerging restores both.
- **Edits** (DB, `transaction_kinds` view): transaction override (`db/edit.py kind|category`)
  > merchant rule (`db/edit.py rule MERCHANT category|kind VALUE`, table `merchant_rules`)
  > the defaults. `db/edit.py categories` prints the tree. The digest with and without
  the DB must agree (`test_digest_stamped_rows_round_trip_unchanged`).
- **Read `kind`, never re-derive it.** `months_view.py`, `budgets.py` (lines and the
  three-block summary) and `cashflow.fixed_expenses` read the ledger's `kind`/`category`.
  Labels that are not ledger rows go through the taxonomy too: a RiseUp envelope's payee
  via `ledger_categories` (the ledger's category for that merchant, edits included) then
  `label_category`; a tracking envelope via `tracking_category`. The per-taxonomy rules
  live in `finance/categories.py`, nowhere else: `DEBT_CATEGORIES`, `LEVERS` /
  `GROUP_LEVER` / `CATEGORY_LEVER` (how a fixed expense can be cut), `bill_kind`.
  **RiseUp still supplies plans, not categories**: `budgets.py`'s planned amounts until
  `budgets.py seed` copies them into the household's own store (the `budget_lines` table;
  a variable category with spending but no line shows at ₪0 as `unplanned`, with its average), and `forecast.py`'s envelopes (see
  docs/forecast-architecture.md — its fixed items carry our `category` +
  `category_group`, the raw label as `source_category`). `plugin/scripts/` keeps its own
  older copies.
- A source label nobody mapped is kept (category without a group) and the digest prints
  it: add it to `SOURCE_ALIASES`.

