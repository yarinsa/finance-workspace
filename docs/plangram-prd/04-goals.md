# PRD 04 — Goals (יעדים)

> Reverse-engineered from Plangram's `/goals` screen. Hebrew (RTL), ILS (₪).
> Evidence: `captures/route-goals.yml`, `captures/route-goals.png`,
> `captures/cashflow-schema.json` (`goals` profile section, `goal_compliance_keys`,
> goal `today_metrics`), `captures/scenario-list.json`
> (`globalEmergencyFund` / `globalInheritanceFund`).

## 1. Summary

The Goals screen answers *"am I on track to fund the things I want — the trips, the
emergency cushion, retirement, the legacy I want to leave?"* It is a **read-only
scoreboard** of goal-attainment, split into two halves:

1. **יעדים אישיים (personal goals)** — the discrete, user-entered savings targets
   ("swap phone — ₪3,000 by 23 Nov 2025"). Each renders as a card with a per-goal
   *probability of attainment* and a progress bar.
2. **יעדים כללים (general goals)** — four headline metric cards that score the
   *whole plan* against its long-horizon objectives: overall goal compliance,
   emergency-fund coverage, retirement-target coverage, and the inheritance amount.

Like every Plangram screen, it is a render of the precomputed model inside
`GET /user/getcurrent?includeCalculations=true`. The personal goals come from the
profile `goals` section (`type: "goals"`); the four general cards come from
`goal_compliance` and the goal-scoped `today_metrics`. The emergency-fund and
inheritance **targets** themselves are per-scenario constants
(`globalEmergencyFund`, `globalInheritanceFund`) edited via "הגדרות תחזית".

For us this is the first screen that needs an entity **we do not scrape** — goals
are user intent, not bank data. See §6 for the gap.

## 2. Goals & non-goals

**Goals**
- List the user's personal savings goals, each with target amount, target date, a
  progress bar, and a *probability/percent of attainment*.
- Show four plan-level attainment scores: goal compliance, emergency-fund coverage,
  retirement-target coverage, and projected inheritance amount.
- Each general card links to a "לפרטים" (details) drill-down.

**Non-goals (for v1)**
- **Authoring** goals (add/edit/delete). Plangram edits these on `/my-plan/goals`
  (a separate profile-editor route); this `/goals` screen only *reads* them. A
  minimal author form is needed for us only because we have no source for the data
  (§6) — but it is a thin CRUD, not this PRD's analytics.
- Editing the emergency-fund / inheritance targets (those live behind
  "הגדרות תחזית" / the scenario object — separate concern).
- The projection engine that produces the compliance percentages — it is shared
  with Cashflow PRD 01 §6/§7c. This PRD *consumes* its output.

## 3. Page anatomy

Layout confirmed from `route-goals.yml` + `route-goals.png` (RTL; right rail is the
shared section nav). Top-to-bottom in the content column:

```
┌─ יעדים  (H1)                                  [▶ הסבר על עמוד זה] ┐
│   (help link → /article/75/דף-יעדים)                              │
│                                                                   │
│  יעדים אישיים  (H2)                                                │
│  ┌── goal card ───────────────────────────────────────────────┐  │
│  │  [▶]                                       החלפת טלפון (name) │  │
│  │                              100% סיכוי לעמידה ביעד          │  │
│  │  ███████████████████████████  (progress bar)                │  │
│  │  יעד ₪3,000            תאריך יעד 23 בנובמבר 2025             │  │
│  └─────────────────────────────────────────────────────────────┘  │
│  …one card per personal goal…                                     │
│                                                                   │
│  יעדים כללים  (H2)                                                 │
│  ┌──────────┬──────────┬──────────────┬──────────────────────┐    │
│  │ סכום      │ אחוז עמידה │ אחוז עמידה   │ אחוז עמידה ביעדים     │   │
│  │ להורשה    │ ביעד פרישה │ בקרן חירום   │                       │   │
│  │ ₪53.8M    │ 100%      │ 100%         │ 100%       [לפרטים]   │   │
│  │ [לפרטים]  │ [לפרטים]   │ [לפרטים]     │                       │   │
│  └──────────┴──────────┴──────────────┴──────────────────────┘    │
└───────────────────────────────────────────────────────────────────┘
```

