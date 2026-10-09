# PRD 02 — Overview / Home dashboard (מבט על)

> Reverse-engineered from Plangram's `/overview` screen. Hebrew (RTL), ILS (₪).
> Evidence: `captures/route-overview.yml`, `captures/route-overview.png`,
> `captures/cashflow-schema.json`.

## 1. Summary

`/overview` is the product's **landing page** — the first screen after login and
the `מבט על` ("a look") nav item. It is a *composite dashboard*: it does not own
any new computation; it re-surfaces, in a glanceable card grid, the same numbers
that the dedicated feature screens (Cashflow, Recommendations, Progress, Net
worth, Asset allocation) render in full. Its job is **orientation, not depth** —
"is everything OK, and where should I click next?"

Top-to-bottom, the page composes seven blocks:

1. **Greeting** — `היי {name},` + subtitle "a quick look at your financial picture".
2. **Stale-data nudge** — a banner prompting the user to refresh balances, with a
   `לעדכון יתרות` CTA.
3. **Two headline tiles** — `שווי נקי נוכחי` (current net worth, with a
   week-over-week delta chip) and `הסיכוי לעמידה ביעדים` (goal-funding probability,
   the butterfly/Plangram-piece motif).
4. **Profile-ready + Recommendations** — `הפרופיל שלך מוכן!` onboarding card next
   to a `המלצות` preview (top 3 of 6, link to all).
5. **סימולציית פלנגרם** — the future-simulation hero: the `מדד פלנגרם` score with
   its verbal verdict and the income/expense legend of the simulation chart.
6. **מדדים מובילים** — a 4-up KPI strip (אחוז חיסכון / חתיכה עודפת / אחוז החזר חוב
   / חתיכה חסרה), each with a good/bad pill, linking to the Progress page.
7. **התזרים + פיזור נכסים + שווי נקי** — a today-cashflow tri-tile, an asset-mix
   breakdown, and a current-vs-retirement net-worth pair.

Like every Plangram screen, all of this renders from one payload:
`calculations.data` inside `GET /user/getcurrent?includeCalculations=true`
(`today_metrics`, `charts`, `goal_compliance`, `recommendations`, `focal_points`).
For us, every tile maps onto data we already produce in
`data/digested/{cashflow,snapshot,transactions}.json`.

## 2. Goals & non-goals

**Goals**
- Give a single at-a-glance verdict: net worth, goal-funding odds, Plangram score,
  and today's cashflow — without the user navigating anywhere.
- Surface the top recommendations and a "what to do next" nudge (refresh balances).
- Act as a **router**: every card deep-links to its owning feature screen.

**Non-goals (for v1)**
- No new metric or chart math lives here — it strictly **re-reads** outputs of
  PRD 01 (Cashflow) and the snapshot. If a number is wrong, fix it upstream.
- No editing. The onboarding/tour CTA (`יאללה, לסיור!`) and the chat bubble are
  out of scope.
- The week-over-week net-worth delta chip needs snapshot **history** (we store one
  point today — see §6); ship the tile without the chip first.

## 3. Page anatomy

Layout confirmed from `route-overview.yml` (RTL; right rail is the section nav,
shared across all screens). Top-to-bottom in the content column:

```
┌─ היי {name},  (H1)                                                   ┐
│  להלן מבט מהיר לתמונת המצב הפיננסית שלך                                │
│                                                                       │
│  ┌─ �clock  הגיע זמן לעדכן כמה נתונים …        [ לעדכון יתרות ▸ ] ─┐   │
│  └───────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ┌── שווי נקי נוכחי ⓘ ──────────┐  ┌── הסיכוי לעמידה ביעדים ⓘ ──┐    │
│  │  ₪2,632,507                  │  │  100%                      │    │
│  │  [▲ ₪1K] משבוע שעבר          │  │  יש לך סיכוי של 100% …      │    │
│  │                              │  │              🦋 butterfly  │    │
│  └──────────────────────────────┘  └────────────────────────────┘    │
│                                                                       │
│  ┌── הפרופיל שלך מוכן! ─────────┐  ┌── המלצות      [לכל המלצות 6]┐    │
│  │  כל הכבוד! … [יאללה, לסיור!] │  │  ⚡ קיים תזרים לא מנוצל     │    │
│  │                  ✦ complete  │  │  ⚡ בעו"ש יש יתרה גבוהה …    │    │
│  │                              │  │  ⚡ איך להפיק את המיטב …     │    │
│  └──────────────────────────────┘  └────────────────────────────┘    │
│                                                                       │
│  ┌── סימולציית פלנגרם ⓘ ──────────────────────────────────────────┐  │
│  │  ┌ מדד פלנגרם ┐   simulation chart        [⚙ אפשרויות גרף]     │  │
│  │  │   100  מעולה│   legend: הכנסות מעבודה · הכנסה מקצבאות        │  │
│  │  │  verbal verdict paragraph …                                  │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌── מדדים מובילים ⓘ                          [לעמוד התקדמות ▸] ──┐  │
│  │  אחוז חיסכון  │ חתיכה עודפת │ אחוז החזר חוב │ חתיכה חסרה        │  │
│  │   0% לא משהו  │ ₪16.7K לא משהו│  5% מעולה   │  ₪0 מעולה         │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌── התזרים  נכון להיום ──────┐  ┌── פיזור נכסים  נכון להיום ───┐   │
│  │  תזרים  ₪16.7K             │  │  נדלן      84.2%             │   │
│  │  הכנסות ₪30K               │  │  פנסיה      9.8%            │   │
│  │  הוצאות ₪13.3K             │  │  השתלמות    4.4%            │   │
│  │                            │  │  תיקים      1.2%            │   │
│  │                            │  │  עובר ושב   0.3%            │   │
│  └────────────────────────────┘  └─────────────────────────────┘   │
│                                                                       │
│  ┌── שווי נקי ────────────────────────────────────────────────────┐  │
│  │  נוכחי  ₪2.7M        בפרישה  ₪46.6M                            │  │
│  │  לפי כל הנתונים … השווי הנקי שלך בגיל 80 צפוי להיות ₪53.76M     │  │
│  └───────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────┘
```

