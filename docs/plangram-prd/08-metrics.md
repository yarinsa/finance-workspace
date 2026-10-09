# PRD 08 — Progress / Metrics (התקדמות)

> Reverse-engineered from Plangram's `/metrics` screen (titled **התקדמות**).
> Hebrew (RTL), ILS (₪).
> Evidence: `captures/route-metrics.yml`, `captures/route-metrics.png`,
> `captures/cashflow-schema.json → today_metrics` (the full 28-metric catalog).

## 1. Summary

The Progress screen is Plangram's **metric scoreboard** — the canonical catalog
view of every health metric the engine computes, scored and tracked over time. It
is the read-only sibling of the Cashflow dashboard (PRD 01): Cashflow surfaces a
curated 5-card subset inline, while `/metrics` lays out **the entire roster** of
metrics that carry `show_in_progress_tab: true` (16 of the 28 in `today_metrics`),
split into two sections:

1. **מדדים מובילים** (leading metrics) — the four headline scored cards:
   אחוז חיסכון, חתיכה עודפת, אחוז החזר חוב, חתיכה חסרה. Big, with a verdict pill
   and a sparkline of historic values.
2. **מדדים נוספים** (additional metrics) — twelve secondary cards: הכנסות,
   הוצאות, תזרים, אחוז עמידה בקרן חירום, הפקדה מתוכננת, יחס השקעות, שווי נקי,
   מדד הצמיחה, מדד פלנגרם, אחוז עמידה ביעדים, אחוז עמידה ביעד פרישה, מדד האיזון.
   (The captured DOM clips before סכום להורשה / אחוז עמידה ביעד פרישה fully scroll
   in, but the schema marks them `show_in_progress_tab: true` — see §4.)

Each card is one entry from `today_metrics` rendered as: title (H5) + formatted
value + verdict pill. Per-metric history comes from `metric_historic_values` and
drives the sparkline / trend under each card. There is no editing here — it is a
pure render of the precomputed model (`calculations.data` in
`GET /user/getcurrent?includeCalculations=true`).

The H1 links to a help article (`/article/63/דף-התקדמות`) — inline help affordance,
same pattern as Cashflow.

## 2. Goals & non-goals

**Goals**
- Present the **complete catalog** of scored metrics in one place, grouped into
  leading vs. additional, each with its good/warning/bad verdict.
- Show each metric's **trend over time** (sparkline from historic values) so the
  user sees whether they are improving.
- Be the single authoritative list of *what every metric means* — descriptions
  surfaced from the schema.

**Non-goals (for v1)**
- Editing any underlying entity (income/expense/goals/assets live on their own
  screens — PRD 10 family).
- Re-deriving the proprietary composite (מדד פלנגרם / מדד האיזון) exactly; we ship
  our own transparent score, clearly labeled as ours (consistent with PRD 01 §7c).
- Per-metric drill-down pages. v1 is the catalog grid only.

## 3. Page anatomy

Layout confirmed from `route-metrics.yml` (RTL; right rail is the global section
nav; `/metrics` = **התקדמות** is the active item). Content column, top to bottom:

```
┌─ התקדמות  (H1)                                  [▶ הסבר על עמוד זה] ┐
│                                                                     │
│  מדדים מובילים  (H2)                                                 │
│  ┌──────────────────────┐  ┌──────────────────────┐                │
│  │ אחוז חיסכון           │  │ חתיכה עודפת           │  (2×2 grid)    │
│  │   0%                  │  │   ₪16.7K              │                │
│  │   [לא משהו]  ~~spark~~ │  │   [לא משהו]  ~~spark~~ │                │
│  ├──────────────────────┤  ├──────────────────────┤                │
│  │ אחוז החזר חוב         │  │ חתיכה חסרה            │                │
│  │   5%                  │  │   ₪0                  │                │
│  │   [מעולה]   ~~spark~~  │  │   [מעולה]   ~~spark~~  │                │
│  └──────────────────────┘  └──────────────────────┘                │
│                                                                     │
│  מדדים נוספים  (H2)                                                  │
│  ┌──────────┐┌──────────┐┌──────────┐   (responsive grid, ~3-up)   │
│  │ הכנסות   ││ הוצאות   ││ תזרים    │                              │
│  │ ₪30K     ││ ₪13.3K   ││ ₪16.7K   │                              │
│  │[חסר מידע]││[חסר מידע]││ [מעולה]  │                              │
│  └──────────┘└──────────┘└──────────┘                              │
│  אחוז עמידה בקרן חירום · הפקדה מתוכננת · יחס השקעות · שווי נקי ·     │
│  מדד הצמיחה · מדד פלנגרם · אחוז עמידה ביעדים · אחוז עמידה ביעד פרישה │
│  · סכום להורשה · מדד האיזון                                          │
└─────────────────────────────────────────────────────────────────────┘
```

