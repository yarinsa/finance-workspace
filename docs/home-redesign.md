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
| חיסכון | Long-term savings | Monthly points | `/portfolio` | **new** daily snapshots (monthly sources) |
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

### Phase 1 — data (Python, pytest from real records)
- [ ] `data/history.py`: daily cash balance, last 90 days, from the banks' running
      balances (the chain `validate.py` already walks). Emits `cashflow.history.cash`.
- [ ] Debt series past + future from mortgage / Leumi / Discount amortization schedules
      → `cashflow.history.debt`.
- [ ] Daily position snapshot on every digest: Postgres `position_snapshots`
      (date PK, cash, card_debt, loans, mortgage, savings, property, net_worth),
      published as `data/digested/history.json`. Best-effort like `db/inbox.py` (a
      dead DB never stops the digest). Follow the `schema-change` skill.
- [ ] Property asset: table `assets` (id, kind, label, value, valued_at,
      valuation_source, updated_at), `finance_api` select/insert/update. Digest adds
      `snapshot.totals.property_value` and `net_worth_with_property`.
      Keep `tracked_net_position` / `net_position_with_savings` unchanged.
- [ ] GraphQL, Linear style (`api/schema/root.graphql` conventions):
      `assets` query, `assetCreate(input)`, `assetUpdate(id, input)` → `AssetPayload
      {success, asset}`. An update signals the ledger rebuild (the totals change).

### Phase 2 — shell (ships with מזומן + הוצאות)
- [ ] Holst palette first (tokens above): `styles.css`, the shadcn mapping in
      `index.css`, `chartTheme.ts`, `theme-color`/manifest. Screenshot every route light
      + dark to catch hardcoded colours (`grep -rn '#[0-9a-fA-F]\{6\}' app/src`).
- [ ] `components/home/HomeBand.tsx`: header (signal, bell, ＋), tabs, scroll-snap
      carousel, dots, הרחב, ⋮ (pin default lens).
- [ ] `components/home/Signal.tsx`: spent/income % ⇄ safe to spend, persisted.
- [ ] `components/home/QuickActionsSheet.tsx`: sync now (existing sync mutation),
      property value, add goal (`GoalEditorSheet`), offset (deep link to the ledger).
- [ ] `components/home/AccountCards.tsx` replacing `AccountRows` (cards, overlap).
- [ ] `lib/lenses.ts`: pure builders (series, big number, delta) + vitest.
- [ ] Remove `StatusTiles` / `Hero` / `RunwayCard` from `Overview`; move the two
      metric tiles to `/metrics`.

### Phase 3 — remaining lenses
- [ ] חובות lens. Property card + `PropertyEditorSheet` (value, date; read-only when the
      API is down, like other edits).
- [ ] חיסכון and שווי נקי lenses on `history.json`, projection placeholder until ≥14
      points. Default-lens rule from decision 4.

### Phase 4 — polish
- [ ] Scrub readout, view transitions into detail pages, desktop layout.
- [ ] Screenshots at each phase via the `dashboard-screenshots` skill (390×844 dark).
