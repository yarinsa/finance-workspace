# Home screen redesign: lens band + account cards

Status: **planned** (2026-10-27). Source concept: a Mint/Credit Karma–style home with a
coloured hero band, swipeable lenses (Spending / Net worth / Cash / Investments), a
history line ending in a "Today" dot, and white account cards overlapping the band.

The gap that drives most of the work: the app has **no history**. `snapshot.json` is
today only and `cashflow.projection` is forward-only, while the concept's chart is
"how did I get here".

## Decisions (made with the household)

1. **Property is an asset.** Manual value for now (stored in the DB, edited from the
   app). Later an automatic estimate, so the row carries `valuation_source`
   (`manual` now, `estimate` later) and `valued_at`.
2. **＋ opens a quick-actions sheet:** sync now · update property value · add goal ·
   offset a payback (קזז החזר). No manual transactions.
3. **Corner signal** (where the concept shows a credit score): **spent / income %**
   for this month (`pace.current.expense / pace.current.income`). Tapping it toggles
   to **safe to spend until payday** (`runway.safe_to_spend`). The choice is
   persisted on the device (`localStorage["home.signal"]`).
4. **Default lens = שווי נקי** once a property value exists (net worth turns
   positive and meaningful); **מזומן** while it doesn't (−₪900k without the
   apartment is a misleading first number). ⋮ lets the user pin another default
   (also `localStorage`).
5. Bottom tab bar unchanged. Lenses become the way into the detail pages.
6. **Palette: "Holst"** (sage greens on warm cream), replacing mint + navy app-wide.
   See the Palette section below.

## Palette ("Holst")

Seven palette colours: `#314C3B` `#4C6B55` `#6D8C73` `#92AA97` `#BDC9B8` `#E2DED2` `#F7F3EA`.
The palette has no red or amber, so `bad`/`warn` use a muted terracotta and ochre
picked to sit with it. Contrast (WCAG) checked; all text pairs ≥ 4.5 unless noted.

| Token (`styles.css`) | Light | Dark | Notes |
|---|---|---|---|
| `--lg-bg` | `#F7F3EA` | `#18201B` | dark = palette deepened |
| `--lg-panel` | `#FFFDF8` | `#222D26` | |
| `--lg-panel-2` | `#EFEADF` | `#2B3830` | |
| `--lg-line` | `#E2DED2` | `#344538` | |
| `--lg-text` | `#1F2A23` | `#F7F3EA` | 13.4 / 15.0 |
| `--lg-muted` | `#5E6B60` | `#BDC9B8` | 5.1 / 8.3 (`#6D8C73` is only 3.4 on cream: never small text) |
| `--lg-accent` | `#4C6B55` | `#92AA97` | 5.4 / 6.7 |
| `--lg-on-accent` | `#F7F3EA` | `#18201B` | |
| `--lg-good` | `#4C6B55` | `#A9C7A4` | |
| `--lg-bad` | `#B4533C` | `#E08B74` | terracotta, 4.9 / 5.5 |
| `--lg-warn` | `#9A6B12` | `#D9B26A` | ochre, 4.6 / 7.2 |
| `--hero-bg` (band) | `#4C6B55` → `#314C3B` gradient | `#314C3B` → `#22362A` | |
| `--hero-text` | `#F7F3EA` | `#F7F3EA` | 5.4 on `#4C6B55` |
| `--hero-muted` | `#E2DED2` | `#BDC9B8` | 4.4 on `#4C6B55`: ≥ 14px only |
| `--hero-chart` (area) | `#92AA97` line, `#BDC9B8` fill 40% | same | Today dot: `#F7F3EA` ring on `#92AA97` |
| `--shadow` | `0 6px 24px rgba(49,76,59,.08)` | `rgba(0,0,0,.35)` | |

- Charts (`chartTheme.ts`, `--chart-1..5`): the green ramp `#314C3B` `#4C6B55`
  `#6D8C73` `#92AA97` `#BDC9B8` (reverse order in dark). Category charts with more
  than 5 series add terracotta/ochre tints rather than more greens.
- shadcn tokens in `index.css` (`--background`, `--primary`, `--border`, `--ring`,
  `--sidebar-*`, …) map onto the `--lg-*` values instead of the neutral greys, so the
  sidebar, sheets and popovers match.
- `index.html` `theme-color` and the PWA manifest colours: `#F7F3EA` / `#18201B`.
- Remove the old `--hero-1/2` navy and `--hero-accent` mint once nothing reads them.

## Design language: calm

