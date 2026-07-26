# PRD 06 — Net Worth (שווי נקי)

> Reverse-engineered from Plangram's `/networth` screen. Hebrew (RTL), ILS (₪).
> Evidence: `captures/route-networth.yml`, `captures/route-networth.png`,
> `captures/cashflow-schema.json`.
>
> **Cross-reference:** the forward-looking math behind this page is *already
> built* — see `data/projection.py` and §7c of `01-cashflow.md`. This PRD
> references that engine and specs only the **gaps**: the two stacked
> assets-/liabilities-over-time charts (`asset_plot` / `loan_plot`) we do not yet
> render, and a fuller assets side than the bank-only one we model today.

## 1. Summary

The Net Worth screen is the **balance-sheet view over a lifetime**: where the
Cashflow page asks *"is my money in balance month to month?"*, this page asks
*"what am I worth, and how does that grow to retirement and beyond?"* It composes,
top to bottom:

1. A **KPI row** — four headline tiles: מדד פלנגרם, מדד הצמיחה, נכסים (total
   assets), הלוואות (total liabilities).
2. A **שווי נקי panel** — net worth now (נוכחי) vs. at retirement (בפרישה), plus a
   one-line projection to age 80, over a per-year area/bar chart of net worth.
3. Two **composition-over-time charts** — גרף נכסים (every asset line stacked over
   the life horizon) and גרף התחייבויות (every loan's remaining balance over time).

Like Cashflow it is a *read-only render* of a precomputed model. In Plangram that
model is `calculations.data` inside `GET /user/getcurrent?includeCalculations=true`
(charts `asset_plot`, `loan_plot`, `netval_plot`, `assetpies`; focal points;
metrics שווי נקי / מדד הצמיחה / מדד פלנגרם). For us, net worth + projection already
come out of `data/projection.py` over `data/digested/snapshot.json`; the gap is
the **per-component** asset/liability decomposition the two stacked charts need.

## 2. Goals & non-goals

**Goals**
- Show net worth today and projected to retirement (and to age 80), with the same
  verdict-pill KPI treatment as Cashflow.
- Render assets-over-time and liabilities-over-time as **stacked** series, one line
  per real asset / per real loan, so the user sees *composition*, not just a total.
- Reuse the existing amortization projection (`projection.py`) as the single source
  of the forward curve — net worth, loan paydown, freed-cashflow reinvestment.

**Non-goals (for v1)**
- Editing assets/loans (those live on `/my-plan/assets` and `/my-plan/debt` —
  separate entity screens). This page only *consumes* them.
- Scenario authoring / "הגדרות תחזית" (forecast settings). v1 reads one default
  scenario (our `projection.CONFIG`).
- The "אפשרויות גרף" (graph options / series toggle) control on each chart — ship
  static stacks first.
- The proprietary **מדד פלנגרם** number — we ship our own transparent score and
  label it ours (same stance as Cashflow §7c).

## 3. Page anatomy

Layout confirmed from `route-networth.yml` (RTL; right rail is the same section
nav as Cashflow). Top-to-bottom in the content column:

```
┌─ שווי נקי  (H1)                                [▶ הסבר על עמוד זה] ┐
│                                                                    │
│  ┌── KPI ROW (4 cards) ─────────────────────────────────────────┐ │
│  │  הלוואות │ נכסים │ מדד הצמיחה │ מדד פלנגרם                       │ │
│  │  ₪99.6K  │ ₪2.7M │  12% מעולה  │  100 מעולה                     │ │
│  │  (value; growth/score cards carry a good/warning/bad pill)    │ │
│  └────────────────────────────────────────────────────────────────┘
│                                                                    │
│  ┌── שווי נקי (H4) ──────────────────────────────────────────────┐ │
│  │   ┌ per-year bar/area chart of net worth ┐   נוכחי   בפרישה     │ │
│  │   │ 2025 ────────────────────────► 2078  │   ₪2.7M   ₪46.6M    │ │
│  │   └──────────────────────────────────────┘                     │ │
│  │   "לפי כלל הנתונים שהזנת, השווי הנקי שלך בגיל 80 … ₪53.76M"      │ │
│  └────────────────────────────────────────────────────────────────┘
│                                                                    │
│  ┌── גרף נכסים (H4)                       [⚙ אפשרויות גרף] ───────┐ │
│  │  stacked area; legend = one line per asset:                    │ │
│  │  עובר ושב · נכס נדלן 1 · שווי השתלמות … · שווי קרן חירום         │ │
│  └────────────────────────────────────────────────────────────────┘
│                                                                    │
│  ┌── גרף התחייבויות (H4)                  [⚙ אפשרויות גרף] ───────┐ │
│  │  stacked area; legend = one line per loan:                     │ │
│  │  הלוואה משכנתא - 10 שנים · משלימה למשכנתא - פריים                 │ │
│  └────────────────────────────────────────────────────────────────┘
└────────────────────────────────────────────────────────────────────┘
```

The H1 links to an article (`/article/74/דף-שווי-נקי`) — inline help, same pattern
as Cashflow's `/article/73`.

## 4. KPI cards

The row surfaces **4 tiles** (from `route-networth.yml`, rendered right-to-left:
מדד פלנגרם, מדד הצמיחה, נכסים, הלוואות). The verdict pill ("מעולה" green / red /
none) is the same `rank` mechanism documented in `01-cashflow.md` §4. Only the two
index cards carry a pill; the two ₪ totals are informational.

| Card (HE) | Meaning | Units | Source |
|---|---|:--:|---|
| **מדד פלנגרם** | Plangram score | 0–100 | proprietary composite — we substitute our **מדד איזון** (`projection.metrics → balance_score`), labeled ours |
| **מדד הצמיחה** | Growth index | % | near-term real net-worth slope — already computed: `projection.metrics → growth` |
| **נכסים** | Total assets | ₪ | sum of all asset lines (see §6 gap) |
| **הלוואות** | Total liabilities | ₪ | sum of loan balances — `snapshot.totals.total_debt` / `projection.total_loan_balance_today` |

Definitions (from `cashflow-schema.json → today_metrics`):
- **מדד הצמיחה** — *"קצב הגידול בשווי הנקי בעת הקרובה"*, `higher_is_better: true`,
  units `%`. Exactly what `projection._balance` already emits as `growth` (5-yr real
  slope). **Reuse as-is.**
- **מדד פלנגרם** — *"מספר בין 0-100 … רמת האיזון … בין ההווה לעתיד"*. Proprietary
  weighting; ship `balance_score` and label it ours (do **not** imply parity).
- **שווי נקי** (the metric backing the panel below) — units `₪`, `rank: null`
  (informational). = `projection.net_worth_today`.

## 5. The שווי נקי panel (נוכחי / בפרישה)

A two-number readout over a per-year net-worth chart:

| Field (HE) | Meaning | Source (already built) |
|---|---|---|
| **נוכחי** | Net worth today | `projection.net_worth_today` |
| **בפרישה** | Net worth at retirement | `projection.net_worth_at_retirement` |
| caption | "…בגיל 80 צפוי להיות … ₪X" | last `timeline` point — `projection.simulate` runs to `CONFIG.end_age` (currently 90; Plangram's caption uses 80 — see Open questions) |

The chart is `netval_plot` (`graph_type: area`, single dataset "שווי נקי", x = age/
year axis to retirement+). **We already emit this** as `projection.to_chart()` —
note our `to_chart` currently bundles three datasets (שווי נקי / יתרת הלוואות / תיק
מושקע); for this panel render only the **שווי נקי** series so it matches Plangram's
single-series `netval_plot`. The screenshot shows a green per-year **bar**-styled
series rising 2025→2078; treat bar vs. area as a styling choice.

> **Gap:** the caption's age-80 figure (₪53.76M) sits **above** בפרישה (₪46.6M)
> because the curve keeps compounding past retirement to `end_age`. Our timeline
> already supports this; we just need to surface the *final* point as a caption
> string and confirm the horizon age (80 vs our 90).

## 6. Data model & the two composition charts (the real gap)

### What's already built (`projection.py`)
- `net_worth_today`, `net_worth_at_retirement`, `total_loan_balance_today` → KPI
  tiles + נוכחי/בפרישה.
- `metrics → {growth, balance_score}` → מדד הצמיחה + (our) מדד פלנגרם.
- `timeline[]` (yearly `{date, age, net_val, loan_val, invested}`) → `netval_plot`.
- `focal_points[]` (היום, each loan payoff w/ freed cashflow, פרישה, סוף תחזית) —
  not surfaced on this page yet but available for tooltips/markers.

These cover the **KPI row + שווי נקי panel** with no new modeling.

### Gap A — גרף נכסים (asset_plot): per-asset lines over time

Plangram's `asset_plot` (`cashflow-schema.json`) is a **stacked area, 7 datasets**:
```
עובר ושב · נכס נדלן 1 · שווי השתלמות לעצמאים ·
שווי קרן השתלמות - linx · שווי קרן השתלמות - טרנזיט ·
שווי קרן השתלמות Chase · שווי קרן חירום
```
i.e. one line per **asset entity** (`BankAccount`, `RealEstate`, `Keren`,
`Portfolio`, emergency fund), each projected forward (cash flat or growing at its
`rise`; funds compounding at their `interest`). There is also an `asset_complete_plot`
(6 datasets: תגמולים / פיצויים / קרנות / תיקים / נדלן / עובר ושב) — the same thing
grouped by **asset class** rather than by entity; pick one grouping for v1.

**Our gap is data, not rendering.** `projection.py` collapses the entire asset side
into a single scalar `liquid = bank − card_debt` plus the compounding `invested`
pool. To draw per-asset lines we need:
- **עובר ושב** — we have it: `snapshot.bank_balances_sum` (flat-lined, or grown by
  the freed-cashflow reinvestment we already model).
- **קרן חירום / תיקים / קרנות השתלמות / פנסיה** — *we do not capture these.* Our
  bank-scraping sources have no investment/pension holdings (see PRD 07). Until a
  portfolio source exists, גרף נכסים can only render the עובר ושב line + the modeled
  `invested` pool — a degraded but honest version. **Flag this on the page.**
- **נדל"ן (property value)** — also not scraped; `snapshot.note` already says
  "property value … NOT in these sources". Needs a manual-entry asset (a
  `RealEstate`-like entity) before it can appear.

### Gap B — גרף התחייבויות (loan_plot): per-loan balance over time

Plangram's `loan_plot` is a **stacked area, one dataset per loan** (the capture
shows 2: "הלוואה משכנתא - 10 שנים", "משלימה למשכנתא - פריים"). Each line is that
loan's **remaining balance month-by-month** until it hits zero.

**This one we can fully build today** — it's a by-product of work
`projection.amortize_loans()` / `simulate()` already does. Today the loop tracks
`l["balance"]` per loan each month but only records the *summed* `loan_val` into
`timeline`. To get `loan_plot` we change the timeline writer to also stash each
loan's balance:
```jsonc
// per timeline point, add:
"loans": { "<loan name>": <remaining balance>, ... }
```
then pivot into one dataset per loan name. `snapshot.loans[]` carries everything
needed (`balance`, `rate_pct`, `monthly_payment`, `payments_remaining`,
`name`/`category`), and these are already amortized correctly. We have **9 loans**
(7 Discount mortgage/מתווה, 2 Discount consumer, 1 Leumi aggregate straight-lined),
versus Plangram's 2 — so our chart is richer; consider collapsing by `category`
(mortgage / consumer) to a 2–3 line stack for legibility, mirroring Plangram.

## 7. Mapping to our data (summary)

| Page element | Plangram source | Our source | Status |
|---|---|---|---|
| מדד פלנגרם | proprietary score | `projection.metrics balance_score` (labeled ours) | built |
| מדד הצמיחה | growth metric | `projection.metrics growth` | built |
| הלוואות (KPI) | total liabilities | `snapshot.totals.total_debt` | built |
| נכסים (KPI) | asset total | bank-only today; full total needs portfolio/property | **partial** |
| נוכחי | net worth today | `projection.net_worth_today` | built |
| בפרישה | net worth @ retirement | `projection.net_worth_at_retirement` | built |
| age-80 caption | last timeline point | `projection.timeline[-1]` | built (verify horizon age) |
| שווי נקי chart | `netval_plot` | `projection.to_chart()` (single-series view) | built |
| גרף התחייבויות | `loan_plot` | per-loan timeline from `simulate()` | **gap B — buildable now** |
| גרף נכסים | `asset_plot` | per-asset lines | **gap A — needs portfolio/property data** |

## 8. Implementation plan (suggested)

**Phase 1 — wire what's built into a `/networth` view**
1. Add `data/networth.py` (or extend `cashflow.py`) that calls `projection.build()`
   and shapes a `networth.json`: `{ kpis: [...], net_worth: {today, retirement,
   end_caption}, charts: {netval, loan_plot, asset_plot} }`.
2. KPI row: hand מדד הצמיחה + (our) מדד פלנגרם straight from `projection.metrics`;
   נכסים/הלוואות from snapshot totals.
3. שווי נקי panel: נוכחי/בפרישה + the age-80 caption from the timeline tail;
   single-series `netval_plot`.

**Phase 2 — גרף התחייבויות (gap B, no new data)**
4. Extend `projection.simulate()` to record per-loan balances per timeline point
   (`point["loans"][name] = balance`), keeping the existing summed `loan_val`.
5. Pivot to a `loan_plot` envelope (one dataset per loan or per `category`).

**Phase 3 — גרף נכסים (gap A, needs new data sources)**
6. Render the honest degraded version now: עובר ושב line + modeled `invested` pool.
7. Once a portfolio source (PRD 07) and a manual property/`RealEstate` entity exist,
   add one dataset per asset → full `asset_plot`. Update the נכסים KPI to the true
   asset total at the same time.

**Deferred:** "אפשרויות גרף" series toggles; "הגדרות תחזית" scenario editing;
focal-point markers/tooltips on the charts.

## 9. Open questions

- **Horizon age in the caption** — Plangram's caption says **גיל 80**; our
  `CONFIG.end_age` is **90**. Match Plangram (cap at 80) or keep 90 and reword the
  caption? Note: `current_age` is derived from `BIRTH_DATE` (1997-11-23) in
  `projection.py` — accurate, no longer a placeholder.
- **Asset grouping for גרף נכסים** — per-entity (`asset_plot`, 7 lines) or
  per-class (`asset_complete_plot`, 6 lines)? Pick one.
- **Loan chart legibility** — render all 9 of our loans, or collapse to
  mortgage/consumer to mirror Plangram's 2-line stack?
- **Net-worth completeness** — until portfolio + property data exist, the נכסים KPI
  and גרף נכסים understate true net worth (snapshot is bank-only). Show a "tracked
  accounts only" disclaimer on the page (snapshot already carries the note).
- **Score parity** — same as Cashflow: ship our transparent מדד איזון as מדד פלנגרם,
  clearly labeled ours, rather than reverse-engineering the proprietary weighting?
