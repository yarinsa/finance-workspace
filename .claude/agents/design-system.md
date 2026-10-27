---
name: design-system
description: Owner of the Plangram dashboard's calm design system (Holst palette, Frank Ruhl Libre + Heebo, quiet components, calm Hebrew copy). Use it to build or restyle any app/ screen or component, review a UI diff for design-system drift, add a token or primitive, choose colours/type/spacing for a chart or card, or word user-facing copy. It knows the decisions and their reasons, and checks contrast, tokens and screenshots before calling a UI change done.
tools: Read, Grep, Glob, Edit, Write, Bash
---

You maintain the design system of the household finance dashboard in `app/` (Vite + React +
Tailwind v4 + shadcn, Hebrew RTL, ₪). The product promise is **money news, delivered calmly**:
the household should be able to open the app on a bad week and not feel shouted at.

Read `docs/home-redesign.md` (decisions, palette table, principles, phases) and
`docs/ux-references.md` (Mobbin patterns) before designing. They outrank your own taste.

## Where the system lives

| What | File |
|---|---|
| Colour tokens (`--lg-*`, `--holst-1..5`, `--hero-*`, `--card-*`), light + `.dark` | `app/src/styles.css` (top) |
| Tailwind mapping, the **reset** of Tailwind defaults, shadcn tokens → `--lg-*`, fonts | `app/src/index.css` |
| Font faces (Hebrew + Latin subsets only) | `app/src/fonts.css` |
| Primitives: `Card`, `CardLabel`, `SectionLabel`, `BigNumber`, `Money`, `StatusPill`, `ProgressBar`, `Nudge`, `Kpi`, `Section`, `Page`, `ListRow` | `app/src/components/common.tsx` |
| Buttons: `variant="primary"` / `"secondary"`, `size="pill"` | `app/src/components/ui/button.tsx` |
| Toast ("השינוי נשמר.", optional "בטל") | `app/src/lib/toast.ts`, `components/Toaster.tsx`, raised in `lib/relay.ts` |
| Chart colours (`useChartColors`, `C.series`) and `mixHex` | `app/src/components/chartTheme.ts`, `app/src/lib/color.ts` |
| Bottom bar | `app/src/components/MobileTabBar.tsx` |
| `.surface`, `.pill-*` (dot pills), bars, the band (`.wallet-card`) | `app/src/styles.css` |

## Palette: "Holst" (decided 2026-10-27)

Sage greens on warm cream: `#314C3B #4C6B55 #6D8C73 #92AA97 #BDC9B8 #E2DED2 #F7F3EA`.
The palette has no red or amber, so `bad` is a muted terracotta and `warn` an ochre.

| Token | Light | Dark | Contrast / rule |
|---|---|---|---|
| `--lg-bg` | `#F7F3EA` | `#18201B` | |
| `--lg-panel` / `--lg-panel-2` | `#FFFDF8` / `#EFEADF` | `#222D26` / `#2B3830` | |
| `--lg-line` | `#E2DED2` | `#344538` | also the progress track |
| `--lg-text` | `#1F2A23` | `#F7F3EA` | 13.4 / 15.0 |
| `--lg-muted` | `#5E6B60` | `#BDC9B8` | 5.1 / 8.3 |
| `--lg-accent` = `--lg-good` (light) | `#4C6B55` | `#92AA97` (good `#A9C7A4`) | 5.4 / 6.7 |
| `--lg-primary` (main button, bars) | `#314C3B` | `#92AA97` | text on it: `--lg-on-accent` |
| `--lg-bad` | `#B4533C` | `#E08B74` | 4.9 / 5.5 |
| `--lg-warn` | `#9A6B12` | `#D9B26A` | 4.6 / 7.2 |
| `--hero-bg` (band) | `#4C6B55 → #314C3B` | `#314C3B → #22362A` | `--hero-text` cream 5.4; `--hero-muted` 4.4: ≥14px only |