Card anatomy (from the DOM): `heading[level=5]` (name) → `generic` (formatted
value, e.g. `₪16.7K`, `0%`, `100`) → `text` verdict pill.

### Verdict pills observed

| `rank` | Pill text (HE) | Color | Meaning |
|---|---|---|---|
| `good` | מעולה | green | healthy |
| `bad` | לא משהו | red | needs attention |
| `null` (value present) | חסר מידע | grey | informational / unscored, or input missing |

Value formatting: ₪ uses compact notation (`₪16.7K`, `₪2.6M`, `₪53.8M`); `%`
metrics show whole percents; unitless scores show a bare number (`100`).

## 4. The metric catalog (authoritative)

All 28 `today_metrics` entries. **In progress tab** = `show_in_progress_tab`; the
two sections in §3 are exactly the `true` rows (leading four broken out first).
**We compute** = already produced by `data/cashflow.py` / `data/projection.py`.

| # | Metric (HE) | Units | higher_is_better | In progress tab | Section | Verdict / rank logic (from schema) | Description | We compute? |
|---|---|:--:|:--:|:--:|---|---|---|:--:|
| 1 | **אחוז חיסכון** (savings %) | % | null | ✅ | leading | scored `bad` in capture; threshold-based | אחוז הכסף המופנה לחיסכון מתוך ההכנסה הכוללת נטו | ⚠ proxy¹ |
| 2 | **חתיכה עודפת** (surplus piece) | ₪ | null | ✅ | leading | scored `bad` (surplus *not* routed to investing is undesirable) | התזרים הפנוי שלא מנותב להשקעות | ❌² |
| 3 | **אחוז החזר חוב** (debt-repayment %) | % | false | ✅ | leading | lower is better; `good` below threshold | שיעור החזר הלוואות מתוך סך ההוצאות החודשיות | ✅ |
| 4 | **חתיכה חסרה** (missing piece) | ₪ | false | ✅ | leading | lower is better; `good` at ₪0 | חתיכה המייצגת את הפער להשלמת כלל היעדים שלכם לאורך כל מסלול החיים | ❌³ |
| 5 | **הכנסות** (income) | ₪ | null | ✅ | additional | unscored (informational) | — | ✅ |
| 6 | **הוצאות** (expenses) | ₪ | null | ✅ | additional | unscored (informational) | — | ✅ |
| 7 | **תזרים** (cashflow) | ₪ | true | ✅ | additional | `good` when positive | מייצג את ההפרש בין ההכנסות להוצאות ללא התחשבות בכסף המופנה לחיסכון | ✅ |
| 8 | **אחוז עמידה בקרן חירום** (emergency-fund coverage %) | % | null | ✅ | additional | unscored in capture; 100% = funded | — | ❌⁴ |
| 9 | **הפקדה מתוכננת** (planned deposit) | ₪ | null | ✅ | additional | unscored | — | ❌² |
| 10 | **יחס השקעות** (investment ratio) | % | null | ✅ | additional | scored `bad` in capture | אחוז הכסף המופנה לחיסכון מתוך התזרים הפנוי | ❌² |
| 11 | **שווי נקי** (net worth) | ₪ | null | ✅ | additional | unscored (informational) | — | ✅ |
| 12 | **מדד הצמיחה** (growth index) | % | true | ✅ | additional | `good` when positive growth | מייצג את קצב הגידול בשווי הנקי בעת הקרובה | ✅⁵ |
| 13 | **מדד פלנגרם** (Plangram score) | — | true | ✅ | additional | `good`; composite 0–100 | מדד פלנגרם מיוצג על ידי מספר בין 0-100… איזון נכון בין ההווה לעתיד | ⚠ ours⁶ |
| 14 | **אחוז עמידה ביעדים** (goal compliance %) | % | null | ✅ | additional | unscored; 100% = on track | — | ❌³ |
| 15 | **אחוז עמידה ביעד פרישה** (retirement-goal compliance %) | % | null | ✅ | additional | unscored; 100% = on track | — | ❌³ |
| 16 | **סכום להורשה** (inheritance amount) | ₪ | null | ✅ | additional | unscored (informational) | — | ❌³ |
| 17 | **מדד האיזון** (balance index) | ₪ | null | ✅ | additional | scored `good`; signed (positive = increase cashflow, negative = surplus in עו"ש) | מדד האיזון אומר כמה "תזרים" חסר כדי להתכנס ליעדנו… | ⚠ ours⁶ |
| 18 | עודף בעובר ושב (current-account surplus) | ₪ | null | ❌ | — | unscored | — | ✅ |
| 19 | משתנה מצב תזרים (cashflow-state flag) | — | null | ❌ | — | internal flag | — | ❌ |
| 20 | חתיכה עודפת בערך מוחלט (surplus piece, abs) | ₪ | null | ❌ | — | internal | — | ❌ |
| 21 | משתנה מצב חיסכון (savings-state flag) | — | null | ❌ | — | internal flag | — | ❌ |
| 22 | דרישת השקעה עודפת (required excess investment) | ₪ | null | ❌ | — | internal | — | ❌ |
| 23 | חוסר בקרן חירום (emergency-fund shortfall) | ₪ | null | ❌ | — | internal (₪ behind 8) | — | ❌⁴ |
| 24 | מדד גירעון (deficit index) | % | null | ❌ | — | internal | — | ❌ |
| 25 | רק תיקים רעים (bad-portfolios only) | — | null | ❌ | — | internal toggle | — | ❌ |
| 26 | רק תיקים סולידיים (solid-portfolios only) | — | null | ❌ | — | internal toggle | — | ❌ |
| 27 | שנה קודמת (previous year) | — | null | ❌ | — | internal comparison anchor | — | ❌ |
| 28 | שנה לפני 6 שנים (year-6-ago) | — | null | ❌ | — | internal comparison anchor | — | ❌ |

Footnotes:
1. **אחוז חיסכון** — `cashflow.py` ships a *proxy* (`max(net,0)/income`), flagged
   `estimated`. The true definition is "money routed to savings ÷ net income",
   which needs a savings-classification of transactions (see §6 / PRD 01 §8).
2. **חתיכה עודפת / יחס השקעות / הפקדה מתוכננת** — all hinge on the same missing
   input: *which* free cashflow is being routed to investing vs. left idle. We do
   not yet classify deposits-to-portfolio, so these are not computed.
3. **חתיכה חסרה / אחוז עמידה ביעדים / אחוז עמידה ביעד פרישה / סכום להורשה** —
   goal-compliance family. Need the **goals** entity + projection engine
   (`goal_compliance` keys: `passive_coverage`, `portfolio_goals`, `missing_piece`,
   `freedom`, `inheritance`). Deferred to PRD 01 §7c "Phase 3".
4. **אחוז עמידה בקרן חירום / חוסר בקרן חירום** — need a target emergency-fund size
   (`scenario.globalEmergencyFund`) compared against liquid balances from
   `snapshot.json`. Cheap to add once a target is configured.
5. **מדד הצמיחה** — `projection.py` emits a 5-yr real net-worth slope under this
   name; treat as a close analog, not a byte-identical match.
6. **מדד פלנגרם / מדד האיזון** — proprietary composites. `projection.py` ships
   **מדד איזון** as our own transparent 0–100 score, explicitly *not* Plangram's
   number (PRD 01 §7c). Same stance applies to מדד פלנגרם.

## 5. Data model

Two schema objects back this page:

- **`today_metrics[]`** — the catalog above. Each item:
  `{ name, units, rank, higher_is_better, show_in_progress_tab, description }`.
  `rank ∈ {good, bad, null}` drives the pill; `units ∈ {₪, %, ""}` drives
  formatting; `show_in_progress_tab` gates membership on this page.
- **`metric_historic_values`** + **`metric_historic_values`-style series** — the
  per-metric time series powering each card's sparkline / trend. (Schema names it
  alongside `timeline`; one entry per metric over past periods.)

