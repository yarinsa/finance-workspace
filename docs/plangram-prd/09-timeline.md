# PRD 09 — Timeline (ציר זמן)

> Reverse-engineered from Plangram's `/timeline` screen (titled **ציר זמן**).
> Hebrew (RTL), ILS (₪).
> Evidence: `captures/route-timeline.yml`, `captures/route-timeline.png`,
> `captures/cashflow-schema.json → timeline` (dense series) + `lifeevents` +
> `event_results`.

## 1. Summary

The Timeline screen answers *"what will each month of my financial future actually
look like?"* It renders the projection as a **vertical, month-by-month feed** down
a central time axis — one card per period (יוני 2026, יולי 2026, …) — where each
card is a **cashflow waterfall** of that month broken into four canonical buckets:

```
הכנסות (income)  →  הוצאות (expenses)  →  הלוואות (loans)  →  הפקדות לתיקים (portfolio deposits)
```

Over the top sits a **filter/legend bar** of toggleable series with counts, and
**life-events** (יעדים, תכנון פרישה) are overlaid as point markers on the axis at
their dates. The horizon is the full life path — the capture shows **626 remaining
months** (~52 years) with each series carrying ~630 points (loans 104 — they end
when paid off), consistent with the dense `timeline` array (~2000 points across
series) in the schema.

> **Canonical bucketing.** This income / expense / loans / portfolio-deposits split
> is **the authoritative top-level cashflow grouping** — it *fixes the bucketing
> gap flagged in PRD 01 §7b*, where loan repayments fail to reach the `loans`
> bucket from the raw ledger (drowned in `uncategorized`) and inter-account
> transfers inflate income/expense. Timeline separates **הלוואות** and **הפקדות
> לתיקים** out of "expenses" as first-class buckets; adopt these four as the
> single source of truth so the Cashflow page, the Metrics catalog, and Timeline
> all agree.

Like the rest of the suite this is a read-only render of `calculations.data` from
`GET /user/getcurrent?includeCalculations=true`. The full feed beyond the first few
months is **Plus-gated** in the captured (free) account — see §3.

The H1 links to a help article
(`/article/124/ציר-הזמן-הצצה-לאיך-יראה-כל-חודש-בעתיד-שלכם`).

## 2. Goals & non-goals

**Goals**
- Show a **per-period cashflow waterfall** (income → expenses → loans → portfolio
  deposits) for every month across the life horizon.
- Establish and reuse the **four-bucket canonical grouping** everywhere downstream.
- Overlay **life-events** (goals, retirement) as dated markers on the time axis.
- Let the user **filter** which series/buckets are visible and pick a year range.

**Non-goals (for v1)**
- Editing the plan from the timeline (income/expense/goals edited on their own
  screens — PRD 10 family). Timeline only renders.
- Per-transaction drill-down. Cards expand to the **bucket sub-breakdown**
  (the `details` list per timeline point), not to individual ledger rows.
- Replicating the full 626-month Plus feed in v1; ship the near-term window first.

## 3. Page anatomy

Layout confirmed from `route-timeline.yml` (RTL; right rail global nav, `/timeline`
= **ציר זמן** active). Content column, top to bottom:

