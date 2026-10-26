# PWA plan — make the dashboard feel like a native app

Goal: installed to the iPhone home screen (and Android), the app launches full-screen
with no browser chrome, opens instantly from cache, works read-only offline, refreshes
itself when brought to the foreground, and behaves like a native app to touch.

## Constraints found in the code

- Everything sits behind the Cognito edge-auth Lambda (`infra/edge-auth/index.js.tftpl`):
  manifest, icons and `sw.js` all need the session cookie. Paths with a `.` skip the
  SPA rewrite, so `/sw.js` and `/manifest.webmanifest` reach S3 as they should.
- `infra/deploy.sh` uploads everything except `index.html` as `immutable, max-age=1y`.
  `sw.js` and the manifest **must** go up as `no-cache`, or updates never reach the phone.
- `lib/data.ts` loads `/data/*.json` with top-level await and checks the content type
  (an expired session comes back as a redirect or HTML, never JSON).
- `/api/*` is live editing. It must never be cached. The "Mac off = read-only" fallback
  already exists.
- Safe-area insets are already partly handled (header, tab bar, `.content`).

## Phases

### 1. Installable (manifest, icons, iOS meta)
- `app/public/manifest.webmanifest`: `name` "תמונת מצב פיננסית", `short_name` "תמונת מצב",
  `lang: he`, `dir: rtl`, `display: standalone`, `start_url: /overview`, `scope: /`,
  `id: /`, theme/background colors from the palette (`#eef4f2` / `#0d1117`),
  `shortcuts` (month, spending, syncs).
- Icons generated from one SVG mark in the mint and navy palette: 192, 512, 512-maskable,
  180 apple-touch-icon, favicon. Commit the PNGs. Do not add an icon package.
- `index.html`: `<link rel="manifest" crossorigin="use-credentials">` (without it the
  manifest fetch carries no cookie and hits the login redirect), `apple-mobile-web-app-capable`,
  `mobile-web-app-capable`, `apple-mobile-web-app-status-bar-style=black-translucent`,
  `apple-mobile-web-app-title`, and `theme-color` twice with `media` set for light and dark.

### 2. Service worker (offline + instant launch)
- Use `vite-plugin-pwa` (workbox, `injectManifest` or `generateSW`) if it supports Vite 8.
  Otherwise write a small hand-written `sw.js`. Either way, `registerType: prompt`.
- Strategies:
  - Hashed `/assets/*`: precache.
  - Navigations: network-first, falling back to the cached `index.html` **only on a
    network error**. Redirects (an expired session going to Cognito) pass through
    untouched and are never cached.
  - `/data/*.json`: network-first with a 4s timeout, falling back to the cache. Cache only
    `200` responses with a JSON content type.
  - `/api/*`, `/_callback`, `/_logout`, `/_passkey`: never intercepted.
- On `/_logout` (and any 401), clear the data cache so financial JSON doesn't stay on the device.
- `deploy.sh`: upload `sw.js`, `registerSW.js` (if any) and `manifest.webmanifest`
  with `no-cache,no-store,must-revalidate` and the right content types.

### 3. App lifecycle (feels alive)
- Update prompt: when a new SW is waiting, show a small toast "גרסה חדשה זמינה — רענן"
  that calls `updateSW()`.
- Resume refresh: on `visibilitychange` → visible (and `online`), call `reloadData()` if the
  last fetch is more than 2 minutes old. This is the native "refresh on foreground".
- Offline banner: when `navigator.onLine` is false, or data was served from the SW cache,
  show "לא מקוון · נתונים מ-<time>". Editing is disabled the same way it is when the Mac is off.
- Session expired: if `loadDigested` gets a non-JSON response or a redirect while online, show
  "החיבור פג — התחבר מחדש" with a button that does a full `location.assign("/")` instead
  of a blank error page.
- App badge: `navigator.setAppBadge(count of לטיפול actions)` when supported, cleared at 0.