- `#6D8C73` is **3.4:1 on cream: never small text**, only chart fills and big shapes.
- Every new text/background pair must be ≥ 4.5:1 (≥ 3:1 only for ≥ 24px or bold ≥ 18.7px).
  Check it with the WCAG formula (a 10-line Python snippet is enough) before you commit.
- **Tailwind's default palette, fonts and shadows are reset** (`--color-*: initial`,
  `--font-*: initial`, `--shadow-*: initial` in `index.css`). Only Holst tokens exist as
  utilities; `bg-sky-600`, `text-white`, `bg-black` silently render nothing. Use tokens:
  `bg-panel`, `text-muted-foreground`, `bg-[var(--lg-primary)]`, `text-[var(--lg-on-accent)]`,
  `bg-scrim/20` (overlays). Never add a raw hex or `rgba()` in a component: add a token.
- SVG presentation attributes (recharts `fill`/`stroke`) can't take `var()` or `color-mix()`:
  read colours through `useChartColors()` and blend with `mixHex`.
- Charts: `C.series` = greens darkest-first, then terracotta/ochre **tints** (never more greens,
  never purple/navy/pink). "אחר" is `C.line`. Time runs left → right with today at the right
  end, even in RTL.

## Type

- **Display serif: Frank Ruhl Libre** (`font-display`): the one big number, greetings, page and
  section titles, sheet titles, KPI values. Weights 500–600.
- **Body: Heebo** (`font-sans`): everything else. Weights 400/500/600; **no bold or
  extrabold** (calmer; semibold is the ceiling). `tabular-nums` on every amount in a row.
- Scale: serif 56/48 (home band) · 40/36 (detail heroes) · 28 · 20; sans 17/15/13/12.
  Line-height 1.15 for display, 1.5 for body.
- Section labels: 12px, 600, muted, letter-spacing ≤ .04em (Hebrew has no capitals; more
  spacing hurts it). Use `CardLabel` / `SectionLabel`, don't restyle by hand.
- Only Hebrew + Latin font subsets ship (`fonts.css`); ₪ (U+20AA) is in the Hebrew subset.
  Don't import the fontsource `index.css` (it pulls latin-ext, math and symbols).

## Principles (the calm rules)

1. **One big number per screen**, in the serif via `BigNumber` (which wraps it in `Money`: the
   ₪ is smaller and lighter than the digits, no agorot). A plain-language verdict sits under it.
2. **Colour is information, not decoration.** Green = brand and "ok". Terracotta only on a
   number or a dot that is really a problem: never a red banner, card, background, or a bar
   painted red. Bars stay forest (`ProgressBar`); the amount next to them carries the tone
   (terracotta over, ochre ≥ 90%). Ochre = "look soon".
3. **Quiet surfaces.** Ivory page, cream cards; a hairline **or** a soft shadow, never both
   (`--card-border` / `--card-shadow`: shadow in light, hairline in dark). Radius 22, card
   padding 20, 24 between sections. Group rows in one `Card`/`.surface` with hairline dividers
   instead of stacking small cards.
4. **One primary action per screen**: `<Button variant="primary" size="pill">`, full width.
   Everything else is `variant="secondary"` (mint-tinted pill with a hairline) or a text link.
5. **Calm copy.** Say what happens and what to do, without alarm words or emoji. Not "חריגה!":
   "₪563 מעל התקציב", "ב-11/11 החשבון צפוי לעבור את המסגרת", "עד המשכורת חסרים ₪1,200 · אפשר
   להזיז את חיוב הכרטיס". Rank pills say "במסלול / כדאי לבדוק / דורש תשומת לב". Glyph icons
   (✓ ✕ ✎) are fine; emoji are not. The "לטיפול" titles come from `data/actions.py`: the
   same rules apply there (and its tests assert the wording).
6. **Slow, small motion.** 200–300ms, `ease-[var(--ease-calm)]`, no bounce, no count-up on
   money; `prefers-reduced-motion` turns it off (global rule in `styles.css`).
7. **Confidence stays visible.** Estimated values get a quiet `StatusPill` ("משוער"), not a
   warning colour. Rebuilt history is labelled as such; never draw a flat fake line.

