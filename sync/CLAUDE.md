# Sync, refresh and freshness

Loaded when working under sync/. Project overview: the root CLAUDE.md.

### Refreshing everything

The `refresh-all` skill orchestrates all nine sources end to end. It checks
every session **first** (`.claude/skills/refresh-all/scripts/check_sessions.sh`), batches the logins you need
into one pass, scrapes in dependency-correct order, then digests and forecasts.

Two things it encodes that are easy to get wrong:

- **Discount order is `account → mortgage → business`.** The three Discount apps
  share one login; the business (SME) app rebinds the server session and blocks
  the mortgage endpoints with `actionRequired: stepup`. Business last, always.
- **Never overwrite a good dump with error stubs.** A scrape against a
  half-authenticated session returns HTTP 200 with a few hundred bytes of error
  JSON. Verify the session is live *before* writing; stop rather than dump.

**The user logs in.** Credentials, OTPs and card numbers are never typed by an
agent, read from Keychain, or pulled from Messages — these are live bank
accounts, and unattended authentication is not a capability worth automating.
Chrome profiles persist logins, so this costs a login only when one lapses.


### Automated sync (Temporal) — POC

**Proof of concept** (dev server, no persistence guarantees); see
`sync/README.md` for status. Not yet the only refresh path — `refresh-all` remains.

`sync/` runs `FinanceSyncWorkflow` daily at 06:20 and 22:00 Asia/Jerusalem over every scraped
source (discount, discount-mortgage, discount-business, leumi, cal, amex, harel, more,
analyst; RiseUp is out of scope) with the Temporal dev server in Docker Compose
(`docker-compose.yml`) and the worker under launchd. It checks **every** session
first, sends **one** macOS notification listing
the dead logins (grouped by login), and waits up to 15m
for `poetry run python sync/resume.py [source|group ...]`; still-dead sources are skipped as
`needs_login`, never fatal. Live sources are scraped one at a time in registry order
(Discount **business → mortgage → account**, all three self-login), each followed by
a `data/validate.py dump <source>` gate (skipped while that file doesn't exist); one
failing source never stops the rest. Then digest chain once and
`infra/deploy.sh --data-only` once (when `SYNC_PUBLISH=1`; withheld if a dump was
rejected). It never authenticates a Chrome session. **One exception:**
Discount business, mortgage and checking are scraped by `scrapers/discount/scrape-business.mjs`,
`scrape-mortgage.mjs` and `scrape.mjs` (shared `lib.mjs`), which log in headless with
`DISCOUNT_ID`/`DISCOUNT_PASSWORD`/`DISCOUNT_NUM` from `.env` (check mode `self`, no
Chrome; business uses the SME login page, ID + password only) and write the same raw files
as the CDP `dump.sh` scripts; a refused login becomes `needs_login` (and skips the other
Discount sources, which share the credentials).
CAL works the same way: `scrapers/cal/scrape.mjs` logs in headless with
`CAL_USERNAME`/`CAL_PASSWORD` from `.env` (check mode `self`) and writes the same
`data/cal/raw` files as `refresh/scripts/cal/dump.sh`; a refused login (or a demanded OTP) is `needs_login`.
Max does the same: `scrapers/max/scrape.mjs` logs in headless with `MAX_USERNAME`/`MAX_PASSWORD`
(check mode `self`, its own login group) and writes `data/max/raw/`.
Leumi too: `scrapers/leumi/scrape.mjs` logs in headless with `LEUMI_USERNAME`/`LEUMI_PASSWORD`
(check mode `self`) and makes the `dump.sh` + `dump-loans.sh` calls, writing the same `data/leumi/raw/` files.
Harel can't self-login (its only login is ID + phone + OTP), so it is headless the other way:
`scrapers/harel/scrape.mjs` reuses the human's login in `~/.chrome-cdp-harel` (check mode
`headless`: `scrape.mjs --check`, no Chrome window unless the session is dead, then the normal
login notification opens it; about one login a month). It can also log in **from the app**: the
`/syncs` Harel row's "התחבר עם קוד SMS" calls `POST /api/sync/harel/login`, which starts a
one-source sync (`finance-sync-login-harel`); `scrape.mjs --login` types `HAREL_ID`/`HAREL_PHONE`
from `.env`, Harel texts a code, the human types it in the app (`POST /api/sync/harel/otp` ->
`submit_otp` signal -> `deliver_otp` writes `~/.finance-otp/harel.code`, 0600, read once). The code
is typed by the human, never read from SMS/email; scheduled runs never request one, and a rejected
code is never resubmitted.
The source registry is `sync/sources.py`.
**Developing the sync** (debugging a failed source, restarting the worker/API, the GraphQL rule for
new sync actions, testing): the `sync-dev` skill. The running worker and API load code from the main
checkout's `master`, not a worktree. A failed or rejected source can be retried from `/syncs`
(GraphQL `syncSourceRetry`), continuing at scrape or straight at digest/publish.
Every source's progress (checking_session → waiting_for_login → scraping → validating →
digesting → publishing → done, or needs_login / failed / rejected) is published as its own
entry to `data/sync-status.json` **and** upserted into Postgres `sync_status`, whose trigger
`NOTIFY`s the API; the app gets it live over SSE (`GET /api/sync/events`: a `snapshot`, then a
`source` event per change) for `/syncs`, the header dot and the home list. When the stream fails
(Mac off) the app falls back to polling the S3 JSON. The worker seeds `sync_status` from the JSON
on start.
Install with `sync/install.sh`; UI at http://localhost:8233. `temporalio` is in the
Poetry `sync` group.

**Push notifications.** The PWA subscribes to Web Push from the `/syncs` "התראות" card; the API only
stores subscriptions (`push_subscriptions`, role `finance_api` gets select/insert/delete; `POST
/api/push/subscribe|unsubscribe`, `GET /api/push/key`) and holds just `PUSH_VAPID_PUBLIC_KEY`. The
VAPID private key (`PUSH_VAPID_PRIVATE_KEY`, `PUSH_VAPID_SUBJECT`) lives only in the Mac's `.env`;
`finance/push.py` (owner `DATABASE_URL`) sends from the sync activities: login needed, failed/rejected
source, new PROBLEM/WARNING inbox items (one push each, deep link `/inbox?tab=…`; `notifications.pushed_at`
is the record of what was pushed, written only by the Mac), and the 22:00 daily summary, which also
counts new REMINDER/SUGGESTION items (INFO is never pushed). It never raises. Keys: `poetry run python sync/push_keys.py <email>`; steps in `sync/README.md`.

### Freshness targets

`data/freshness.py` holds a per-source target (max age + grace) instead of one
global staleness rule: banks and cards **daily** (24h + 12h), the mortgage/loans
**weekly** (7d + 2d), pension/study/gemel **monthly** (30d + 7d). RiseUp has no
target and is never listed. Age is the newest `raw/` file mtime (what
`digest.source_syncs` calls `last_synced`). State is `fresh` -> `due` (past target,
inside grace) -> `overdue` (past grace; raises the home "נתונים לא עדכניים"
action, naming how late each source is) or `never`.

- `poetry run python data/freshness.py` prints the table (`--json` for the list; `--root DIR`
  reads another checkout's dumps read-only). `digest.py` writes the same list to
  `snapshot.json` -> `freshness`.
- `due_sources(now)` is the pure "scrape these today" list for the scheduled sync,
  in Discount-safe order (account -> mortgage -> business). A new source must be
  added to `TARGETS` (a test enforces it).