Notes from the capture:
- The personal-goal card carries a **play/▶ glyph** (image labelled with the goal
  name) — the same "focal point" affordance used on the timeline; clicking it likely
  centers that goal on the life-path chart.
- The four general cards each have an **icon** (boat = goals, beach-umbrella =
  retirement, umbrella = emergency fund, flag = goal-compliance in the screenshot)
  and a **"לפרטים"** link to a per-metric details view.
- `סכום להורשה` (inheritance) renders as **₪** (e.g. `₪53.8M`); the other three
  render as **%**. The general row is RTL, so reading right→left the order is:
  אחוז עמידה ביעדים · אחוז עמידה בקרן חירום · אחוז עמידה ביעד פרישה · סכום להורשה.

## 4. Personal goals (יעדים אישיים)

### 4a. The goal entity

From `cashflow-schema.json → profile_sections[name="goals"]`, the goals section
holds three entity types:

| Entity `type` | UI name | itemName | Add/Del | Purpose |
|---|---|---|:--:|---|
| `goals` | יעדים | יעד | both | discrete personal savings goal (the cards) |
| `GlobalEmergencyFund` | קרן חירום | קרן חירום | both | the single emergency-fund **target** |
| `GlobalInheritanceFund` | הורשה | הורשה | add only (no delete) | the single inheritance **target** |

The `goals` item fields (schema-exact):

```
id, description, amount, type, startDate, endDate,
interval, repetitions, rise, assosiatedAssetType, assosiatedAssetId
```

Read of each field for the card render:
- **`description`** → card title ("החלפת טלפון").
- **`amount`** → `יעד ₪{amount}` (the target sum).
- **`endDate`** → `תאריך יעד {date}` (target date, e.g. "23 בנובמבר 2025").
- **`startDate`** → when accrual toward the goal begins (drives the time the plan has
  to reach it; feeds the probability).
- **`interval` / `repetitions` / `rise`** → recurring goals (e.g. an annual trip):
  interval = period, repetitions = how many times, rise = per-occurrence growth.
  A one-time goal has `repetitions = 1`.
- **`assosiatedAssetType` / `assosiatedAssetId`** → optionally fund this goal *from*
  a named asset (e.g. a specific portfolio) rather than from generic free cashflow.