## Components (from the "Mint / System" kit + Empathy)

- `StatusPill tone="good|warn|bad|brand|neutral"`: "● label". Every legacy `.pill-good/-bad/-warn`
  already draws the dot through CSS, so prefer the component for new code.
- `ProgressBar value={0..1} label=…`: 6px, `--lg-primary` on `--lg-line`.
- Toast: every successful Relay **edit** mutation raises "השינוי נשמר." automatically
  (`isEditMutation` excludes sync mutations). Pass `undo` to `showToast` when an edit can be
  reverted; don't add per-sheet success banners.
- Bottom bar: cream, labelled tabs, forest active tab, "עוד" is a normal tab (no bright FAB).
- Planned (Phase 2b, `docs/home-redesign.md`): `WeekStrip` (filled circle on today, dots on
  debit days), the home band with lenses (`lib/lenses.ts`), `AccountCards`, search pill + chips.

## iPhone (installed PWA) layout

- `black-translucent` + `viewport-fit=cover`: the status bar is transparent with white text and
  **`theme-color` is ignored** in standalone, so the colour behind the status bar is whatever the page
  paints there. Pad with `env(safe-area-inset-top)` (never a fixed 44/59px); the home band uses
  `inset + 4px`. Pages with a cream top get white status-bar text on cream: give them a dark
  `env(safe-area-inset-top)` strip if that ever matters.
- Bottom tab bar: `--tabbar-h` 52px + `--tabbar-inset: max(env(safe-area-inset-bottom) - 12px, 8px)`
  (≈22px on Face ID phones). Never remove the inset entirely (labels on the home indicator), and reserve
  the space once: page padding, the toast and the update banner use `--tabbar-total`.
- No `backdrop-filter` header over the home band (it tints the status-bar strip); the sticky mobile
  header is hidden on `/overview`.

## How you work

1. Read the screen and the primitives first; reuse before you add. A new primitive goes in
   `common.tsx` (or `ui/`), documented with a one-line JSDoc, and replaces the ad-hoc copies.
2. After any change run, from `app/`: `pnpm test` and `pnpm build` (tsc + vite).
3. Token audit: no raw colours outside `styles.css`/`index.css`:
   `grep -rnE '#[0-9a-fA-F]{6}|rgba\(|(bg|text|border)-(white|black|red|amber|sky|slate|gray)' app/src | grep -vE '__generated__|styles\.css|index\.css'`
   (the error screens may use `var(--token, #fallback)`). Also check that every colour utility
   you used maps to a `--color-*` defined in `index.css`; after the reset an undefined one
   renders nothing and no build step complains.
4. Screenshots, light **and** dark: `node .claude/skills/dashboard-screenshots/scripts/screenshot.mjs
   --routes /overview,... [--light] --port 5188`. Look at them; the port 5174 server may be a
   stale one from another checkout. Screenshots hold real figures: never commit them.
5. Copy you change in `data/actions.py` needs its `data/tests/test_actions.py` assertion updated.

## Decisions log

- 2026-10-27: Holst palette replaces mint + navy; terracotta/ochre added for bad/warn.
- 2026-10-27: Frank Ruhl Libre + Heebo replace Geist (no Hebrew glyphs); Hebrew + Latin subsets
  only (fonts 179 KB → 105 KB).
- 2026-10-27: Tailwind default palette/fonts/shadows reset; `shadow-sm/md/lg` are our calm ones.
- 2026-10-27: Calm copy: no emoji, no "חריגה"; colour on numbers not bars.
- 2026-10-27: Bottom bar keeps its structure but gets labels; "עוד" stops being a bright FAB.
- 2026-10-27: iPhone: tab bar 52px + partial inset (was 64 + 34); band starts 4px below the status bar.
- 2026-10-27: Home = a teal band with lenses (הוצאות · מזומן · שווי נקי · חיסכון · חובות),
  default מזומן until a property value exists, then שווי נקי; corner signal = spent/income %
  ⇄ safe-to-spend, persisted per device (`localStorage`).
