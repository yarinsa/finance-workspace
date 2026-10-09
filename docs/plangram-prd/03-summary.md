# PRD 03 — Plan Summary (סיכום התוכנית שלי)

> Reverse-engineered from Plangram's `/summary` screen. Hebrew (RTL), ILS (₪).
> Evidence: `captures/route-summary.yml`, `captures/route-summary.png`,
> `captures/cashflow-schema.json`.

## 1. Summary

`/summary` is the **plan-inputs cockpit** — the first item under the `התוכנית שלי`
nav group. Where Overview (PRD 02) and Cashflow (PRD 01) answer *"how am I doing?"*
from computed metrics, Summary answers *"is my plan fully described, and what did I
tell the model?"* It is a **profile-completeness + plan-inputs map**, the hub from
which the user drills into each editable section.

Top-to-bottom it has three regions:

1. **המסע הפיננסי שלי** — a single life-horizon net-worth chart ("my financial
   journey"): one curve from today → age 80, with a `הפרישה שלך` marker at
   retirement and `▶`-play life-event markers along the early years. An
   `+ הוספת אירוע` button adds life events.
2. **השלמת N מתוך M מחלקות** (here 5 of 5) — a grid of **completeness cards**, one
   per profile section (הכנסות / הוצאות / יעדים / נכסים / התחייבויות), each badged
   `הושלם` when complete.
3. **פרטי התוכנית** — plan-meta cards: `גיל פרישה` (you + partner) and `הפרופיל שלי`
   (name + birth date).

As with every screen, the data comes from the single
`GET /user/getcurrent?includeCalculations=true` payload — specifically
`profile_sections[]` (the section catalog + completeness), `focal_points[]` /
`timeline[]` (the journey curve), and the `PersonalInformation` entity
(retirement age, birth date). It is **read + route**: the cards link out to the
editable section screens (`/my-plan/{income,expense,goals,assets,debt}`).

## 2. Goals & non-goals

**Goals**
- Show whether the plan is fully specified — completeness per section, with a
  headline "N of M sections done" and per-card `הושלם` badges.
- Give the lifetime net-worth narrative in one curve, with retirement and
  life-events marked, as the emotional anchor of "the plan".
- Be the routing hub into each editable plan section, plus surface plan-meta
  (retirement ages, identity).

**Non-goals (for v1)**
- The section editors themselves (income/expense/goals/assets/debt CRUD) are
  separate screens/PRDs; Summary only links to them and reports their status.
- Life-event authoring (`+ הוספת אירוע`) — capture the affordance, defer the editor.
- No KPI/verdict math here (that's Cashflow/Overview). Summary is structural.

## 3. Page anatomy

Layout confirmed from `route-summary.yml` (RTL; shared right-rail nav).
Top-to-bottom in the content column:

```
┌─ סיכום התוכנית שלי  (H1)                                              ┐
│                                                                       │
│  region "המסע הפיננסי שלי" ───────────────────────────────────────┐  │
│  │  המסע הפיננסי שלי  (H2)                       [ + הוספת אירוע ] │  │
│  │                                                  הפרישה שלך ┊   │  │
│  │   ₪60M ┤                                              ╱──────  │  │
│  │   ₪45M ┤                                         ╱╱◉╱          │  │
│  │   ₪30M ┤                                    ╱╱╱               │  │
│  │   ₪15M ┤   ▶  ▶  ▶  ▶ ___________╱╱╱                          │  │
│  │      0 ┼───┬────┬────┬────┬────┬────┬────┬────┬────┬───        │  │
│  │       היום ג35  ג41  ג48  ג54  ג61  ג67  ג74  ג80              │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  region "התקדמות התוכנית" ─────────────────────────────────────────┐ │
│  │  ✦  השלמת 5 מתוך 5 מחלקות  (H2)                                  │ │
│  │     חשוב להשלים את כל המחלקות לקבלת תמונה מלאה                    │ │
│  │  ┌ הושלם✓ הוצאות ┐ ┌ הושלם✓ הכנסות ┐ ┌  השלמת 5 מתוך 5 מחלקות ┐ │ │
│  │  │ נהל את ה…      │ │ עקוב אחר כל…   │ │ חשוב להשלים… (overall) │ │ │
│  │  └───────────────┘ └───────────────┘ └────────────────────────┘ │ │
│  │  ┌ הושלם✓ התחייבויות┐ ┌ הושלם✓ נכסים ┐ ┌ הושלם✓ יעדים ┐         │ │
│  │  │ עדכן פרטים…       │ │ רשום ועקוב…  │ │ נהל יעדים…    │         │ │
│  │  └──────────────────┘ └──────────────┘ └──────────────┘         │ │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  region "פרטי התוכנית" ────────────────────────────────────────────┐ │
│  │  ┌ גיל פרישה ┐                ┌ הפרופיל שלי ┐                    │ │
│  │  │ אתה 67 | בת הזוג 65        │ {name} | תאריך לידה dd/mm/yyyy   │ │
│  │  └───────────┘                └─────────────┘                    │ │
│  └───────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────┘
```

Each completeness card is a `button` linking to its editor; the meta cards
(`גיל פרישה`, `הפרופיל שלי`) are buttons that open the personal-information editor.

## 4. Block-by-block content

### 4.1 המסע הפיננסי שלי (the journey chart)
- One net-worth curve, today → age 80, axis ticks `היום / גיל 35 / 41 / 48 / 54 /
  61 / 67 / 74 / 80` and y-grid `0 / ₪15M / ₪30M / ₪45M / ₪60M`.
- A dashed `הפרישה שלך` marker at the retirement-age tick with a node on the curve.
- `▶` play-glyph markers in the early years = **life events** on the timeline.
- `+ הוספת אירוע` = add a life event (one-time income/expense/goal at a date).
- Same series as Overview's net-worth / PRD 01's `netval_plot`, rendered as the
  full lifetime curve from `focal_points[]` + `timeline[]`.

### 4.2 Completeness cards (השלמת N מתוך M מחלקות)
One card per **profile section**, plus an overall-progress card. From
`profile_sections[]` and `profile.completePercent`:

| Card (HE) | Section `name` | Subtitle (`subtitle`) | Routes to |
|---|---|---|---|
| **הכנסות** | income | עקוב אחר כל מקורות ההכנסה החודשיים שלך | `/my-plan/income` |
| **הוצאות** | expense | נהל את ההוצאות השוטפות שלך | `/my-plan/expense` |
| **יעדים** | goals | נהל יעדים פיננסיים, קרן חירום והורשה | `/my-plan/goals` |
| **נכסים** | assets | רשום ועקוב אחר הנכסים וההשקעות שברשותך | `/my-plan/assets` |
| **התחייבויות** | debt | עדכן פרטים אישיים והוסף יעדים | `/my-plan/debt` |
| **השלמת 5 מתוך 5** | (overall) | חשוב להשלים את כל המחלקות לקבלת תמונה מלאה | — |

Badge: `הושלם` (green ✓) when the section is complete; otherwise a "needs input"
state (CTA to fill it). The headline count = completed sections / total.

> Note the captured subtitle for **התחייבויות** ("עדכן פרטים אישיים והוסף יעדים")
> looks like a copy/label reuse in Plangram's data; treat the section *intent* as
> debts/liabilities (matches `/my-plan/debt` + the `Debt` entity).

### 4.3 פרטי התוכנית (plan meta)
| Card | Content | Source |
|---|---|---|
| **גיל פרישה** | "אתה 67 | בת הזוג 65" | scenario `retirementAge` / `partnerRetirementAge`; `PersonalInformation.retirementAge` |
| **הפרופיל שלי** | "{name} | תאריך לידה dd/mm/yyyy" | `PersonalInformation.{firstName,lastName,birthDate}` |

## 5. Data model (Plangram)

From `calculations.data` / profile of `GET /user/getcurrent?includeCalculations=true`:

- **`profile_sections[]`** — the section catalog driving the completeness grid.
  Each: `{name, title, subtitle, entities:[{type, name, itemName, item_fields…}]}`.
  The five plan sections: `income`, `expense`, `goals`, `assets`, `debt`
  (+ `personal-information`). Their entity types are the editable plan inputs:
  - income: `income`, `income-onetime`, `income-allowance`, `income-property`
  - expense: `Expense` (שכירות, הוצאות צריכה)
  - goals: `goals`, `GlobalEmergencyFund`, `GlobalInheritanceFund`
  - assets: `BankAccount`, `Pension`, `Keren`, `Portfolio`, `RealEstate`, `otherasset`
  - debt: `Debt`
  - personal-information: `PersonalInformation`, `children`, `AccountDetails`
- **`profile.completePercent`** (0–100) — overall completeness; per-section
  complete = section has ≥1 entity / required fields filled.
- **`focal_points[]`** `{date, age, name, asset_val, loan_val, net_val}` +
  **`timeline[]`** `{value, date, units, category, color}` — the journey curve and
  its markers (retirement focal point, life events).
- **`PersonalInformation`** entity — `{firstName, lastName, gender, birthDate,
  retirementAge}` → the meta cards.
- **scenario** — `{retirementAge, partnerRetirementAge, inflationRate, isDefault,
  netWorthAtRetirement, …}` → retirement ages + the curve's assumptions.

## 6. Mapping to our data

Summary is mostly about **plan inputs we don't yet model as editable entities**;
our data backs the chart and parts of the sections, but the profile structure is
new:

| Summary element | Our source / status |
|---|---|
| המסע הפיננסי שלי (curve) | `cashflow.json → projection.{timeline,focal_points}` (PRD 01 §7c) — already a lifetime net-worth curve to `end_age` |
| הפרישה שלך marker | `projection.focal_points[retirement]` |
| גיל פרישה | `projection.CONFIG.retirement_age` (placeholder 67) — **not scraped per-person**; partner age not modeled |
| הפרופיל שלי (birth date) | **not captured** — `CONFIG.current_age` is a hardcoded placeholder (PRD 01 §7c); no birth date in any scrape |
| הכנסות (section) | partial — `transactions.json` has income flows + `snapshot.detected_monthly_salary`, but **no structured income entities** (job/allowance/property) |
| הוצאות (section) | partial — `transactions.json → summary.by_category`; **no structured recurring-expense entities** |
| נכסים (section) | partial — `snapshot.bank_accounts` only; **no pension/keren/portfolio/real-estate** (the bulk of net worth) |
| התחייבויות (section) | **good** — `snapshot.loans[]` (mortgage + consumer) with balance/rate/payment/term |
| יעדים (section) | **not captured** — no goals / emergency-fund / inheritance entity |
| completeness % | derive from which of the above we actually populate |

**What we're missing (the core gap of this screen):**
- We aggregate **observed** money (a ledger + balances); Plangram's Summary is
  about **declared plan inputs** (structured income/expense/goal/asset entities the
  user authors). Most sections have no editable-entity model on our side yet.
- **Assets** beyond bank/cards/loans (pension, keren, portfolio, real-estate) are
  entirely absent — these dominate net worth and the journey curve's later years.
- **Identity** (birth date, partner, retirement ages) is not scraped; the
  projection uses placeholders, so the journey's age axis is approximate.
- **Goals** and **life events** have no representation at all.

So v1 of this screen is honest about status: the curve + liabilities + a rough
income/expense picture are real; goals/assets/identity show as "needs input".

## 7. Implementation plan (suggested)

**Phase 1 — Status map over what we have**
1. Define a `profile_sections` config mirroring Plangram's five sections + their
   entity types (income/expense/goals/assets/debt) in `data/`.
2. Add `data/summary.py` that, per section, reports `complete | partial | empty`
   from existing sources (debt ← `snapshot.loans`, assets ← `snapshot.bank_accounts`,
   income/expense ← ledger) and emits `summary.json`:
   `{ sections:[{name,title,subtitle,status,route}], complete_count, total,
   complete_percent, meta:{retirement_age, partner_age?, name?, birth_date?},
   journey:{timeline, focal_points} }`.
3. Render: journey chart (reuse `projection` series) + completeness grid + meta.
4. Cards route to (future) section editors; until those exist, link to the
   relevant digested view.

**Phase 2 — Make sections editable / complete the model**
5. Add a `PersonalInformation` store (birth date, retirement ages, partner) so the
   projection stops using placeholders and the journey age axis is exact.
6. Ingest the missing **assets** (pension/keren/portfolio/real-estate) — manual
   entry and/or new scrapers — flipping `נכסים` to complete and fixing net worth.
7. Add **goals** + emergency-fund + inheritance entities → `יעדים` complete and
   unlocks the goal-compliance metrics referenced in PRD 01/02.
8. Life-event authoring (`+ הוספת אירוע`) → markers on the journey curve.

## 8. Open questions

- **Observed vs. declared** — do we keep deriving income/expense from the ledger,
  or introduce user-authored plan entities (Plangram's model) so completeness and
  projections are intentional rather than inferred?
- **Identity capture** — where do birth date / retirement age / partner come from?
  (Manual settings screen — nothing scrapes them.) Until then the age axis and
  retirement marker are approximate.
- **Asset ingestion** — biggest gap; pension/keren/portfolio/real-estate drive both
  net worth and the journey's later trajectory. Scrape (which providers?) or manual?
- **Completeness rule** — what counts a section "complete"? (≥1 entity? all required
  `item_fields`?) Define per section to make the N-of-M honest.
- **Life events** — model now as one-time timeline entries, or defer entirely?