References: **Empathy** (a calm fintech/estate app: warm ivory surfaces, serif
headlines, human copy, one dark primary button, quiet checklists) and a **"Mint /
System"** Pinterest kit (forest/mint/ivory/ink, serif "Aa", pill buttons, status pill
with a dot, thin progress bars, a week strip with a filled "today", a check-circle
toast). We take their *tone and components*; colours come from Holst (below).

The feeling we want: money news, delivered calmly. The household should be able to
open the app on a bad week and not feel shouted at.

### Principles
1. **One big number per screen**, in the serif, 48–56px on the home band and
   40px on detail heroes. ₪ sign smaller and lighter than the digits; no agorot in
   heroes. A plain-language verdict sits under it in the sans.
2. **Colour is information, not decoration.** Green = brand and "ok". Terracotta
   only on a number or a dot that is really a problem — never a red background, banner
   or card. Ochre for "look soon". Everything else is ink and muted.
3. **Quiet surfaces.** Ivory page, cream cards, a hairline border *or* a soft
   shadow (not both), radius 20–24, 20px card padding, 24px between sections. Fewer
   cards per screen; group rows inside one card with hairline dividers (Empathy
   checklist) instead of stacking many small cards.
4. **One primary action per screen**: a full-width forest pill. Everything else is
   the secondary pill (mint-tinted fill, hairline border) or a text link.
5. **Calm copy.** Say what happens and what to do, without alarm words or emoji:
   "עד המשכורת חסרים ₪1,200 ב־3.11 · אפשר להזיז את חיוב הכרטיס" rather than "חריגה!".
   Greetings and screen titles in the serif ("ערב טוב"). Drop the 👋 / 🕑 emoji.
6. **Slow, small motion.** 200–300ms ease-out, no bounce, no count-up animations
   on money; respect `prefers-reduced-motion`.
7. **Confidence stays visible** (from `ux-references.md`): estimated values get a
   quiet "משוער" status pill, not a warning colour.

### Typography
- **Display (serif): Frank Ruhl Libre** (`@fontsource-variable/frank-ruhl-libre`,
  Hebrew + Latin). Big numbers, greetings, screen titles, card titles.
- **Body (sans): Heebo** (`@fontsource-variable/heebo`, Hebrew + Latin). Geist has no
  Hebrew glyphs, so today Hebrew falls back to the system font; Heebo gives one
  consistent face. Rows and tables keep `tabular-nums`.