The page reads these straight out of `calculations.data` in
`GET /user/getcurrent?includeCalculations=true`. No write path.

## 6. Mapping to our data

Our equivalent is already partly built in `data/cashflow.py::build_metrics` (+
`data/projection.py`). It emits, with the same Hebrew names and a `rank` verdict
via `_verdict()`:

| Plangram metric | Our source field | Status |
|---|---|---|
| תזרים | `month.net` (income − expense from ledger) | ✅ done |
| הכנסות | `summary.total_income` (monthly) | ✅ done |
| הוצאות | `abs(summary.total_spent)` (monthly) | ✅ done |
| שווי נקי | `snapshot.totals.tracked_net_position` | ✅ done |
| אחוז החזר חוב | `snapshot.totals.monthly_loan_service ÷ expense` | ✅ done (prefer snapshot loan service — ledger loan bucket is noisy, PRD 01 §7b) |
| אחוז חיסכון | `max(net,0)/income` | ⚠ proxy — needs savings classification |
| עודף בעובר ושב | `snapshot.totals.bank_balances_sum` | ✅ done |
| מדד הצמיחה | `projection.py` 5-yr real slope | ✅ analog |
| מדד איזון | `projection.py` own 0–100 score | ⚠ ours, not Plangram's |
| חתיכה עודפת / יחס השקעות / הפקדה מתוכננת | — | ❌ needs savings/deposit classification |
| חתיכה חסרה / אחוז עמידה ביעדים / ...ביעד פרישה / סכום להורשה | — | ❌ needs goals entity + projection (Phase 3) |
| אחוז עמידה בקרן חירום / חוסר בקרן חירום | liquid balances vs. configured target | ❌ needs an emergency-fund target |

