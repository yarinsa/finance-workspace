# Plangram — Feature PRDs (reverse-engineered)

Product reference docs distilled from **Plangram** (`plangram.co.il`), an Israeli
personal financial-planning product. Captured by driving a logged-in browser over
CDP and reading the authenticated API that feeds each screen, then scrubbing all
personal financial values down to schema + labels.

The goal: reimplement these features against **our own** unified ledger /
snapshot (see root `CLAUDE.md`) instead of Plangram's backend. Each PRD is written
to be implementable — it documents *what the screen shows, where each number comes
from, and how to compute it from our data*.

## Status

| # | Feature (route) | PRD | Captured | Impl |
|---|---|---|:--:|:--:|
| 01 | **Cashflow** (`/cashflow`, תזרים כספי) — KPI dashboard + projections | [01-cashflow.md](01-cashflow.md) | ✅ | ✅ app (KPIs, net-worth curve, expense breakdown) |
| 02 | **Overview** (`/overview`) — composite home dashboard | [02-overview.md](02-overview.md) | ✅ | ✅ app (net worth, today cashflow, top metrics, stale nudge) |
| 03 | **Plan summary** (`/summary`, סיכום התוכנית) — profile-inputs cockpit | [03-summary.md](03-summary.md) | ✅ | ⚠️ app (journey curve + section status map) |
| 04 | **Goals** (`/goals`, יעדים) — personal/general goals + compliance | [04-goals.md](04-goals.md) | ✅ | ✅ app (4 general cards + personal goals; Phase 1+2) |
| 05 | **Recommendations** (`/recommendations`, המלצות) — advice/nudge engine | [05-recommendations.md](05-recommendations.md) | ✅ | ⚠️ app (heuristic nudges; no rules engine) |
| 06 | **Net worth** (`/networth`, שווי נקי) — assets/liabilities over time | [06-networth.md](06-networth.md) | ✅ | ✅ app (assets/liabilities + lifetime curve) |
| 07 | **Portfolio** (`/portfolio`, השקעות) — investment holdings/allocation | [07-portfolio.md](07-portfolio.md) | ✅ | ⛔ stub — needs new source |
| 08 | **Progress / Metrics** (`/metrics`, התקדמות) — full 28-metric catalog | [08-metrics.md](08-metrics.md) | ✅ | ✅ app (full metric catalog) |
| 09 | **Timeline** (`/timeline`, ציר זמן) — monthly cashflow waterfall + life events | [09-timeline.md](09-timeline.md) | ✅ | ⚠️ app (focal points; monthly waterfall = Phase 2) |
| 10 | **My Plan / Plus** (`/my-plan`, תכנון פלוס) — scenario what-if simulator | [10-my-plan-plus.md](10-my-plan-plus.md) | ⛔ Plus-gated | ⛔ stub — Plus-gated, not captured |
| 11 | **Goals editor** (`/goals/edit`) — set targets + add/edit/delete goals | [11-goals-editor.md](11-goals-editor.md) | native | ✅ CLI (Phase 1) · ⚠️ in-app editor (Phase 2) pending |

All ten features captured and routed in the React app (`app/`). **5 render real
data** (Cashflow, Overview, Net worth, Metrics, Goals), **3 are partial** (Summary,
Recommendations, Timeline), **2 are honest stubs** (Portfolio, My Plan).
Income/expenses are documented inside the Cashflow, Timeline, and Metrics PRDs
(they're profile sections of the same payload, not standalone screens).

**Goals** (PRD 04) is the first feature backed by a **user-owned store**
(`data/goals/goals.json`) rather than scraping — `python3 data/goals.py` digests it
with the snapshot's liquid buffer and the projection's retirement/estate figures
into `data/digested/goals.{json,md}`. Phase 1 (emergency-fund coverage) + Phase 2
(retirement / inheritance) + per-goal progress are live; the probabilistic
"% סיכוי" model (PRD §4b) is deferred in favour of a transparent on-track verdict.

### Next feature (the recurring blocker)

The repeated gap across Overview §6, Summary §6, Net worth, and Portfolio is one
thing: **we don't capture pension / השתלמות / portfolio / real-estate assets.**
Resolving it once (manual-entry `data/assets.json` to start, scrapers later)
fixes net worth, unlocks the `פיזור נכסים` asset-mix donut, and flips ~5 metrics
(יחס השקעות, אחוז חיסכון, הפקדה מתוכננת, …) across 3 screens. That is the
highest-leverage next build. → see [07-portfolio.md](07-portfolio.md).

### Cross-cutting findings from the full sweep

- **One payload feeds everything.** Every screen renders from a single
  `GET /user/getcurrent?includeCalculations=true` — there is no per-screen API.
- **The recurring blocker is one thing:** classifying *money routed to
  savings/portfolio*. It gates אחוז חיסכון (true), חתיכה עודפת, יחס השקעות,
  הפקדה מתוכננת, and the Timeline "deposits" bucket. Resolve this once → unlocks
  ~5 metrics across 3 features.
- **The Timeline four-bucket split** (income → expenses → loans → portfolio
  deposits) is the **canonical grouping that fixes the §7b loan/transfer
  bucketing gap** in Cashflow — sourced from snapshot/projection, not the noisy
  ledger categories. Adopt it everywhere.
- **Two features need new data we don't scrape:** Portfolio (investment/pension
  holdings) and Goals (user-entered intent). Both need a new source/store.
- **`/my-plan` (Plus tier)** is a paywalled empty iframe — not capturable without
  a subscription.

## How the source was captured

Plangram is a single-page app. The entire financial model for the logged-in user
arrives in **one call**:

```
GET /user/getcurrent?includeCalculations=true   → ~1.3 MB
GET /Scenario/List                               → scenario roster
```

Both responses are **double-encoded** (a JSON *string* containing JSON — the same
gotcha as our RiseUp scrape). The cashflow screen is a pure *render* of
`calculations.data` from that payload; there is no per-widget API.

`captures/` holds the scrubbed evidence:

- `cashflow-schema.json` — metric catalog (28 metrics), chart catalog (15 plots),
  profile-section catalog, and the timeline/focal-point/scenario schemas. **No
  personal values.**
- `cashflow-dom.yml` — accessibility snapshot of the rendered page (panel layout).
- `cashflow-top.png` — screenshot of the dashboard above the fold.
- `scenario-list.json` — `/Scenario/List` envelope + item schema.

## Mapping to our data

Our workspace already produces the raw materials these features need:

- `data/digested/transactions.json` — unified deduped ledger (income/expense, by
  category, by origin) → feeds the **cashflow summary** and income/expense charts.
- `data/digested/snapshot.json` — balances, card debt, loans/mortgage, salary →
  feeds **net worth (עו"ש)**, debt-repayment %, and the projection seed.

The forward-looking projections (net worth to retirement, focal points, life
events) are the part we don't have yet — they require a small projection engine
documented in the cashflow PRD.
