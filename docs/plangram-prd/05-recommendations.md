# PRD 05 — Recommendations (המלצות)

> Reverse-engineered from Plangram's `/recommendations` screen. Hebrew (RTL), ILS (₪).
> Evidence: `captures/route-recommendations.yml`, `captures/route-recommendations.png`,
> `captures/cashflow-schema.json` (`recommendation_schema`,
> `looking_for_smart_advices.advices`).

## 1. Summary

The Recommendations screen is Plangram's **advice / nudge engine**: a triaged inbox
of personalized, prescriptive suggestions ("you have unused cashflow", "your checking
balance is above target", "keep filling your emergency fund"). Each item is a *card*
the user can open, act on (a list of `nextsteps`), read more about (`articles`), mark
**done**, or **hide**.

It is the action layer that sits on top of the analytics screens (Cashflow, Goals):
those screens *diagnose*; this screen *prescribes*. The nav badge shows the count of
active recommendations (`6` in the capture).

Like every Plangram screen it renders from the precomputed model in
`GET /user/getcurrent?includeCalculations=true` — specifically the
`recommendation_schema` items plus a `looking_for_smart_advices.advices` block. The
recommendations are **generated server-side** by rule evaluation over the same
metrics the other screens display, so each one is effectively a `(condition →
message + steps + articles)` rule that fired against this user's numbers.

For us this is a **rules engine over our own digested data** — no scraping needed,
and (unlike Goals) no missing entity, because every condition is computable from
`snapshot.json` / `transactions.json` / the projection. See §6.

## 2. Goals & non-goals

**Goals**
- Present active recommendations triaged into **urgent** vs **regular** suggestions.
- Each card opens to a description, a `nextsteps` action list, and related `articles`.
- Let the user **complete** (→ הושלם) or **hide** (→ הוסתר) a recommendation, and
  surface those in collapsed sections with counts.
- Drive the nav badge with the count of active (non-completed, non-hidden) items.

**Non-goals (for v1)**
- Authoring/curating the rule catalog from a UI — rules are code/config.
- Executing the action for the user (e.g. actually moving money). `nextsteps` are
  instructions/links, not automated transactions.
- The in-app chat / AI advisor (the floating "צ'אט" button, separate iframe widget).

## 3. Page anatomy

Layout confirmed from `route-recommendations.yml` + `route-recommendations.png`
(RTL; right rail is the shared section nav). Top-to-bottom in the content column:

```
┌─ המלצות  (H1)                                 [▶ הסבר על עמוד זה] ┐
│   (help link → /article/60/דף-המלצות)                             │
│                                                                   │
│  הצעות דחופות  (H2, urgent — collapsible)                          │
│  ┌─ ◆  קיים תזרים לא מנוצל                                    ‹ ┐  │  ← red/peach
│  └────────────────────────────────────────────────────────────┘  │     cards
│  ┌─ ◆  בחשבון עו"ש יש יתרה גבוהה מהיעד                        ‹ ┐  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  הצעות  (H2, suggestions — collapsible)                            │
│  ┌─ ◆  איך להפיק את המיטב מפלנגרם?                            ‹ ┐  │  ← blue/lilac
│  └────────────────────────────────────────────────────────────┘  │     cards
│  ┌─ ◆  המשך למלא את קרן החירום שלך!                          ‹ ┐  │
│  ┌─ ◆  מומלץ לבחון מעבר לניהול עצמי (IRA) של חסכונות פנסיוניים ‹ ┐ │
│  ┌─ ◆  הגיע זמן לחלומות חדשים                                 ‹ ┐  │
│                                                                   │
│  הושלם (0)   ▾   (completed — collapsed, count)                    │
│  הוסתר (0)   ▾   (hidden — collapsed, count)                       │
└───────────────────────────────────────────────────────────────────┘
```

Notes from the capture:
- Two visual tiers: **urgent** cards are peach/red, **regular** suggestions are
  lilac/blue — i.e. `status`/`type` drives card color.
- Each card has a **‹ chevron** (RTL "expand") to open the detail (description +
  `nextsteps` + `articles`).
- **הושלם** and **הוסתר** are **collapsible headers with counts** (`(0)` each here)
  and a ▾ arrow — empty by default, expand to reveal resolved items.
- The active count across הצעות דחופות (2) + הצעות (4) = **6**, matching the nav
  badge "המלצות 6".
- "איך להפיק את המיטב מפלנגרם?" is an **onboarding/evergreen** suggestion, not a
  data-driven one — the catalog includes static educational nudges too.

## 4. Recommendation entity

From `cashflow-schema.json → recommendation_schema`:

```
id, code, name, description, status, showComplete, type, nextsteps, articles
```

| Field | Render / role |
|---|---|
| **`id`** | stable instance id (for complete/hide actions, dedupe) |
| **`code`** | the **rule code** — identifies *which* rule fired (e.g. an "unused cashflow" rule). Stable across users; the join key to the catalog |
| **`name`** | card **title** ("קיים תזרים לא מנוצל") |
| **`description`** | body text shown when the card is expanded |
| **`status`** | lifecycle: active / completed / hidden → routes the card to its section |
| **`showComplete`** | whether the card offers a **"mark done"** affordance (some, e.g. evergreen tips, can only be hidden, not completed) |
| **`type`** | severity / bucket → **urgent (דחוף)** vs **suggestion (הצעה)**; drives the section + card color |
| **`nextsteps`** | ordered **action list** rendered inside the expanded card (what to do about it) |
| **`articles`** | related help **articles** (links into `/article/{id}/…`, same pattern as the page-help links) |

### 4a. Status → section mapping

| Section (HE) | H-level | `status` | Card style |
|---|:--:|---|---|
| **הצעות דחופות** (urgent) | H2 | active **and** `type` = urgent | peach / red |
| **הצעות** (suggestions) | H2 | active **and** `type` = suggestion | lilac / blue |
| **הושלם** (completed) | H2 (collapsible, count) | `status` = completed | collapsed list |
| **הוסתר** (hidden) | H2 (collapsible, count) | `status` = hidden | collapsed list |

Active = not completed and not hidden. The nav badge = count of active items.

## 5. The advice generator (`looking_for_smart_advices.advices`)

`cashflow-schema.json` exposes a `looking_for_smart_advices.advices` block — the
**source list of candidate advices** the engine evaluates. Read of the model:

- The engine evaluates a **catalog of rules**, each keyed by `code`, against the
  user's current metrics (`today_metrics`, `goal_compliance`, balances).
- A rule that **fires** materializes into a `recommendation_schema` item with a
  filled `name` / `description` / `nextsteps` / `articles` and a `type` (urgency).
- `looking_for_smart_advices.advices` is the **candidate/working set** ("advices the
  system is looking for / considering") — i.e. the rule evaluations, before the
  user's complete/hide state filters them into the visible sections.

### Observed rules (from the captured cards → inferred conditions)

| Card `name` (HE) | Inferred condition | Source metric | Bucket |
|---|---|---|:--:|
| קיים תזרים לא מנוצל ("unused cashflow") | free cashflow not routed to investing > 0 | `today_metrics: חתיכה עודפת` / `יחס השקעות` low | urgent |
| בחשבון עו"ש יש יתרה גבוהה מהיעד ("checking above target") | bank buffer > target buffer | `snapshot.bank_balances` vs `balanceGoal` / emergency target | urgent |
| המשך למלא את קרן החירום שלך! ("keep filling emergency fund") | emergency-fund coverage < 100% | `אחוז עמידה בקרן חירום` < 100 | suggestion |
| מומלץ לבחון מעבר לניהול עצמי (IRA) ("consider IRA self-management") | has pension/keren assets w/ high fees | `Pension`/`Keren` fee fields | suggestion |
| הגיע זמן לחלומות חדשים ("time for new dreams") | all goals funded / no active goals | `אחוז עמידה ביעדים` = 100% & free surplus | suggestion |
| איך להפיק את המיטב מפלנגרם? ("get the most from Plangram") | evergreen onboarding (always present until hidden) | none — static | suggestion |

> These are *inferred* from card titles + the metric catalog; the exact thresholds
> are proprietary. We replicate the **intent** with our own transparent thresholds.

## 6. Mapping to our data

Unlike Goals, this screen needs **no new scraped entity** — every condition above is
computable from data we already digest, plus the goals targets from PRD 04:

| Rule | Our source |
|---|---|
| unused cashflow | `transactions.summary` (income − spend, surplus) + projection investable surplus |
| checking above target | `snapshot.totals.bank_balances_sum` vs emergency/buffer target (PRD 04 store) |
| keep filling emergency fund | `bank_balances_sum` vs `emergency_fund_target` (PRD 04) |
| IRA / high-fee pension | ⚠ **gap** — we don't scrape pension/keren fee data; needs the assets entity (not yet captured). Skip in v1 |
| time for new dreams | goals store (PRD 04) — all goals funded |
| get the most from Plangram | static evergreen — N/A for us (or repurpose as our own onboarding tip) |

### Suggested data shape

A **rule catalog** (code → predicate + copy) evaluated against the digest, plus a
small **user state** store for complete/hide:

```jsonc
// data/recommendations/catalog.py  (code, predicate, copy)
//   each rule: { code, type: "urgent"|"suggestion", show_complete,
//                predicate(snapshot, tx_summary, goals, projection) -> bool,
//                name, description, next_steps: [...], articles: [...] }

// data/recommendations/state.json  (user-owned)
{ "completed": ["<code>", ...], "hidden": ["<code>", ...] }

// data/digested/recommendations.json  (emitted)
{ "active":   [ {id, code, name, description, type, show_complete,
                 next_steps, articles} ],
  "completed":[ ... ], "hidden": [ ... ],
  "badge_count": 0 }
```

`data/recommendations.py` runs the catalog over the digest, drops codes present in
`state.json`'s completed/hidden lists, and emits the three buckets + the badge count.
Idempotent and re-runnable after every digest, matching the repo convention.

## 7. Implementation plan (suggested)

**Phase 1 — Engine + the cashflow/emergency rules**
1. Define the rule catalog (`code`, predicate, `type`, copy, `next_steps`,
   `articles`) starting with the rules backed by data we have today: *unused
   cashflow*, *checking above target*, *keep filling emergency fund*.
2. Add `data/recommendations.py`: evaluate catalog over
   `snapshot.json` + `transactions.json` (+ PRD 04 goals targets) → emit active list
   + `badge_count`. Wire into `data/digest.py` after the snapshot.

**Phase 2 — User state (complete / hide)**
3. Add `state.json` (completed/hidden code lists) + actions to mark done / hide.
4. Render the four sections (urgent / suggestion / completed / hidden) with counts;
   collapsed completed & hidden.

**Phase 3 — Goal- and asset-derived rules**
5. Add goal-driven rules once PRD 04's goals store exists ("time for new dreams").
6. Defer asset/pension-fee rules (e.g. IRA) until we capture an assets entity (gap).

## 8. Open questions

- **Thresholds** — Plangram's fire conditions are proprietary. What are *our*
  thresholds (e.g. "checking above target" = balance > N× monthly expense, or >
  emergency target)? Needs product decision per rule.
- **Urgency classification** — is `type` purely per-rule, or does the same rule
  escalate urgent vs suggestion based on magnitude? The capture shows fixed buckets;
  confirm before modeling severity dynamically.
- **`nextsteps` / `articles` content** — Plangram links to its own article CMS
  (`/article/{id}/…`). We have no CMS; do we write our own short action text inline,
  or link out to external resources?
- **Persistence of complete/hide** — single-user local `state.json` is fine here;
  confirm we don't need per-scenario recommendation state.
- **Asset/pension data gap** — the IRA/high-fee rule needs pension `fee` fields we
  don't scrape. Acceptable to ship without it in v1?
- **Dedup vs re-fire** — if a user completes a recommendation and the condition
  later re-triggers, does it re-appear or stay completed? Plangram's `id` vs `code`
  split suggests instances can re-fire; define our policy.