- Section labels (the kit's letter-spaced "COLOR PALETTE"): Hebrew has no capitals,
  so 12px, weight 600, muted, letter-spacing .04em at most (more hurts Hebrew).
- Scale: 56 / 40 / 28 / 20 serif; 17 / 15 / 13 / 12 sans. Line-height 1.15 for
  serif display, 1.5 for body.
- Check that Frank Ruhl Libre's digits look right in large ₪ amounts; if they
  don't, use Heebo light for the digits and keep the serif for words.

### Components (from the kit, adapted)
| Kit component | Our use |
|---|---|
| Primary / secondary pill buttons | `Button` variants `primary` (forest `#314C3B`, cream text) and `secondary` (fill `#EEF2EC`, border `#BDC9B8`, ink text) |
| Status pill with a dot ("In progress") | `StatusPill`: sync states, bill paid/upcoming/overdue, "משוער", goal on track. Replaces the coloured `.pill-*` blocks |
| Thin progress bar + % | `ProgressBar` (6px, forest on `#E2DED2`): budgets, goals, month elapsed |
| Week strip with a filled "today" and dots | `WeekStrip` on home "בקרוב": days with a debit get a dot; tap a day to see its bills and balance-after |
| Search pill + filter chips | Transaction search on `/spending` and the ledger |
| Toast with a check circle | `Toast` "השינוי נשמר." (+ "בטל" when the edit can be undone) for every ledger, goal and property edit. No toast exists today |
| Toggle (forest on) | Settings and the push-notifications card |
| Task card (icon tile, title, meta, ⋮) | Inbox items and goals: meta label above the title (Empathy "The Funeral / Look for final wishes") |
| Empathy checklist with sections and counts | Inbox: "לטיפול (3)" / "נדחה לאחר כך (2)" sections, circle check to archive |

### Navigation tone
Keep the bottom-bar structure, but make it calmer: ivory/cream bar, **text labels
under the icons** (Empathy's Home / Explore / To Do / Vault), forest for the active
tab, and the "עוד" button becomes a normal tab instead of the bright round button.

## Layout (mobile, RTL)

```
┌──────────────── teal band (--hero-bg) ─────┐
│ ＋  🔔•                   הוצאות/הכנסה 84% │  header: signal (tap toggles), inbox, actions
│   חובות  חיסכון  [שווי נקי]  מזומן  הוצאות   │  lens tabs
│                                 ₪1,093,354 │  big number (scrub → that day)
│                       ↑ ₪3,400 החודש       │  delta chip, only when measured
│      ╭──────────────────────●┄┄┄┄┄┄┄┄      │  history → היום dot → dashed projection
│ ────╯                      היום            │
│  ⋮            • • ● • •            הרחב ‹   │
├────────────────────────────────────────────┤
│ ┌ מזומן ופיקדון נזיל                  ‹ ┐ │  first card overlaps the band
│ ┌ כרטיסי אשראי                        ‹ ┐ │
│ ┌ חיסכון ארוך טווח                    ‹ ┐ │
│ ┌ הלוואות                             ‹ ┐ │
│ ┌ משכנתא                              ‹ ┐ │
│ ┌ נכס (דירה)   עודכן ידנית 10/2026    ‹ ┐ │  tap → property editor sheet
│ בקרוב (UpcomingChips) · תנועות אחרונות     │  kept
└────────────────────────────────────────────┘
```

Leaves the home: `StatusTiles` (absorbed into lenses; growth index + debt-repayment %
move to `/metrics`, debt % also as a footer on the חובות lens), `home/Hero` (replaced),
`RunwayCard` (becomes the cash lens), `InboxButton` (becomes the bell, same count).

## Lenses

| Lens | Big number | Chart | הרחב → | Data |
|---|---|---|---|---|
| הוצאות | Spent this month | Cumulative this month vs last month | `/spending` | `pace` + daily cumulative (small addition) |
| מזומן | Checking balance | 30 days actual + 45-day runway dashed; low point, ₪0, overdraft lines | `/monthly?view=forecast` | future ✅ runway; past **new** (running balances) |
| שווי נקי | Net worth incl. property | History to היום; projection placeholder until ≥14 points | `/networth` | **new** daily snapshots |
| חיסכון | Long-term savings | Monthly points | the home savings card, opened (`?holdings=1`; `/portfolio` redirects there) | **new** daily snapshots (monthly sources) |
| חובות | Total debt | Paid-down line, past + future | `/networth` | ✅ amortization schedules in the dumps |

## Interaction rules

- Carousel = CSS scroll-snap, no new library. Tabs follow the scroll. RTL: next lens is
  to the left; dots mirrored.
- Lens in the URL: `/overview?lens=cash` (same pattern as `/monthly?view=`).
- Scrub: finger on the chart swaps the big number for that day's value and the chip for
  the date (reuse `NetWorthChart`'s mobile readout). Release → today.
- Time runs left → right, היום at the right end (matches existing charts).
- No fake data: a lens without history shows "היסטוריה נאספת מ־<date>" + the dashed
  projection. Delta chip hidden unless both ends are measured.
- Freshness ("עודכן לפני N ימים" + sync dot) sits in the band under the big number.
- Desktop: full-width band (chart one side, number the other), cards in a 3-col grid,
  sidebar as today.
- Dark mode: `--hero-bg` is a deep teal; light mode the muted teal of the concept.

## Phases

### Phase 1 — data (Python, pytest from real records) — done 2026-10-27
- [x] `data/history.py`: daily cash balance, last 90 days, from the banks' running
      balances (the chain `validate.py` already walks). Emits `cashflow.history.cash`.
- [x] Debt series past + future from the loan dumps (reverse / forward amortization;
      the dumps carry no full schedules) → `cashflow.history.debt`.
- [x] Daily position snapshot on every digest: Postgres `position_snapshots`
      (date PK, cash, card_debt, consumer_loans, mortgage, savings, property, net_worth).
      **Published inside `cashflow.json` → `history.positions`** rather than a separate
      `history.json` (no new file to deploy or fetch). Best-effort like `db/inbox.py`.
- [x] Property asset: table `assets` (migration 0014), `db/asset_store.py`, digest adds
      `snapshot.totals.property_value` and `net_worth_with_property`.
- [x] GraphQL, Linear style: `assets` connection, `assetCreate(input)`,
      `assetUpdate(id, input)` → `AssetPayload {success, asset}`; edits signal a rebuild.
- Found on the way, fixed with regression tests: the 2026-10-27 Leumi scrape saved loan
  2529 twice (consumer debt +₪13k, the מילואים loan lost), and the snapshot kept
  RiseUp's stale Leumi `loan_account` copy instead of the direct checking account, which
  dropped Leumi from the runway pool.

### Phase 2a — calm design system (app-wide, before any new screen) — done 2026-10-27
- [x] Holst palette (tokens above): `styles.css`, the shadcn tokens in `index.css` now
      read the `--lg-*` values (one `.dark` switch), `chartTheme.ts` (`series`: greens,
      then terracotta/ochre tints mixed in JS — SVG attributes don't take `color-mix()`),
      `theme-color`/manifest, the error screens. Off-palette navy/purple/pink/sky are gone.
- [x] Tailwind's default palette, fonts and shadows are **reset** (`--color-*: initial` …):
      only Holst tokens exist as utilities, `shadow-sm/md/lg` are our calm shadows.
- [x] Fonts: Frank Ruhl Libre (display) + Heebo (body), **Hebrew + Latin subsets only**
      (`src/fonts.css`; 4 woff2 / 105 KB instead of 8 / 179 KB), `--font-display`.
- [x] Primitives: `Button` `primary` + `secondary` + size `pill`, `StatusPill` (and every
      `.pill-*` now draws the dot), `ProgressBar` (6px forest on hairline), `Toast`
      (raised by the Relay network layer after any edit mutation), `SectionLabel`,
      `Money` (₪ smaller than the digits), `BigNumber` in the serif, `.surface`.
- [x] Calm copy: no emoji; "חריגה" → "מעל התקציב" / "החשבון צפוי לעבור את המסגרת"
      (`actions.py` titles too), rank pills "במסלול / כדאי לבדוק / דורש תשומת לב".
- [x] Bottom bar: labels, cream bar, forest active, "עוד" as a normal tab.
- [x] Screenshots light + dark (`dashboard-screenshots --light` added).
- Not yet: "בטל" (undo) in the toast — the Toast supports it, no edit passes one yet.

### Phase 2b — home shell (ships with מזומן + הוצאות) — done 2026-10-27
- [x] `WeekStrip` for "בקרוב" (replaces `UpcomingChips`): today filled, dots on debit days,
      balance-after and "משוער" per item (`lib/week.ts` + tests).
- [x] `components/home/HomeBand.tsx`: header (signal, bell, ＋), tabs, scroll-snap
      carousel (RTL), dots, הרחב, ⋮ (pin default lens); `LensChart` on `--hero-*` tokens,
      ₪0 line when the cash runway dips below zero. The mobile sticky header hides on home.
- [x] `components/home/Signal.tsx`: spent/income % ⇄ safe to spend, persisted.
- [x] `components/home/QuickActionsSheet.tsx`: סנכרון (→ /syncs: there is no "sync all"
      endpoint), שווי הדירה (`PropertyEditorSheet`, pulled forward from Phase 3), יעד חדש
      (`GoalEditorSheet`), קיזוז החזר (→ /spending, offsets start from the expense).
- [x] `components/home/AccountCards.tsx` replacing `AccountRows` (cards, overlap, property card).
- [x] `lib/lenses.ts`: pure builders (series, big number, delta) + vitest.
- [x] Removed `StatusTiles` / `RunwayCard` / `UpcomingChips` / `InboxButton` from home; the
      growth index and debt-repayment % were already on `/metrics`.

### Phase 3 — remaining lenses
- [x] חובות lens (`history.debt`, `debtLens`). (Property card + `PropertyEditorSheet` shipped in 2b.)
- [x] חיסכון and שווי נקי lenses (`savingsLens`, `networthLens`) on `history.positions`,
      shown from two recorded days, past only (the chart ends at היום; no projection). Days
      recorded before the apartment was typed in carry its latest valuation, so entering it
      is not a ₪2.2M jump. Change = since the first recorded day.
- [x] Backfill: the site bucket keeps every published `snapshot.json` version, so
      `data/history.py backfill FILE...` seeds `position_snapshots` from them, keeping only
      days whose coverage (bank accounts, loans, savings accounts) matches today's: before
      10-24 the Leumi loan 66730014 was unread and a liquid deposit still counted, which
      would draw moves that never happened. Seeded 10-25 and 10-26.

- [x] חיסכון ארוך טווח card is collapsible and holds the החזקות list (fund type,
      institution · עצמאי/שכיר · policies); the `/portfolio` page and its disclaimer are gone.
- [x] Same `CollapsibleCard` for מזומן ופיקדון נזיל (bank accounts with their overdraft line,
      liquid deposits, a link to the balance forecast). הלוואות and משכנתא both open to
      `LoanDetails` (logic in `lib/loans.ts`): effective average rate, monthly payment, payoff;
      the fixed/variable mix; each loan or track with its rate and a bar of how much is paid off
      (principal when the original amount explains the balance, else payments made). A loan the
      bank names "ללא ריבית" counts at 0%. /networth lost its assets, liabilities and mortgage
      cards, which live on the home now.

### Phase 4 — polish
- [ ] Scrub readout, view transitions into detail pages, desktop layout.
- [ ] Screenshots at each phase via the `dashboard-screenshots` skill (390×844 dark).