```
┌─ ציר זמן  (H1)                                  [▶ הסבר על עמוד זה] ┐
│                                                                     │
│  ┌── FILTER / LEGEND BAR ────────────────────────────────────────┐ │
│  │ הכנסות(630)● הוצאות(630)● הלוואות(104)● הפקדות לתיקים(630)●     │ │
│  │ יעדים(4)●  תכנון פרישה(2)●            [▾ מציג כל השנים]         │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│      ●── יוני 2026 ───────────┐                                     │
│                    ┌──────────┴───────────────────────┐            │
│                    │ ▴ הכנסות            ₪30,000  [tag] │            │
│                    │   סך ההכנסה נטו של משק הבית ₪30,000│            │
│                    │ ▾ הוצאות            ₪11,663  [tag] │            │
│                    │ ▾ הלוואות           ₪1,606   [tag] │            │
│                    │ ▾ הפקדות לתיקים     ₪16,731  [tag] │            │
│                    └──────────────────────────────────┘            │
│      ●── יולי 2026 ───────────┐  (cards alternate left / right)     │
│                    ┌──────────┴───────────────────────┐            │
│                    │  … same four buckets …            │            │
│      ●── אוגוסט 2026 / ספטמבר 2026 …                                │
│                                                                     │
│  ┌── PLUS UPSELL (after first months) ──────────────────────────┐  │
│  │ 🗂 צפו בציר הזמן המלא שלכם · עוד 626 חודשים ממתינים לכם         │  │
│  │   • צפייה בכל האירועים הפיננסים העתידיים                        │  │
│  │   • תכנון מדויק של הכנסות, הוצאות והפקדות                        │  │
│  │   • מעקב אחר יעדים והלוואות לאורך זמן                            │  │
│  │   [⚡ לשדרוג לפלנגרם פלוס → /plus-signup]                        │  │
│  └────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

**Card anatomy** (from DOM): a period label (`יוני 2026`) anchored to an axis dot,
then four collapsible `heading[level=2]` rows, each a `button` with `{bucket name}
{₪ value}`. The currently-expanded bucket (הכנסות in the capture, `[expanded]`)
shows a sub-line: label (`סך ההכנסה נטו של משק הבית`) + amount. Each bucket has a
colored tag matching the legend dot. The other three rows are collapsed (chevron
`▾`).

**Legend / filter bar** — six toggle buttons, each `{series}({count})`:

| Series (HE) | Meaning | Count (capture) | Color (from screenshot) |
|---|---|:--:|---|
| הכנסות | income | 630 | purple/blue |
| הוצאות | expenses | 630 | green |
| הלוואות | loans | 104 | yellow |
| הפקדות לתיקים | portfolio deposits | 630 | purple |
| יעדים | goals (life-events) | 4 | orange |
| תכנון פרישה | retirement plan (life-events) | 2 | dark purple |

Counts = number of dated points per series over the horizon. Loans have fewer (104)
because they terminate when paid off — they drop out of later months. The four
cashflow buckets share the same monthly cadence (630 ≈ 52.5 yrs × 12).

**Year-range control** — `מציג כל השנים` (showing all years) dropdown scopes the
feed to a window.

**Plus gate** — after the first visible months the free account hits an upsell card
("צפו בציר הזמן המלא שלכם · עוד 626 חודשים ממתינים לכם") linking to `/plus-signup`.
The full feed is a Plus-tier feature; the free capture only exposes the near-term
window. For us there is no gate — we render the whole horizon.

## 4. Data model

Backed by three schema objects in `calculations.data`:

### `timeline[]` — the dense per-point series

Each point (`timeline_item_schema`):

```jsonc
{
  "value":       float,    // bucket amount for this point (₪ or %)
  "details":     [...],    // sub-breakdown rows (e.g. "סך ההכנסה נטו…": 30000)
  "date":        "str",    // period (month) this point belongs to
  "units":       "str",    // ₪ / %
  "category":    "str",    // which bucket: income / expense / loans / deposits / goal / retirement
  "color":       "str",    // legend color (matches the tag/dot)
  "text":        null,
  "progress":    null,     // populated for goal/event points (toward target)
  "targetValue": null      // populated for goal/event points
}
```

~2000 points total across all series. **`category`** is the bucket key that drives
both the legend grouping and which card row a point lands in. **`details`** is the
expand-panel content (the capture's `סך ההכנסה נטו של משק הבית` line). `progress` /
`targetValue` are non-null only for the event-type series (יעדים / תכנון פרישה),
encoding how close the projection is to that life-event's target.

To render the feed: group `timeline` by `date` (month) → one card; within a card
group by `category` → the four (+event) bucket rows; sum `value` per bucket; list
`details` in the expand panel.

### `lifeevents[]` — the event overlay

```jsonc
{ "name": "str", "date": "str" }   // e.g. a goal due date, a retirement date
```

Rendered as dated markers on the axis (the יעדים(4) / תכנון פרישה(2) series). Counts
in the legend match: 4 goal events + 2 retirement events in the capture.

### `event_results[]` — computed outcome per event

The projection's result for each life-event (whether/when it is funded). Drives the
`progress` / `targetValue` on the corresponding `timeline` points and any
pass/fail styling on the event markers.

## 5. Mapping to our data

The four canonical buckets map cleanly onto what we already have, but the values are
**projected forward**, not historic — so this is a projection-engine consumer, not a
ledger render:

| Bucket (HE) | Our source | Notes |
|---|---|---|
| **הכנסות** | recurring net income (snapshot `detected_monthly_salary` / income entities); `summary.total_income` as a baseline | Project forward as a recurring series; `details` = per-income-source rows. |
| **הוצאות** | `summary.by_category` minus loans/deposits, grouped to the running-expense bucket | **Must exclude inter-account transfers** (PRD 01 §7b) before this is trustworthy. |
| **הלוואות** | `snapshot.loans[]` amortization — `monthly_payment`, `payments_remaining`, `balance`, `rate_pct` | This is the fix for PRD 01 §7b: take loan service from the **snapshot schedule**, not the ledger `הלוואה`/`משכנתא` categories. Loans drop out when `payments_remaining` hits 0 → explains the 104 vs 630 count. `projection.py` already amortizes these month-by-month. |
| **הפקדות לתיקים** | portfolio/deposit contributions | ❌ **gap** — we do not yet classify deposits-to-portfolio (same missing input as the savings/investment-ratio metrics in PRD 08 §6). Until then this bucket is unknown; `projection.py` treats freed loan-payment cashflow as investable surplus, which is an analog but not the same line. |
| **יעדים / תכנון פרישה** (events) | goals entity + `retirement_age` config | ❌ needs the goals entity (Phase 3) and a configured retirement date. `projection.py` already emits retirement focal points. |

**Bucketing decision (adopt project-wide):** make
`{income, expense, loans, portfolio_deposits}` the canonical top-level grouping in
`data/cashflow.py` so the Cashflow expense pie, the Metrics catalog, and Timeline
all reconcile. Loans and deposits come from the **snapshot/projection**, not the raw
ledger categories — this sidesteps the ledger-noise problem entirely.

**Gaps:** (1) portfolio-deposit classification, (2) goals entity for the event
overlay, (3) transfer-filtering so the expense bucket is clean. The income and loan
buckets are computable today.

## 6. Implementation plan (suggested)

**Phase 1 — Near-term feed (computable today)**
1. Extend `projection.py` to emit a `timeline` array shaped like the schema:
   month-grouped points with `{ value, details, date, units, category, color }`
   for the **income** and **loans** buckets (income from recurring net salary;
   loans from the existing amortization). Expenses from the cleaned ledger baseline.
2. Render the vertical month-feed: axis + alternating cards, four collapsible bucket
   rows, expand → `details`. Reuse the legend/filter bar with per-series counts.

**Phase 2 — Deposits + events**
3. Add portfolio-deposit classification → the **הפקדות לתיקים** bucket.
4. Add the goals entity + retirement config → `lifeevents` / `event_results` and the
   יעדים / תכנון פרישה axis markers (with `progress` / `targetValue`).

**Phase 3 — Controls**
5. Year-range scoping (`מציג כל השנים`) and per-series toggles.

## 7. Open questions

- **Period granularity** — Plangram is strictly monthly across 626 months. Render
  every month, or coalesce to years for far-future periods to keep the feed usable?
- **Portfolio-deposit source** — explicit deposit transactions, scenario deposit
  fields, or derived from net-worth deltas? Blocks the fourth bucket (and the
  savings-ratio metrics in PRD 08).
- **Expense projection** — hold today's cleaned monthly expense flat, inflate it,
  or model per-category growth/decay (kids, mortgage end)? Plangram clearly varies
  it per period.
- **Event progress** — do we replicate `progress` / `targetValue` per goal event,
  or just place undecorated date markers in v1?