- **`type`** (the `[sic]` spelling `assosiated*` is Plangram's own) — goal sub-kind.

> Note the misspellings (`assosiated`, not `associated`) are **in the source schema**
> and must be matched verbatim if we ever interop with their payload; our own model
> should use correct spelling internally.

### 4b. Per-goal metrics rendered on the card

- **Progress bar** — fraction funded so far: accrued-toward-goal ÷ `amount`. The
  capture shows a full (100%) bar.
- **`{p}% סיכוי לעמידה ביעד`** — *probability of attainment*, not raw progress. This
  is a projection output: given the plan's free cashflow, start/end dates, and any
  associated asset, what is the modelled chance the goal is funded by `endDate`. In
  the capture it reads `100%`. (Plangram phrases it as a likelihood — "סיכוי" — so it
  can read 100% even when the bar is short, if the runway is long enough.)

## 5. General goals (יעדים כללים) — the four metric cards

These four cards are **plan-level** scores, sourced from `today_metrics` (the goal
subset) and `goal_compliance`. From `cashflow-schema.json → today_metrics`, the
goal-scoped metrics (all `show_in_progress_tab: true`):

| Card (HE) | metric `name` | units | `rank` | Meaning |
|---|---|:--:|:--:|---|
| **אחוז עמידה ביעדים** | אחוז עמידה ביעדים | % | null | overall goal compliance — share of all life-path goals the plan funds |
| **אחוז עמידה בקרן חירום** | אחוז עמידה בקרן חירום | % | null | emergency-fund coverage — funded ÷ `globalEmergencyFund` |
| **אחוז עמידה ביעד פרישה** | אחוז עמידה ביעד פרישה | % | null | retirement-target coverage — projected net worth at retirement vs target |
| **סכום להורשה** | סכום להורשה | ₪ | null | projected estate left at end-of-life (the inheritance the plan produces) |

Supporting / related metrics in the same catalog (not on the cards but feed them):
`חתיכה חסרה` ("missing piece", ₪ — gap to fully fund **all** goals across the life
path; `rank: good`, lower is better), `חוסר בקרן חירום` (₪ shortfall in the
emergency fund), `אחוז עמידה ביעדים` is the headline; `חתיכה עודפת` (the free
cashflow *not* routed to investing — the inverse signal).

### 5a. goal_compliance (the computation behind the cards)

`cashflow-schema.json → goal_compliance_keys`:

```
passive_coverage, portfolio_goals, improve_by, missing_piece,
bottom_line, freedom, base_problem_data, inheritance
```

Mapping keys → cards (best inference from names + the prompt's relevant-keys list):

| `goal_compliance` key | Feeds | Reading |
|---|---|---|
| `portfolio_goals` | אחוז עמידה ביעדים | per-goal attainment rolled up into the overall % |
| `passive_coverage` | אחוז עמידה ביעד פרישה / freedom | does projected passive income/net worth cover the retirement need |
| `freedom` | אחוז עמידה ביעד פרישה | financial-independence / retirement readiness |
| `inheritance` | סכום להורשה | projected estate at end-of-life vs `globalInheritanceFund` |
| `missing_piece` | חתיכה חסרה (KPI) | ₪ gap to fund **all** goals; 0 ⇒ 100% compliance |
| `improve_by` | "לפרטים" drill-down | prescriptive: how much more monthly flow closes the gap |
| `bottom_line` / `base_problem_data` | details / diagnostics | summary verdict + the raw inputs the score was computed from |

The **emergency-fund card** (`אחוז עמידה בקרן חירום`) is computed against the
per-scenario target, not `goal_compliance` — see §5b.

### 5b. Emergency-fund & inheritance targets (scenario constants)

From `captures/scenario-list.json` / `scenario_schema`, each scenario carries:

```
globalEmergencyFund     // target emergency-fund size (₪)
globalInheritanceFund   // target inheritance to leave (₪)
```

These are the **denominators** for two of the cards:

- **אחוז עמידה בקרן חירום** = `min(1, liquid_buffer / globalEmergencyFund)`, where
  `liquid_buffer` is the projected עו"ש / liquid reserve. `חוסר בקרן חירום` =
  `max(0, globalEmergencyFund − liquid_buffer)`.
- **סכום להורשה** = the projected estate at end-of-life; the `GlobalInheritanceFund`
  entity is the **target** the user wants to leave, and the card shows the **modelled
  result** (which may exceed the target — `₪53.8M` in the capture). The "comply
  with inheritance" verdict compares result vs `globalInheritanceFund`.

These targets are **per-scenario** and edited through "הגדרות תחזית" (the scenario
settings), mirroring the `GlobalEmergencyFund` / `GlobalInheritanceFund` profile
entities (each just `{id, amount}`). There is exactly **one** of each per scenario
(`disableAdd` semantics: emergency fund add/del enabled but conceptually singular;
inheritance is add-only, no delete).

## 6. Mapping to our data (and the gap)

### The gap — goals are user input, not scraped ⚠

Our pipeline (`data/digested/{snapshot,transactions}.json`) is built **entirely from
bank/card scraping**. It has **no goals entity** and cannot derive one — a goal
("swap my phone for ₪3,000 by November") is *intent*, invisible to any bank API.
This is the central gap for this screen:

- **Personal goals (`goals`)** — must be **user-entered**. There is no scraped source.
  We need a small persisted store (e.g. `data/goals/goals.json`) and a thin editor.
- **`globalEmergencyFund` / `globalInheritanceFund`** — also user-entered targets;
  store as config/scenario constants (we already hardcode a synthetic default
  scenario per Cashflow PRD 01 §6).

Everything else (the *coverage* of those goals) **is** computable from our data once
the targets exist.

### What we already have

| Card / value | Our source | Notes |
|---|---|---|
| אחוז עמידה בקרן חירום | `snapshot.totals.bank_balances_sum` ÷ user `emergency_fund` target | liquid buffer = sum of bank balances; clean, available today |
| חוסר בקרן חירום | `max(0, target − bank_balances_sum)` | trivial once target set |
| אחוז עמידה ביעד פרישה / סכום להורשה | `data/projection.py` net-worth-at-retirement / end-of-life (PRD 01 §7c) | already built; compare to retirement need / inheritance target |
| אחוז עמידה ביעדים / חתיכה חסרה | projection net worth vs the **user-entered goals** | needs the goals store first (gap above) |
| per-goal `{p}% סיכוי` + progress | goals store + projection free-cashflow runway | progress = accrued ÷ amount; probability = projection vs `endDate` |

### Suggested data shape (new, user-owned)

```jsonc
// data/goals/goals.json  (user-entered; NOT scraped)
{
  "emergency_fund_target": 0,      // ₪  (globalEmergencyFund)
  "inheritance_target": 0,         // ₪  (globalInheritanceFund)
  "goals": [
    {
      "id": "…",
      "description": "החלפת טלפון",
      "amount": 3000,              // ₪ target
      "start_date": "2025-01-01",
      "end_date": "2025-11-23",
      "interval": null,            // recurring period or null for one-time
      "repetitions": 1,
      "rise": 0,
      "from_asset_id": null        // optional funding source (assosiatedAssetId)
    }
  ]
}
```

`data/goals.py` would then read this store + `snapshot.json` + the projection output
and emit a `goals.json` digest mirroring the four general cards + per-goal cards.

## 7. Implementation plan (suggested)

**Phase 1 — Targets + emergency fund (data we have)**
1. Add the user-owned `data/goals/goals.json` store (start with just the two
   `*_target` fields). Provide a minimal CLI/edit path to set them.
2. Compute **אחוז עמידה בקרן חירום** + **חוסר בקרן חירום** from
   `snapshot.totals.bank_balances_sum` vs `emergency_fund_target`. This is fully
   backed today and is the cleanest of the four cards.

**Phase 2 — Retirement & inheritance (reuse projection)**
3. Wire `data/projection.py` outputs (net worth at retirement, end-of-life estate)
   into **אחוז עמידה ביעד פרישה** and **סכום להורשה** vs the user targets.

**Phase 3 — Personal goals + overall compliance**
4. Extend the store with the `goals[]` array + a thin author form (add/edit/delete).
5. Per-goal card: progress bar (accrued ÷ amount) + probability (projection runway
   to `end_date`).
6. Roll personal goals into **אחוז עמידה ביעדים** / **חתיכה חסרה** (gap to fund all
   goals), reproducing `goal_compliance.{portfolio_goals, missing_piece, improve_by}`
   with our own transparent formula.

> Phase 1 ships value immediately and only needs two user-entered numbers. Personal
> goals are deferred because they require the full author + projection loop.

## 8. Open questions

- **Goal authoring scope** — do we build the full `/my-plan/goals` editor (recurring
  goals, per-asset funding) or ship a flat list of `{name, amount, date}` for v1?
- **Emergency-fund definition** — is the buffer "sum of all bank balances", or only
  designated liquid/savings accounts? Plangram models a `globalEmergencyFund` target
  against a projected liquid `buffer_plot`; we'd need to pick which accounts count.
- **Retirement need** — `אחוז עמידה ביעד פרישה` needs a *target* net worth at
  retirement. Plangram derives it from desired retirement spend × longevity. Do we
  ask the user for a target number, or compute one from projected expenses?
- **Probability vs progress** — Plangram's "% סיכוי לעמידה ביעד" is a modelled
  likelihood, distinct from the progress bar. Do we replicate a probabilistic model,
  or ship a simpler deterministic "on track / not on track" for v1?
- **`current_age` placeholder** — the projection's `current_age` is a hardcoded
  placeholder (PRD 01 §7c, ⚠ = 35, not scraped). Retirement/inheritance cards inherit
  that inaccuracy until we capture birth date (`PersonalInformation.birthDate`).
