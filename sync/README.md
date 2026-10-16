# Automated sync (Temporal) — POC

> **Status: proof of concept.** Covers AMEX only, runs on a local Temporal dev
> server (no persistence guarantees), and is not yet wired into `refresh-all`.
> Keep it as a reference for automating the other sources; don't rely on it as
> the only refresh path.

Runs the AMEX refresh daily at 07:30 Asia/Jerusalem on this Mac:
`ensure_chrome -> check session -> scrape -> digest -> publish`.

**The automation never logs in.** If the session is dead it sends a macOS
notification and waits up to 12h for you. No credentials, OTPs, Keychain reads
or keep-alive pings.

## Layout

- `activities.py` subprocess wrappers (amex-refresh scripts, `data/*.py`, `infra/deploy.sh --data-only`, osascript)
- `workflows.py` `AmexSyncWorkflow` (query `status`, signal `session_refreshed`)
- `worker.py` task queue `finance-sync`; `schedule.py` schedule `amex-sync`; `resume.py`
- `launchd/` worker plist template; `install.sh` / `uninstall.sh`

## Start / stop

```bash
sync/install.sh      # venv deps, Temporal container, worker launchd agent, schedule
sync/uninstall.sh    # unload worker, stop Temporal container (keeps ~/.temporal/finance.db)
docker compose up -d --wait   # Temporal (+ Postgres) alone, from the repo root
```

Temporal runs in Docker Compose (the `temporal` service); its history stays in
`~/.temporal/finance.db`, bind-mounted into the container. The worker stays a
launchd agent on the Mac (it needs Chrome, osascript and aws). Set Docker
Desktop to start at login, otherwise the 07:30 run has no server.

Temporal UI: http://localhost:8233 (namespace `default`, task queue `finance-sync`).

```bash
.venv/bin/python sync/schedule.py --trigger   # run now
.venv/bin/python sync/schedule.py --pause     # / --unpause
```

Publishing to S3 only happens when `SYNC_PUBLISH=1` (set in the worker plist).
Without it `publish_data` returns `skipped`.

## Live status on the dashboard

Every status change (`checking_session -> scraping -> digesting -> publishing ->
done`, or `waiting_for_login` / `needs_login` / `failed`) runs the
`publish_status` activity. It writes `data/digested/sync-status.json` and, with
`SYNC_PUBLISH=1`, copies it to `s3://<bucket>/data/sync-status.json` (bucket from
`$BUCKET` or `terraform output`). Per source it holds `status`, a short Hebrew
`message`, `step`/`total_steps`, workflow/run ids, `started_at`, `updated_at`,
`last_success_at` and a one-line `error`. Status only: no secrets or account data.

Publishing is best-effort (one attempt, never raises), so a missing bucket or
network blip never fails a sync. `deploy.sh --data-only` does not upload or
delete this file.

The app polls it every 5s while a run is active and every 60s otherwise:
`/syncs` shows a live card with a progress bar, the header dot pulses while
running and turns red on `waiting_for_login` / `needs_login` / `failed`, and the
home "לטיפול" list gets a "log in to AMEX" item. A running state that hasn't been
updated for 15 minutes shows as "לא ידוע" (unknown): the worker probably died.

## Session expired

You get a notification: "AMEX session expired - log in in the AMEX Chrome window".
Log in in that Chrome window (profile `~/.chrome-cdp-amex`, CDP port 9226), then:

```bash
python3 sync/resume.py
```

This signals every running `AmexSyncWorkflow`; it re-checks the session and
continues. After 12h without a signal, or if the session is still dead, the run
ends with status `needs_login` and scrapes nothing. A scrape failure is never
retried (`SessionExpired`, `ScrapeFailed`): `dump.sh` keeps the previous dump
intact, and a "live but failing" result means the endpoint moved (see the
amex-refresh skill triage table).

## Logs

Worker: `~/Library/Logs/finance-sync/worker.log` and `.err.log`.
Temporal: `docker compose logs temporal`.
Per-run detail (command output tails) is in the Temporal UI event history.

## Tests

`.venv/bin/python -m pytest sync/tests` (time-skipping Temporal test server, mocked activities).