### 4. Native feel (CSS + touch)
- `html, body`: `overscroll-behavior: none` (no rubber-band reveal of white),
  `-webkit-tap-highlight-color: transparent`, `-webkit-text-size-adjust: 100%`,
  `touch-action: manipulation` (no double-tap zoom delay).
- `user-select: none` on chrome (header, tab bar, buttons, rows). Numbers and text stay selectable.
- Use `100dvh` instead of `100vh`. Add `env(safe-area-inset-left/right)` padding for landscape.
- `@media (display-mode: standalone)`: tweaks only when installed (for example, extra top
  padding under the translucent status bar on desktop-width layouts).
- Pull-to-refresh hook (`usePullToRefresh`) on `<main>` in standalone mode, because iOS
  standalone has none. It runs `reloadData()`, with a spinner, and respects the existing
  `SwipeableRow` horizontal gestures.
- Route transitions: wrap navigations in `document.startViewTransition` where supported
  (cheap cross-fade/slide), honoring `prefers-reduced-motion`.
- Keep the tab bar fixed. Inputs stay ≥16px so iOS doesn't zoom on focus.

### 5. Verify
- `pnpm build && pnpm preview`, then a Lighthouse PWA/installability audit and the
  Application panel (manifest parses, SW active, offline reload works with the network disabled).
- Vitest for any pure logic (the SW route matcher, the resume-refresh throttle,
  the pull-to-refresh threshold).
- `infra/edge-auth/edge-auth.test.js` still passes. Add a case if routing changes.
- Screenshots via the `dashboard-screenshots` skill (390×844, light + dark).

## Out of scope (phase 2)
- Web Push notifications for "login needed" / sync results. These need VAPID keys, a push
  sender on the Mac and an API endpoint, so they are a separate change.
- Splash screens per iPhone size (`apple-touch-startup-image`). There are many sizes for
  small gain, so this is optional later.

## For the user to check on a real device
- iOS standalone + Cognito: when the cookie expires, the hosted login opens in-app.
  Confirm it returns to the standalone app and the cookie sticks.
- Deploy with `deploy-app` after merge, then remove the old home-screen bookmark and re-add it.

## Status

Implemented (phases 1–5) in `app/` and `infra/deploy.sh`. Approach: `vite-plugin-pwa` 2.0
(`injectManifest`, `registerType: prompt`; it supports Vite 8) with a hand-written worker in
`app/src/sw.ts`; the route rules live in `app/src/lib/swRoutes.ts` so vitest covers them.

Left out or different from the plan:
- **Lighthouse PWA audit and `dashboard-screenshots` light/dark shots**: not run. Verified with
  Playwright instead (manifest + credentialed link, SW activates and controls, offline reload and
  offline deep-route load render from cache, `/api` is not served offline). Pull-to-refresh was
  exercised with synthetic touch events in a faked standalone mode, not on a device.
- **"Any 401 clears the data cache"**: done for `/data/*` (worker and client) and `/_logout`.
  A 401 from `/api/*` is not observed (the worker never touches `/api`); `lib/api.ts` already reloads
  the page on it.
- **Expired session detection**: a redirect/401/403 on `/data/*`, or a fetch that throws while
  `navigator.onLine` is true (the cross-origin Cognito hop is blocked by CORS). HTML on a 200 is
  deliberately still the "file not published" error, since that is what a missing S3 key returns.
- **Edge-auth**: unchanged, so no new test case (`node --test infra/edge-auth/edge-auth.test.js`
  still passes).
- **Icons** are un-hashed files uploaded with the immutable cache header by `deploy.sh`; changing
  the mark later needs renamed files or an explicit no-cache upload. Regenerate with
  `app/scripts/make-icons.sh` (needs `rsvg-convert`).
- **Route transitions** use React Router's `viewTransition` on the tab bar and sidebar links only;
  links elsewhere navigate without a transition.
- `vite.config.ts` gained a `DIGESTED_DIR` env override so a worktree without `data/digested` can
  preview against another checkout's data.
