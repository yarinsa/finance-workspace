# PRD 07 — Investments / Portfolio (השקעות שלי)

> Reverse-engineered from Plangram's `/portfolio` screen. Hebrew (RTL), ILS (₪).
> Evidence: `captures/route-portfolio.yml`, `captures/route-portfolio.png`,
> `captures/cashflow-schema.json`.
>
> ## ⚠️ Blocking data gap — read first
>
> **Our scraped sources do not capture investment holdings.** Every existing
> source (discount, discount-business, discount-mortgage, leumi, cal, amex, riseup)
> pulls **bank balances, card debt, transactions, and loans** — none of them returns
> brokerage positions, pension funds (קרנות פנסיה), study funds (קרנות השתלמות),
> managed portfolios (תיקי השקעות), or crypto. `snapshot.json` says so explicitly:
> *"property value and external savings/investments are NOT in these sources, so
> totals reflect bank balances and debts, not full net worth."*
>
> This page therefore **cannot be populated from our current data**. It needs a
> **new data source** (a brokerage/pension scraper, a manual-entry portfolio
> entity, or both). The rest of this PRD specs the screen so that source can be
> built against a known target — but ship-readiness is **blocked on that source**.

## 1. Summary

The Investments screen is the **portfolio tracker**: a list of investment vehicles
(study funds, pensions, managed portfolios, emergency fund, crypto) with their
balances, a total, a value-history chart, and allocation breakdowns. It answers
*"what's my portfolio worth, how is it allocated, and how is it performing?"*

