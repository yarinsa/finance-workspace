# PRD 01 — Cashflow (תזרים כספי)

> Reverse-engineered from Plangram's `/cashflow` screen. Hebrew (RTL), ILS (₪).
> Evidence: `captures/cashflow-schema.json`, `captures/cashflow-dom.yml`,
> `captures/cashflow-top.png`.

## 1. Summary

The Cashflow screen is the product's **headline dashboard**: a single page that
answers *"is my money in balance, today and over my lifetime?"* It composes three
things, top to bottom:

1. A row of **KPI cards** — scored health metrics (savings %, debt-repayment %,
   Plangram score, etc.).
2. A **today cashflow summary** — income vs. expense vs. net for the current month.
3. A set of **time-series charts** — net worth over the full life horizon, plus
   income and expense breakdowns.

It is a *read-only render* of a precomputed model. In Plangram the model is the
`calculations.data` object inside `GET /user/getcurrent?includeCalculations=true`.
For us, the model is computed from `data/digested/{transactions,snapshot}.json`
plus a lightweight projection engine.

## 2. Goals & non-goals

**Goals**
- Show, at a glance, whether monthly cashflow is positive and whether savings/debt
  ratios are healthy — with a good/warning/bad verdict per metric.
- Show net worth projected over the user's lifetime (to retirement and beyond).
- Break down income and expenses by category so the user sees composition.

**Non-goals (for v1)**
- Editing income/expense/goal entities (those live on their own screens — separate
  PRDs). Cashflow only *consumes* them.
- Scenario authoring / what-if editing (the `תכנון פלוס` screen). v1 reads the
  default scenario only.
- The "explain this page" guided tour and the 6 personalized recommendations
  (separate Recommendations feature).

## 3. Page anatomy

Layout confirmed from `cashflow-dom.yml` (RTL; right rail is the section nav).
Top-to-bottom in the content column:

```
┌─ תזרים כספי  (H1)                              [▶ הסבר על עמוד זה] ┐
│                                                                    │
│  ┌── KPI ROW (5 cards) ────────────────────────────────────────┐  │
│  │  יחס השקעות │ מדד פלנגרם │ אחוז החזר חוב │ חתיכה חסרה │ אחוז חיסכון │
│  │   value + good/warning/bad verdict pill under each           │  │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                    │
│  ┌── עו"ש (net worth chart) ───┐  ┌── התזרים (today summary) ───┐  │
│  │  area chart, year axis      │  │  bar: income vs expense      │  │
│  │  2026 … 2078                │  │  תזרים ₪ / הכנסות ₪ / הוצאות ₪ │  │
│  └─────────────────────────────┘  └──────────────────────────────┘ │
│                                                                    │
│  ┌── הכנסות (income breakdown) ─────────────────────────────────┐  │
│  │  legend: הכנסות מעבודה · הכנסה מקצבאות     [⚙ אפשרויות גרף]   │  │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                    │
│  ┌── הוצאות (expense breakdown) ────────────────────────────────┐  │
│  │  legend: הוצאה שוטפת · יעדים · הלוואות · מיסים · השקעות         │  │
│  └──────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────┘
```

The H1 links to an article (`/article/73/דף-תזרים-כספי`) — an inline help affordance.

## 4. KPI cards

The card row surfaces 5 of a catalog of **28 metrics** (full list in
`cashflow-schema.json → today_metrics`). Each metric carries: `name`, `units`
(`₪` / `%` / none), `higher_is_better`, a `rank` verdict, and a `description`
shown on hover/expand. The verdict drives the colored pill:

| `rank` | Pill in UI | Meaning |
|---|---|---|
| `good` | green "מעולה" | healthy |
| `bad`  | red, e.g. "לא משהו" | needs attention |
| `null` | none / neutral | informational only |

The 5 cards shown on the dashboard (from `cashflow-dom.yml`):

| Card (HE) | Meaning | Units | Definition (from `description`) |
|---|---|:--:|---|
| **יחס השקעות** | Investment ratio | % | Share of free cashflow directed to savings |
| **מדד פלנגרם** | Plangram score | 0–100 | Overall balance score across cashflow & goals |
| **אחוז החזר חוב** | Debt-repayment % | % | Loan repayments as a share of monthly expenses |
| **חתיכה חסרה** | "Missing piece" | ₪ | Gap to fully fund all life-path goals |
| **אחוז חיסכון** | Savings % | % | Money directed to savings as a share of net income |

### Metric definitions we will implement first

These are computable from our data **today** (no projection needed):

