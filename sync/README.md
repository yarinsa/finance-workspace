# Automated sync (Temporal) — POC

> **Status: proof of concept.** Runs on a local Temporal dev server (no
> persistence guarantees) and is not wired into `refresh-all`. Keep `refresh-all`
> as the manual path; use this as the unattended daily one.

`FinanceSyncWorkflow` refreshes every scraped source daily at 06:20 and 22:00
Asia/Jerusalem on this Mac, then digests and publishes once:

```
preflight (all sessions) -> one login notification + wait -> scrape each live source
  -> validate each dump -> digest -> publish
```

RiseUp is deliberately not covered.

**The automation never logs in.** A dead session sends a macOS notification and
waits up to 15m for you. No credentials, OTPs, Keychain reads or keep-alive pings.

## Sources

Defined once in `sources.py` (ports, Chrome profiles, login URLs, tab matching, dump
commands, session-check strategy). Registry order is the scrape order.

| Source | CDP port | Login group | Session check |
|---|---|---|---|
| `discount-business` | none | (self-login) | `self`: always live; its dump logs in headless (SME login page) |
| `discount-mortgage` | none | (self-login) | `self`: always live; its dump logs in headless |
| `discount` | none | (self-login) | `self`: always live; its dump logs in headless |
| `leumi` | 9224 | leumi | `check_sessions.sh leumi` |
| `cal` | 9225 | cal | `check_sessions.sh cal` |
| `amex` | none | (self-login) | `self`: `scrapers/amex/scrape.mjs` logs in headless from `.env` |
| `max` | — | — | self: `scrapers/max/scrape.mjs` logs in headless from `.env` |
| `harel` | 9227 (only to log in) | harel | `headless`: `scrapers/harel/scrape.mjs --check` reuses the profile's login; Chrome opens only when it is dead |
| `more` | 9228 | more | `check_sessions.sh more` |
| `analyst` | 9229 | analyst | `check_sessions.sh analyst` |

Harel cannot log in by itself (ID + phone + a one-time code, never automated), so it uses
check mode `headless`: `scrapers/harel/scrape.mjs` reuses the login the human left in
`~/.chrome-cdp-harel`, connecting over CDP when that Chrome is open on 9227 and otherwise
running the same Google Chrome binary headless on the profile. Only when `--check` says
LOGGED_OUT does the preflight open the visible window for the normal login notification.
A Harel-only run started from the app (`POST /api/sync/harel/login`, workflow id
`finance-sync-login-harel`) logs in instead: status `waiting_for_otp`, the `submit_otp(source, code)`
signal relays the code typed on `/syncs` through `deliver_otp` to the waiting `scrape_login`. The
code is in that workflow's Temporal history (single-use, minutes-long, local dev server).

No Discount source needs Chrome any more. Business, mortgage and checking
(`scrapers/discount/scrape-business.mjs`, `scrape-mortgage.mjs`, `scrape.mjs`, sharing
`lib.mjs`) log in headless from `.env` (check mode `self`, always "live" in the
preflight). Business logs in through the SME login page (`LOGIN_PAGE_SME`, ID + password
only): a personal session cannot open the business2 app (the server logs it out). All
three share one self-login group, so a refused login surfaces as `needs_login` and the
remaining ones are skipped rather than retrying the same credentials. Order stays
**business → mortgage → checking**; each headless run is its own fresh session, so the
old "the SME app rebinds the shared Chrome session" ordering problem no longer exists. Leumi runs `dump.sh` and then
`dump-loans.sh`. App-tab matching comes from `refresh-all/scripts/app_tab_index.py`
(loaded, not copied); a `discount-business` entry was added to it.

### Session checks ("live" / "dead" / "unknown")

Nothing here navigates a bank tab. `unknown` (no tab on the app, page unreadable,
check could not run, Chrome was closed) is **never** treated as dead: the source is
scraped anyway and the dump script's own stub guard is the backstop; the result
detail says `session unverified`. A source is only `dead` on a positive signal:
AMEX's `LOGGED_OUT` verdict, `check_sessions.sh` reporting `NEEDS LOGIN`, or the
bank's login page open in its window with nothing on the app.

`check_sessions.sh` today can only answer live or unknown (its `DEAD` branch is
unreachable), so for everything except AMEX a lapsed session usually shows up as
`unknown` and is caught at scrape time instead (`SessionExpired`, below).

