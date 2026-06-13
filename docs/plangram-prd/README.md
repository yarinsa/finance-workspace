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

| # | Feature | PRD | Source captured | Impl |
|---|---|---|:--:|:--:|
| 01 | **Cashflow (תזרים כספי)** — KPI dashboard + projections | [01-cashflow.md](01-cashflow.md) | ✅ | Phase 1 ✅ · Phase 2 ✅ |
| — | Income (הכנסות) | _todo_ | |
| — | Expenses (הוצאות) | _todo_ | |
| — | Goals (יעדים) | _todo_ | |
| — | Assets (נכסים) | _todo_ | |
| — | Liabilities (התחייבויות) | _todo_ | |
| — | Recommendations (המלצות) | _todo_ | |
| — | Progress / Metrics (התקדמות) | _todo_ | |
| — | Scenario planning (תכנון פלוס) | _todo_ | |

We are **starting with Cashflow** per request.

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