Every card is `cursor=pointer` and routes to its owner:
net-worth/asset-mix → net-worth view, KPI strip → `/metrics` (התקדמות),
recommendations → `/recommendations`, simulation → cashflow/`תכנון פלוס`,
the nudge → `#profile/update-balances`.

## 4. Block-by-block content

### 4.1 Headline tiles
| Tile (HE) | Value | Sub | Source |
|---|---|---|---|
| **שווי נקי נוכחי** | net worth ₪ | ▲/▼ delta chip "משבוע שעבר", tooltip "סך כל הנכסים שלך פחות התחייבויות" | `netval` today / `focal_points[today]` |
| **הסיכוי לעמידה ביעדים** | goal-funding % (e.g. 100%) | "יש לך סיכוי של N% לממן את התוכנית שלך במלואה." | `goal_compliance` (`missing_piece==0` ⇒ 100%) |

### 4.2 Profile-ready + Recommendations
- **הפרופיל שלך מוכן!** — shown when `profile.completePercent == 100`; otherwise
  this slot becomes a "complete your profile" prompt (see PRD 03). CTA opens the tour.
- **המלצות** — top 3 of `recommendations[]` (schema: `id, code, name, description,
  status, type, nextsteps, articles`); the `6` badge = total active count; each row
  is a `⚡`-prefixed `name`. "לכל המלצות" → `/recommendations`.

### 4.3 סימולציית פלנגרם (hero)
- **מדד פלנגרם** (Plangram score, 0–100) with its `rank` pill (`מעולה` at 100) and
  the long `description`/verdict paragraph from `today_metrics`.
- The simulation chart legend (`הכנסות מעבודה · הכנסה מקצבאות`) is the
  `income_plot_3color` series; the full visual is the projection (PRD 01 §6).
- `⚙ אפשרויות גרף` = series toggle; v1 can omit.

### 4.4 מדדים מובילים (KPI strip)
4 of the 28 `today_metrics`, each `{name, value+units, rank pill}`:

| Card | Units | rank seen | Definition (`description`) |
|---|:--:|---|---|
| **אחוז חיסכון** | % | bad | money to savings ÷ total net income |
| **חתיכה עודפת** | ₪ | bad | free cashflow **not** routed to investing |
| **אחוז החזר חוב** | % | good | loan repayments ÷ total monthly expenses |
| **חתיכה חסרה** | ₪ | good | gap to fund all life-path goals (0 ⇒ מעולה) |

`rank` → pill: `good`→green "מעולה", `bad`→red "לא משהו". "לעמוד התקדמות" → `/metrics`.