## Workflow

`FinanceSyncWorkflow.run(sources: list[str] | None = None)`; `None` is every source.

1. **Preflight.** `ensure_chrome(source)` (launches the window if closed, makes sure
   a tab exists, attaches playwright-cli where the dump needs it) then
   `check_session(source)` for every requested source, before anything is scraped.
2. **Grouped login.** If any are dead: **one** notification listing them by login
   group, then wait up to 15m for `session_refreshed`. After the signal the dead
   sources are re-checked (only the ones named, if `resume.py` got names). Sources
   still dead are skipped with status `needs_login`; this is not an error.
3. **Scrape.** Live and unknown sources one at a time in registry order. `scrape` then
   `validate_dump`. One failing source never stops the others. If a session expires
   mid-scrape, the rest of that login group is skipped as `needs_login` instead of
   hammering the bank with a dead login.
4. **Validation gate.** `validate_dump(source)` runs `poetry run python data/validate.py dump
   <source>` when that file exists (exit 0 = good; non-zero rejects, with the output in
   the result detail) and passes while the file doesn't exist yet. A rejected source
   has status `rejected` and does not count as scraped.
5. **Finish.** If at least one source scraped: digest once, publish once. Publishing is
   withheld when any dump was rejected (the rejected files are already on disk and the
   digest reads them). One summary notification.

Result: `{source: {"status": ..., "detail": ...}}` plus `"_finish": {digest, published}`
when the finish ran. Statuses: `ok`, `needs_login`, `failed`, `rejected`. The `status`
query returns `{"phase": ..., "sources": {source: {status, detail}}}` while it runs.