- **תזרים (net cashflow)** = `total_income − total_spent` for the month.
  → `summary.total_income + summary.total_spent` (spend is negative in our data).
  Verdict `good` when positive.
- **הכנסות / הוצאות** = `total_income` / `abs(total_spent)`.
- **אחוז חיסכון (savings %)** = money to savings ÷ net income. Needs a "to savings"
  classification — map our categories (e.g. transfers to investment/deposit) or
  derive from snapshot deltas. *Flag as needs-input.*
- **אחוז החזר חוב (debt-repayment %)** = monthly loan service ÷ total monthly
  expenses. Loan service comes from `snapshot.json` loans/mortgage installments.
- **שווי נקי (net worth)** = assets − liabilities, straight from `snapshot.json`.

Defer to the projection engine (§6): מדד פלנגרם, מדד הצמיחה, חתיכה חסרה,
חתיכה עודפת, אחוז עמידה ביעדים, אחוז עמידה בקרן חירום, סכום להורשה.

## 5. Charts

15 plot definitions exist (`cashflow-schema.json → charts`); the cashflow page
renders this subset. Every plot shares one envelope:

```jsonc
{
  "graph_type": "area" | "bar" | "line" | "pie",
  "graph_title": "string (HE)",
  "xlabel": "string", "ylabel": "string|null",
  "x_axis": [ ...values ],          // shared category axis
  "datasets": [ { "name", "ds": [...], "color", "first" } ]
}
```

Pies use a nested `assetpies.data[] = { dataset, labels, graph_title, graph_type }`.

| Panel (HE) | Plot key | Type | Datasets / legend |
|---|---|:--:|---|
| **עו"ש** (net worth over time) | `netval_plot` | area | net value across the year axis |
| **התזרים** (today) | `income_plot_3color` + summary | bar | income vs. expense bars + 3 numeric tiles |
| **הכנסות** | `income_plot` / `income_plot_3color` | area | הכנסות מעבודה · הכנסה מקצבאות |
| **הוצאות** | `expense_plot` | area | הוצאה שוטפת · יעדים · הלוואות · מיסים · השקעות |

Notes:
- The net-worth x-axis is **calendar years to ~age 80** (screenshot shows 2026–2078),
  i.e. driven by the scenario's `retirementAge` and life horizon, not the ledger.
- The **expense legend categories** (running expense / goals / loans / taxes /
  investments) are the canonical expense grouping — adopt these as our top-level
  cashflow buckets so charts and KPIs agree.
- Each chart has an **⚙ "אפשרויות גרף"** (graph options) button → series toggle /
  view switch. v1 can ship without it.

## 6. Data model & projection engine

### Inputs we already have
- `data/digested/transactions.json` → `summary.{total_income,total_spent,by_category,by_origin}`
  → today summary, income chart, expense chart, savings/debt ratios.
- `data/digested/snapshot.json` → balances, card debt, loans/mortgage installments,
  detected salary → net worth seed, debt service, income baseline.

### Scenario object (drives the projection)
From `GET /Scenario/List` (`captures/scenario-list.json`), each scenario carries:

```
id, name, retirementAge, partnerRetirementAge,
globalEmergencyFund,        // target emergency-fund size (₪)
globalInheritanceFund,      // target inheritance to leave (₪)
netWorthAtRetirement,       // computed output
isConservativeForecast,     // toggles return assumptions
inflationRate, isDefault, updatedDate
```

For v1 we synthesize a **single default scenario** with sensible constants
(retirement age, inflation, expected return, emergency-fund target) in config.

### Projection outputs to compute
The forward-looking widgets need a yearly simulation from now to end-of-life:

- **`netval_plot` / `focal_points`** — iterate years; each step:
  `net_worth += (annual_income − annual_expense) + investment_return − goal_outflows`.
  `focal_points[]` = `{date, age, asset_val, loan_val, net_val}` snapshots at key
  ages (today, retirement, ...). `timeline[]` is the dense per-step series
  (`{value, date, units, category, color}`), ~2000 points in Plangram.
- **goal compliance** (`goal_compliance`: `passive_coverage`, `portfolio_goals`,
  `freedom`, `inheritance`, `missing_piece`) — whether projected net worth funds
  the goals; produces **חתיכה חסרה** (missing piece) and **אחוז עמידה ביעדים**.
- **מדד פלנגרם (0–100)** — composite of cashflow balance + goal coverage. Exact
  weighting is proprietary; v1 ships our own transparent formula and labels it ours.

> Build the **today** half first (KPIs + income/expense + net-worth seed) — it's
> fully backed by our existing data. The projection engine is phase 2.