### 4.5 Today tri-tiles + asset mix + net worth
- **התזרים / נכון להיום** — `תזרים` / `הכנסות` / `הוצאות` for the current month
  (the same three numbers as Cashflow's today summary).
- **פיזור נכסים / נכון להיום** — asset-class share list (`נדלן / פנסיה / השתלמות /
  תיקים / עובר ושב` with %). This is the `assetpies` pie reduced to a ranked legend.
- **שווי נקי** — `נוכחי` vs `בפרישה` pair + a sentence with the end-of-life (age 80)
  projected figure. From `focal_points` (today, retirement, end).

## 5. Data model (Plangram)

All from `calculations.data` of `GET /user/getcurrent?includeCalculations=true`:

- `today_metrics[]` — `{name, units, rank, higher_is_better, description}` → tiles
  in §4.1, §4.4, §4.5 (net worth, Plangram score, savings%, debt%, surplus/missing
  piece).
- `charts.income_plot_3color`, `charts.assetpies` — simulation legend, asset mix.
- `focal_points[]` — `{date, age, name, asset_val, loan_val, net_val}` → current /
  retirement / age-80 net worth.
- `goal_compliance` — `{passive_coverage, portfolio_goals, missing_piece,
  freedom, inheritance, …}` → goal-funding %.
- `recommendations[]` — recommendation_schema → the preview list.
- `profile.completePercent` — gates the "profile ready" card.

## 6. Mapping to our data

Everything the overview shows is already (or nearly) produced by us:

| Overview tile | Our source |
|---|---|
| שווי נקי נוכחי | `snapshot.json → totals.tracked_net_position` (extend to full assets−liabilities); also `cashflow.json → projection.focal_points[today]` |
| בפרישה / גיל 80 | `cashflow.json → projection.focal_points[retirement,end]` (PRD 01 §7c) |
| התזרים (תזרים/הכנסות/הוצאות) | `cashflow.json → today.{net,income,expense}` |
| מדדים מובילים | `cashflow.json → metrics[]` (savings%, debt%, surplus, missing piece) |
| מדד פלנגרם | `cashflow.json → metrics[]` (our **מדד איזון** — clearly-labeled own score, not theirs) |
| פיזור נכסים | derive class shares from `snapshot.json` (bank_accounts + loans give עו"ש & debt; **assets like נדלן/פנסיה/השתלמות are not yet captured** — see gaps) |
| הסיכוי לעמידה ביעדים | needs goals entity → **not yet captured** |
| המלצות | **not yet produced** — no recommendations engine on our side |
| ▲ משבוע שעבר delta | needs snapshot **history** (we store one point) |
| נדודיע refresh nudge | derive from `snapshot.json → generated_at` staleness |

**What we're missing (and why each tile degrades gracefully):**
- **Asset allocation** — we capture bank balances, cards, loans, but **not**
  pension/השתלמות/portfolio/real-estate assets (Plangram's `assets` profile
  section). Until we ingest them, `פיזור נכסים` can only show עו"ש; net worth is
  understated. (Plangram's own net worth ₪2.6M is mostly נדלן 84% — invisible to us.)
- **Goals** — no goals entity → `הסיכוי לעמידה ביעדים`, `חתיכה חסרה`, `חתיכה עודפת`
  cannot be computed faithfully; show "לא זמין" or hide.
- **Recommendations** — no rules engine yet; v1 can hardcode 1–2 derived nudges
  (e.g. "עו\"ש above target" from snapshot) and label the section accordingly.
- **Week-over-week delta** — add `snapshot-history/` append per digest (already
  flagged in PRD 01 §7b) to unlock the chip.

## 7. Implementation plan (suggested)

**Phase 1 — Router dashboard over existing outputs**
1. Add `data/overview.py` (or a view template) that reads `cashflow.json` +
   `snapshot.json` and assembles an `overview.json`:
   `{ headline:{net_worth, goal_odds?}, today:{net,income,expense},
   top_metrics:[…4], net_worth:{current,retirement,end},
   asset_mix:[…], recommendations:[…], stale:bool }`.
2. Reuse PRD 01's `metrics[]` verdict logic verbatim for the KPI strip and score.
3. Render the 7 blocks; each card links to its owner screen.
4. `stale` = `now − snapshot.generated_at > N days` → show the refresh nudge.

**Phase 2 — Fill the gaps**
5. Ingest pension/השתלמות/portfolio/real-estate assets → real `פיזור נכסים` and a
   correct net worth (depends on new scrapers / manual asset entry).
6. Add the goals entity → goal-odds tile, חתיכה חסרה/עודפת.
7. Append `snapshot-history/` per digest → week-over-week delta chip.
8. A small recommendations rules engine → `המלצות` preview.

## 8. Open questions

- **Goal-funding %** — Plangram derives it from a full goals + projection model.
  Do we model goals at all in v1, or hide the tile until assets/goals are ingested?
- **Asset capture** — pension/keren/portfolio/real-estate are the bulk of net worth
  but unscraped. Manual entry screen, or new scrapers? (Blocks both פיזור נכסים and
  an accurate שווי נקי.)
- **Plangram score parity** — reuse our own `מדד איזון` here (as in PRD 01) and label
  it ours, to avoid implying parity with their proprietary 0–100.
- **Recommendations** — minimal hardcoded nudges for v1, or defer the whole card?
- **Delta window** — "משבוע שעבר" implies weekly snapshots; is our digest cadence
  frequent enough, and do we want weekly or per-digest deltas?