**Gaps to close (in priority order):**
1. **Savings/deposit classification** — unlocks אחוז חיסכון (true), חתיכה עודפת,
   יחס השקעות, הפקדה מתוכננת. This is the single highest-leverage input.
2. **Emergency-fund target** in config → אחוז עמידה בקרן חירום + חוסר בקרן חירום.
3. **Goals entity + projection** → the four goal-compliance metrics.
4. **Snapshot history** (append per digest) → real savings-delta and proper
   per-metric sparklines (we currently store one point; PRD 01 §7b).

## 7. Implementation plan (suggested)

**Phase 1 — Catalog render (mostly built)**
1. Extend `cashflow.py` output with a `progress` block: the full catalog filtered
   to `show_in_progress_tab`, each item `{ name, units, value, rank,
   higher_is_better, description, section }` where `section ∈ {leading, additional}`.
   Mark not-yet-computed metrics with a `חסר מידע` placeholder rank.
2. Render two H2 sections (מדדים מובילים / מדדים נוספים) as card grids, reusing the
   verdict-pill component from the Cashflow page.

**Phase 2 — History / sparklines**
3. Append a `snapshot-history/` record each digest; derive `metric_historic_values`
   per metric → sparkline under each card.

**Phase 3 — Fill the gaps**
4. Add savings-classification → savings/investment-ratio family.
5. Add emergency-fund target + goals entity → coverage and compliance metrics.

## 8. Open questions

- **Leading-four selection** — Plangram's leading set (אחוז חיסכון / חתיכה עודפת /
  אחוז החזר חוב / חתיכה חסרה) differs from the Cashflow 5-card set. Mirror their
  split exactly, or pick our own four based on what we can compute well?
- **חסר מידע vs. hide** — show uncomputable metrics greyed with a "חסר מידע" pill
  (matches Plangram), or omit them until we can compute them?
- **Score parity** — same question as PRD 01 §8: replicate מדד פלנגרם, or keep our
  own clearly-labeled score and skip the proprietary one entirely?
- **History depth** — Plangram tracks `metric_historic_values` across years; we
  start from today. How far back do we backfill (re-run digest over old raw dumps)?