## 7. Implementation plan (suggested)

**Phase 1 — Today dashboard (no projection)**
1. Add `data/cashflow.py` that reads the two digested files and emits a
   `cashflow.json`: `{ metrics: [...], today: {income,expense,net}, charts: {...} }`
   using the metric/chart catalog in `cashflow-schema.json`.
2. Compute the computable metrics (§4) with good/warning/bad verdicts.
3. Build income & expense breakdowns from `summary.by_category`, grouped into the
   canonical buckets (work/benefits for income; running/goals/loans/taxes/investments
   for expense).
4. Render: KPI row + today summary + two breakdown charts.

**Phase 2 — Projection**
5. Add a scenario config + yearly simulation → `netval`, `focal_points`, `timeline`.
6. Net-worth chart + goal-compliance metrics (חתיכה חסרה, אחוז עמידה ביעדים).
7. Plangram-style composite score (our own formula).

## 7b. Phase 1 — built (`data/cashflow.py`)

Implemented and wired into `data/digest.py` (runs after the snapshot). Emits
`data/digested/cashflow.json` + `cashflow.md`. It aggregates the ledger **by
month**, picks the latest *complete* month as "current", and computes the
data-backed metrics + income/expense breakdowns + a months trend.

**Data-quality caveats found against real data (fix before trusting numbers):**

- **Inter-account transfers inflate income & expense.** Business↔personal moves
  count as both income and spend (May: ₪69K in / ₪84K out). Need a transfer
  filter (exclude `העברות`/P2P and same-amount opposite-sign pairs across origins)
  before the monthly totals are trustworthy.
- **Loan repayments don't reach the `loans` bucket from transactions** — the
  `הלוואה`/`משכנתא` categories are swamped by `uncategorized`, so the expense
  pie shows ~₪0 loans while the snapshot knows real loan service is ₪9,485/mo.
  `אחוז החזר חוב` therefore uses snapshot loan-service ÷ (inflated) tx-expense and
  reads low (11%). Prefer snapshot-derived figures for loan/debt lines.
- **Savings% is a proxy** (`max(net,0)/income`) — reads 0% on a negative month.
  True net-worth-delta savings needs snapshot **history**; we only store one point.
  → add a `snapshot-history/` append on each digest to unlock it.
- The huge `uncategorized` bucket (~₪443K all-time) falls into `running` expense.

## 7c. Phase 2 — built (`data/projection.py`)

Forward-looking net-worth projection, wired into `cashflow.py` (adds a
`projection` block, the `net_worth` chart, and 3 KPI cards). Read-only over
`snapshot.json`.

**Method (decisions locked with the user):**
- **Real terms** (after-inflation); the curve reads in today's shekels.
- **Surplus from loan payoff, not the ledger** — each snapshot loan is amortized
  month-by-month from its real `balance`/`rate_pct`/`monthly_payment`/
  `payments_remaining`; when a loan finishes, its freed monthly payment becomes
  recurring investable surplus compounding at **4% real**. This sidesteps the
  Phase-1 ledger-noise problem entirely.
- Loans with no schedule (Leumi aggregate) are straight-lined over a default term.
- Assumptions live in `projection.CONFIG`: `current_age` (⚠ placeholder 35 — not
  in scraped data; edit for an accurate horizon), `retirement_age=67`,
  `end_age=90`, `real_return=0.04`.

**Outputs:** `timeline` (yearly net-worth/loan/invested points → `netval_plot`),
`focal_points` (today, each loan payoff with freed cashflow, retirement, end),
`net_worth_at_retirement`, plus KPI cards **שווי נקי בפרישה**, **מדד הצמיחה**
(5-yr real slope), and **מדד איזון** (our own transparent 0–100 score, explicitly
*not* Plangram's proprietary number).

**Still deferred (Phase 3):** goal-compliance metrics (חתיכה חסרה / אחוז עמידה
ביעדים) — they need the goals entity, which lives on a separate screen we haven't
captured yet; income growth and life-events overlays.

## 8. Open questions

- **Savings classification** — which of our categories/transfers count as "money to
  savings"? Needed for אחוז חיסכון and יחס השקעות. *(needs user input)*
- **Scenario assumptions** — retirement age, expected return, inflation: hardcode
  defaults or expose a settings screen? Plangram exposes them per-scenario.
- **Chart granularity** — Plangram projects per-year to ~age 80. Match that horizon
  or cap at a shorter window for v1?
- Do we replicate the **composite "Plangram score"**, or ship our own clearly-labeled
  health score to avoid implying parity with theirs?