A scrape failure is never retried (`SessionExpired`, `ScrapeFailed`): the dump scripts
keep the previous dump intact, and "live but failing" means the endpoint moved (see the
source's refresh skill triage table). `AmexSyncWorkflow` still exists and is just
`FinanceSyncWorkflow(["amex"])`.

The scheduled workflow decides what to scrape with `data/freshness.py`
`due_sources(now)` (per-source freshness targets, see CLAUDE.md "Freshness
targets"), rather than hard-coding the source list. Sources with no target
(RiseUp) are never returned.

### LedgerRebuildWorkflow (debounced rebuild after ledger edits)

Not scheduled: the ledger API (`api/`) signal-with-starts it on every transaction edit
(`edited` signal, workflow id `ledger-rebuild`, task queue `finance-sync`). Edits only
change `transaction_overrides`, so the rebuild is the digest chain run with
`digest.py --no-normalize` (the `digest` activity's `normalize=False`), then `publish_data`
(which still respects `SYNC_PUBLISH`).

- **Debounce.** Waits until 20 s pass with no new `edited` signal, so a burst of edits is
  one rebuild. Signals that land during a run queue exactly one more pass.
- **Idle out.** After 10 min with no signals it returns, so the next signal-with-start
  starts a fresh run. It also continues-as-new after 5 passes to keep history small.
- **Status.** Query `status` -> `{"state": "idle|pending|running", "last_published_at":
  iso|null, "last_error": str|null}`. A failed pass sets `last_error` and returns to
  idle; the workflow never crashes on an activity failure (digest: 2 attempts, publish: 3).
- **Overrides.** `run()` takes an optional `opts` dict (`debounce_seconds`,
  `idle_seconds`, `max_passes`) so tests can shorten the timers; the API passes none.
- **Digest lock.** The `digest` activity holds an exclusive `flock` on
  `data/digested/.lock` for the whole chain, so this workflow and `FinanceSyncWorkflow`
  never write `data/digested/` at once; the second waits (heartbeating) for the first.
  The kernel releases it if the worker dies. The file is covered by the `data/digested/`
  gitignore.
- **Deploying.** The worker must be restarted to pick the new workflow up:
  `launchctl kickstart -k gui/$(id -u)/me.yarinsa.finance-worker`.

## Layout

- `sources.py` the registry (one entry per source, order, login groups)
- `activities.py` subprocess wrappers (`ensure_chrome`, `check_session`, `scrape`, `validate_dump`, `digest`, `publish_data`, `notify`)
- `workflows.py` `FinanceSyncWorkflow` (query `status`, signal `session_refreshed`), `AmexSyncWorkflow`
- `worker.py` task queue `finance-sync`; `schedule.py`; `resume.py`
- `launchd/` worker plist template; `install.sh` / `uninstall.sh`

## Start / stop

```bash
sync/install.sh      # poetry install --with sync, Temporal container, worker launchd agent, schedule
sync/uninstall.sh    # unload worker, stop Temporal container (keeps ~/.temporal/finance.db)
docker compose up -d --wait   # Temporal (+ Postgres) alone, from the repo root
```

Temporal runs in Docker Compose (the `temporal` service); its history stays in
`~/.temporal/finance.db`, bind-mounted into the container. The worker stays a
launchd agent on the Mac (it needs Chrome, osascript and aws). Set Docker
Desktop to start at login, otherwise the scheduled runs have no server.

Temporal UI: http://localhost:8233 (namespace `default`, task queue `finance-sync`).

```bash
poetry run python sync/schedule.py                      # create/update the schedule (every source)
poetry run python sync/schedule.py --sources amex,cal   # ...only these
poetry run python sync/schedule.py --trigger            # run now
poetry run python sync/schedule.py --pause              # / --unpause
```

The schedule id is `finance-sync` (workflow `FinanceSyncWorkflow`, daily 06:20 and 22:00
Asia/Jerusalem). It replaces the old AMEX-only `amex-sync` schedule, which
`schedule.py` deletes when it creates or updates `finance-sync` so the two never both
fire. Re-run `schedule.py` once after upgrading.

Publishing to S3 only happens when `SYNC_PUBLISH=1` (set in the worker plist).
Without it `publish_data` returns `skipped`.

## Live status on the dashboard

Every status change of every source runs the `publish_status` activity, once **per
source**: `checking_session -> scraping -> validating -> digesting -> publishing ->
done` (5 steps), or `waiting_for_login` / `needs_login` / `rejected` / `failed`.
`digesting` and `publishing` are reported on every source that scraped. Sources that
are connected while others wait for a login show "בתור לסנכרון" (queued). When a
dump is `rejected` the other sources still finish `done`, with a note that publishing
was withheld. It writes `data/digested/sync-status.json` and, with
`SYNC_PUBLISH=1`, copies it to `s3://<bucket>/data/sync-status.json` (bucket from
`$BUCKET` or `terraform output`). Per source it holds `status`, a short Hebrew
`message`, `step`/`total_steps`, workflow/run ids, `started_at`, `updated_at`,
`last_success_at` (advances only on `done`) and a one-line `error`. Status only: no
secrets or account data.

Each update is also upserted (merged entry, per source) into the Postgres table
`sync_status` using the owner `DATABASE_URL` (env or `.env`, 3 s connect timeout); a trigger
`pg_notify('sync_status', source)` wakes the API, which streams it to the app over SSE at
`/api/sync/events`. Order: local JSON, then Postgres, then S3. No `DATABASE_URL` skips it
silently; a DB error only logs a warning.

Publishing is best-effort (one attempt, never raises), so a missing bucket or
network blip never fails a sync. `deploy.sh --data-only` does not upload or
delete this file.

The app polls it every 5s while a run is active and every 60s otherwise:
`/syncs` shows a live card with a progress bar, the header dot pulses while
running and turns red on `waiting_for_login` / `needs_login` / `rejected` / `failed`, and
the home "לטיפול" list gets a "log in to <source>" item per source that needs one. A running state that hasn't been
updated for 15 minutes shows as "לא ידוע" (unknown): the worker probably died.

## Session expired

You get one notification listing every dead login, grouped, e.g. "amex
(profile ~/.chrome-cdp-amex), harel (profile ~/.chrome-cdp-harel)". Log in in each of those Chrome windows, then:

```bash
poetry run python sync/resume.py                     # re-check every dead source
poetry run python sync/resume.py discount amex       # re-check only these (a source name or a login group)
```

This signals every running sync workflow. After 15m without a signal, or for sources
still dead on the re-check, the status is `needs_login` and nothing is scraped for them.

## Logs

Worker: `~/Library/Logs/finance-sync/worker.log` and `.err.log`.
Temporal: `docker compose logs temporal`.
Per-run detail (command output tails) is in the Temporal UI event history.

## Tests

`poetry run pytest sync/tests` (time-skipping Temporal test server, mocked
activities; nothing touches Chrome or a bank).
