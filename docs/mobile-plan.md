# Mobile compatibility plan

The dashboard is read mostly from a phone (my-finance.yarinsa.me, passkey sign-in).
Baseline after PR #3: Tailwind v4 + shadcn are in, the shell is a shadcn Sidebar that
collapses to a sheet below `md`, and the legacy grids have a single phone breakpoint so
nothing overflows at 390px. Every route renders, but it is "desktop squeezed", not
mobile-first.

Verify each phase with the `dashboard-screenshots` skill at 390×844 (and `--desktop`
to make sure desktop doesn't regress).

## What's wrong today (from 390×844 screenshots)

| Area | Problem |
|---|---|
| Navigation | Reaching another screen takes two taps (hamburger → sheet → item), with no sense of where you are. The 10 routes are a flat list. |
| Charts (`NetWorthChart`) | The Y axis is `orientation="right"` with `width={70}`, so its labels overlap the plot on narrow screens. Fixed heights (220–300px) take up half the viewport. Recharts tooltips are hover-first, which is awkward on touch. |
| KPI grids | Two-up tiles get uneven heights and leave an orphan on odd counts (Cashflow has 5 KPIs). Long helper text inside tiles (Goals) makes them tall and hard to scan. |
| Touch | `title=` tooltips (KPI hints, stale dot) never show on touch. Tap targets for whole-card links aren't sized or given press feedback. |
| Typography | Legacy Heebo plus fixed px sizes. Large ₪ figures (`-1,552,756`) are close to wrapping at 2-up. |
| App-ness | No manifest, no `theme-color`, no icons, and safe-area insets aren't handled, so Add to Home Screen gives a generic bookmark. |
| Styling debt | Routes use legacy `styles.css` (`--lg-*`). Any mobile work done there gets thrown away when we restyle with shadcn. |

## Approach

Do mobile **as part of** moving each route onto shadcn/Tailwind, not as patches on the
legacy CSS. Mobile-first classes (`grid-cols-2 md:grid-cols-4`) replace the media query
added in PR #3.

### Phase 1 — Shell and navigation
- Bottom tab bar under `md` with the 4–5 primary destinations (proposed: Overview, Cashflow, Net worth, Goals, More). "More" opens the existing Sheet with the remaining routes.
- Sticky header showing the current page title and a data-freshness indicator. Replace the stale dot's `title=` with a tap-able Popover.
- Respect `env(safe-area-inset-*)` on the header and the tab bar.
- Keep the sidebar for `md+`.

### Phase 2 — Shared building blocks (shadcn-based)
- `KpiTile`: a shadcn Card with fixed internal layout and tabular-nums. Hints move into a Popover or a collapsible description instead of `title=`. A responsive `KpiGrid` (`grid-cols-2 md:grid-cols-4`) that lets the last odd tile span both columns.
- `MoneyValue`: one formatter component. It switches to compact form (₪1.55M) below a width threshold, with the full value in an accessible label and on tap.
- `ChartCard`: wraps recharts with an aspect-ratio height instead of fixed px, a Y axis that's narrower or hidden on phones (values shown in the tooltip or a header readout), and tap-to-inspect tooltips. Use shadcn's `chart` component as the base.
- Lists and tables (Networth assets, Metrics) become stacked label/value rows on phones; shadcn `Table` from `md` up.

### Phase 3 — Route by route
Priority follows what gets opened on a phone: Overview → Cashflow → Goals → Net worth →
Metrics → Portfolio → Timeline → Summary → Recommendations → MyPlan. Each route: move it
onto the Phase 2 components, delete its legacy CSS, then take screenshots at mobile and
desktop size.

### Phase 4 — Installable app
- `manifest.webmanifest` (name, `display: standalone`, dark `theme_color`, RTL `dir`), app icons, and `apple-touch-icon` and `apple-mobile-web-app-*` meta.
- No service worker or offline cache at first. The data is private and passkey-gated, and caching it on the device is a separate decision.
- Check that the edge-auth passkey flow works when the app is launched from the home screen (standalone WebView, iOS).

### Phase 5 — Cleanup
- Remove `styles.css` and the `--lg-*` tokens once no route uses them. Drop Heebo or make it the shadcn `--font-sans`.
- Code-split routes (`React.lazy`) to get under the 1.1 MB bundle warning, which matters on mobile networks.

## Open questions
1. Bottom tab bar vs. sheet-only navigation. Which 4 screens are primary?
2. Font: keep Heebo (Hebrew-first) or move to Geist plus a Hebrew fallback?
3. Should the installed PWA ever cache data offline, or always fetch live?
4. Hide anything on mobile entirely (e.g. MyPlan, a placeholder screen)?