In the capture the account is on a **free tier**, so most of the analytical surface
is gated behind a **פלנגרם פלוס** upsell (a modal overlays the page in
`route-portfolio.png`). What *is* visible for free: total portfolio value, a single
manually-tracked "קרן חירום" portfolio, and the allocation panels rendered from
that one holding. The value-history chart shows an **empty state** ("בקרוב יוצג כאן
גרף היסטוריית השווי / נתונים היסטוריים יצטברו לאחר מספר ימים") — Plangram only
starts the history series once it has been tracking for several days. **We hit the
same cold-start: even with a source, the history chart needs accumulated snapshots.**

## 2. Goals & non-goals

**Goals**
- List each investment portfolio with its balance, type, and a per-item edit
  affordance.
- Show total portfolio value with a period-over-period change (week / month / 3mo /
  year / all).
- Show allocation two ways: by portfolio (חלוקת התיקים) and by asset class
  (חלוקה לפי סוגי נכסים).
- Track value history over time (requires accumulated snapshots).

**Non-goals (for v1, even once data exists)**
- The "ייבוא חכם" (smart import) flow — auto-pulling positions from a brokerage.
- The advanced performance-analysis suite (the פלוס-gated card): real-time tracking,
  per-instrument breakdown across portfolios, growth analytics. Free tier shows the
  upsell; spec but defer.
- Editing/adding portfolios inline beyond a basic manual-entry form.

## 3. Page anatomy

Layout confirmed from `route-portfolio.yml` (RTL; same right-rail nav). Note the
free-tier **upsell modal** covers the center in the screenshot; the YAML shows the
full DOM behind it.

```
┌─ השקעות שלי  (H1) ─────────────────────────────────────────────────┐
│                                                                     │
│  ┌── שווי תיק כולל (H2) ───────────────────┐  [שבוע][חודש][3 חודשים] │
│  │  ₪34K                                   │  [שנה][הכל]  ← period   │
│  │  בשנה האחרונה  ₪0  ↑ 0%                  │                        │
│  └─────────────────────────────────────────┘                       │
│  ┌── value-history chart (EMPTY STATE) ───────────────────────────┐ │
│  │  "בקרוב יוצג כאן גרף היסטוריית השווי"                            │ │
│  │  "נתונים היסטוריים יצטברו לאחר מספר ימים"                        │ │
│  └────────────────────────────────────────────────────────────────┘
│                                                                     │
│  ┌── פירוט תיקי השקעות (H2) ─────[✎ ייבוא חכם] [+ הוספת תיק] ──────┐ │
│  │  ┌ קרן חירום ───────────────────────────────[✎ ערוך תיק]────┐  │ │
│  │  │  ₪34K   ניהול ידני   ✦ לעבור למתקדם                       │  │ │
│  │  └──────────────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────────┘
│                                                                     │
│  ┌── חלוקת התיקים (H4) ───────────────────────────────────────────┐ │
│  │  קרן חירום    34,000 ₪    100.0%                                │ │
│  └────────────────────────────────────────────────────────────────┘
│                                                                     │
│  ┌── חלוקה לפי סוגי נכסים (H4) ────────────────────────────────────┐ │
│  └────────────────────────────────────────────────────────────────┘
│                                                                     │
│  ┌══ פלוס upsell (overlays free tier) ════════════════════════════┐ │
│  │  "נתחו את ביצועי ההשקעות שלכם על פני כל תיקי ההשקעות שלכם"        │ │
│  │  ✓ מעקב בזמן אמת  ✓ מניות/קרנות/קריפטו במקום אחד                  │ │
│  │  ✓ היסטוריית שווי וצמיחה  ✓ פירוט ויזואלי של ההתפלגות             │ │
│  │  [⚡ לשדרוג לפלנגרם פלוס]   קראו עוד >                            │ │
│  └════════════════════════════════════════════════════════════════┘
└─────────────────────────────────────────────────────────────────────┘
```

The upsell links to `/article/125/ניהול-מתקדם-של-תיקי-השקעות` and `/plus-signup`.

## 4. Components

### שווי תיק כולל (total portfolio value)
- Big ₪ total = sum of all portfolio balances (capture: ₪34K, all from one holding).
- A change readout vs. the selected period: absolute (₪0) + percent (↑ 0%) with an
  up/down arrow. 0/0% here because there's only manual data and no history yet.
- **Period selector**: שבוע · חודש · 3 חודשים · שנה · הכל — re-scopes both the change
  readout and the history chart.

### Value-history chart
- Time-series of total portfolio value over the selected period.
- **Empty state** until enough daily snapshots accumulate ("…יצטברו לאחר מספר ימים").
- This is a **cold-start** component: it needs a stored history, not a single point.

### פירוט תיקי השקעות (portfolio breakdown)
- A list, one card per portfolio. Each card: name, balance, management mode
  ("ניהול ידני" = manual vs. advanced/linked), a per-item **✎ ערוך תיק** edit link
  (`#profile/assets/portfolio/edit/<id>`), and a "✦ לעבור למתקדם" upgrade nudge.
- Header actions: **✎ ייבוא חכם** (smart import) and **+ הוספת תיק** (add portfolio).
- Backed by the `Portfolio` entity (`cashflow-schema.json → assets`): fields
  include `description`, `balance`, `manualBalance`, `interest`, `fee`,
  `profitFraction`, `designation`, `type`, `goal`, `managementType`, `allowWithdraw`.

### קרן חירום (emergency fund)
- A **special-cased portfolio** surfaced as its own card (capture: ₪34K, 100% of the
  portfolio). Corresponds to the `GlobalEmergencyFund` goal entity
  (`globalEmergencyFund` on the scenario) and/or a `Portfolio` flagged as the
  emergency fund. Plangram tracks an **אחוז עמידה בקרן חירום** metric (% of target
  funded) and **חוסר בקרן חירום** (shortfall ₪) — see `today_metrics`.

### חלוקת התיקים (allocation by portfolio)
- Per-portfolio share of the total: name · ₪ amount · % (capture: קרן חירום /
  34,000 ₪ / 100.0%). Likely a pie/donut in the full UI (`assetpies` in the schema).

### חלוקה לפי סוגי נכסים (allocation by asset type)
- Breakdown by asset **class** rather than by portfolio — e.g. מניות / אג"ח / מזומן /
  קריפטו / נדל"ן. Empty in the capture (only one cash-like holding). Maps to the
  `asset_complete_plot` grouping (תגמולים/פיצויים/קרנות/תיקים/נדלן/עו"ש) and to
  `assetpies`. Needs per-instrument class tags the current data lacks entirely.

### Performance analysis (פלוס-gated)
- The upsell card promises: real-time portfolio tracking; stocks/funds/crypto in one
  place; value history & growth; visual allocation breakdown. This is the premium
  analytical layer — **spec, but defer** behind the same gate.

## 5. Data model

Plangram's investment vehicles live in the `assets` profile section
(`cashflow-schema.json`), each its own entity type:

| Entity (HE) | `type` | Carries | Plangram chart line |
|---|---|---|---|
| תיקי השקעות | `Portfolio` | balance, interest, fee, profitFraction, type, managementType | "תיקים" |
| קרנות השתלמות | `Keren` | balance, interest, fee/fee2, owner, status | "שווי קרן השתלמות - …" |
| נכסים פנסיונים | `Pension` | balance, interest, fees, תגמולים/פיצויים split | `pensias_plot` / "תגמולים"/"פיצויים" |
| קרן חירום | `GlobalEmergencyFund` | amount (target) | "שווי קרן חירום" |
| נכסי נדל"ן | `RealEstate` | value, rise, buy/sell | "נדלן" |
| חשבונות בנק | `BankAccount` | balanceCurrent | "עובר ושב" |

Forward projection of these is what feeds `asset_plot` / `asset_complete_plot` /
`assetpies` (PRD 06 §6, Gap A). The **portfolio page** itself is mostly the
*present-value* view (balances, allocation, history) of the same entities.

## 6. Mapping to our data — the gap, in detail

| Page element | Needs | Have today? |
|---|---|:--:|
| שווי תיק כולל | portfolio balances | ❌ no investment holdings scraped |
| value-history chart | accumulated value snapshots | ❌ (and cold-start even with a source) |
| פירוט תיקי השקעות | per-portfolio entities | ❌ |
| קרן חירום | emergency-fund balance + target | ⚠️ target could be a config; balance not scraped |
| חלוקת התיקים | balances → shares | ❌ |
| חלוקה לפי סוגי נכסים | per-instrument asset-class tags | ❌ |
| performance analysis | live positions + history | ❌ (premium) |

**Nothing on this page maps to an existing source.** The closest thing we have is
the spending category `השקעה וחיסכון` in `snapshot.spending.by_category` — but it's
₪0.04 all-time, i.e. effectively noise, and it's a *transaction tag*, not a holdings
balance. There is no portfolio, pension, study-fund, or property balance anywhere in
our normalized layer.

### What a new source must provide
To build this page we need a source emitting an `investments` (or `portfolios`)
entity to the common envelope (`{source, entity, generated_at, records:[...]}`),
each record roughly:
```jsonc
{
  "name": "...", "type": "keren|pension|portfolio|emergency|crypto|realestate",
  "asset_class": "equity|bond|cash|crypto|realestate|mixed",
  "balance": <number ₪>, "currency": "ILS",
  "management": "manual|linked", "as_of": "<date>"
}
```
Candidate sources (each is its own `add-bank-source` scraper or a manual entry):
- **קרנות השתלמות / פנסיה** — a pension-clearinghouse scrape (e.g. מסלקה פנסיונית /
  Mountain / employer portals).
- **תיקי השקעות** — a brokerage scrape (e.g. IBKR, Meitav, etc.).
- **קרן חירום** — likely just a designated bank/savings balance we *do* scrape, or a
  manual figure.
- **נדל"ן** — manual-entry value (same gap PRD 06 flags).

Until then, the page renders only an empty/placeholder state — which is exactly what
Plangram's own free tier shows.

## 7. Implementation plan (suggested)

**Phase 0 — unblock: add an investments source (prerequisite)**
1. Decide the first source (manual-entry portfolio entity is the cheapest unblock;
   a pension/brokerage scraper is the real one). Emit `investments` records per the
   envelope above. `digest.py` should fold them into `snapshot.json` as an `assets`/
   `portfolios` block and into a portfolio total.
2. Start a **snapshot-history** append (PRD 01 §7b already wants this) so the
   value-history chart can ever populate — store `{date, total, by_portfolio}` each
   digest run.

**Phase 1 — present-value view (once balances exist)**
3. `data/portfolio.py` reads the investments block → emits `portfolio.json`:
   `{ total, change_by_period, portfolios:[...], allocation_by_portfolio,
   allocation_by_class, emergency_fund:{balance,target,pct} }`.
4. Render: total + period selector, breakdown list (+ add/edit), חלוקת התיקים,
   חלוקה לפי סוגי נכסים, emergency-fund card with אחוז עמידה בקרן חירום.

**Phase 2 — history & performance**
5. Value-history chart from the accumulated snapshot-history (period-scoped).
6. Performance analytics (growth %, per-instrument) — mirror the פלוס card; can stay
   behind our own gate or ship fully since we have no tiers.

## 8. Open questions

- **Which investment source first?** Manual entry (fast, low fidelity) vs. a
  pension/brokerage scraper (real, more work). *(needs user input)*
- **Emergency-fund definition** — is it a designated savings/bank balance we already
  scrape, or a separate tracked portfolio + a target from config? Drives
  אחוז עמידה בקרן חירום / חוסר בקרן חירום.
- **Asset-class tagging** — חלוקה לפי סוגי נכסים needs each holding classified
  (equity/bond/cash/crypto/realestate). Manual tags, or derive from the source?
- **History cold-start** — even after wiring a source, the value-history chart stays
  empty until snapshot-history accumulates. Acceptable for v1 (matches Plangram), or
  backfill from any dated source data we can find?
- **Property** — track נדל"ן here, on /networth, or both? It straddles "asset
  allocation" and "net worth"; PRD 06 also flags it missing.
