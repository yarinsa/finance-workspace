# Refresh-all automation notes

Written after observing a live `refresh-all` run (2026-09-04). Originally
analysis-only; a follow-up pass on the same date fixed the three highest-value
findings in code/docs (FIX 1, FIX 2, FIX 3 below) — everything else in this
memo remains a proposal, not yet implemented. Every claim is checked against
the actual source, cited by file:line.

**Hard constraint carried into every proposal below: the user logs in, always.
No proposal here has an agent touch credentials, OTP, or card numbers.**
Anything that would require that is explicitly marked OUT OF SCOPE and not
proposed.

## Fixed 2026-09-04 (highest-value findings, now resolved)

### FIX 1 — AMEX scraper/normalizer drift (fixed; the hardest of the three to catch)

**This is the most important finding in this memo, and the one most likely to
recur elsewhere**, because unlike a stub it produces **no size anomaly to
notice** — the run reports every endpoint green and the ledger simply goes
stale silently.

`data/amex/normalize.py` reads only `raw/cardList.json` and
`raw/transactions_<suffix>_<month>.json` (per-card monthly pulls) — see its
glob at `data/amex/normalize.py:64`. But `.claude/skills/amex-refresh/scripts/dump.sh`
(pre-fix) only ever captured 5 SPA-bootstrap endpoints (cardList,
transactionsList, initContent, personalComponents, campaign) — it never wrote
a single `transactions_*` file. `transactionsList.json` is the account-wide
aggregate view, not the per-card file `normalize.py` actually globs. Every
refresh since the 2026-08-09 re-platforming reported all-green while the
ledger silently kept whatever `transactions_*` files existed from before that
date.

**The trap:** a stub is *loud* — a 350B file where a 17K file should be is
visible in `ls -lh`. This bug was *silent* — the bootstrap capture genuinely
succeeded, wrote real JSON, and the run looked completely healthy. The only
way to have caught it was reading `normalize.py`'s glob against what `dump.sh`
actually produces, which nobody had done since the endpoints moved.

**Fix:** `dump.sh` now fetches the per-card files itself, for every card
`cardList.json` marks `isActive`, for the current + previous billing month,
via `POST .../GetTransactionsList` with an explicit `card4Number` /
`billingMonth` / `companyCode` / `isPartner` body — issued with
`page.request.post()` (not `page.evaluate()+fetch()`), which does carry the
context's HttpOnly cookies. `amex-refresh/SKILL.md` previously claimed
`page.request.post()` "was also tried and also returned login HTML" — that
note was wrong (never cleanly isolated from the dead-StatusPage-endpoint
confusion of the same period) and has been corrected in place.
Filenames match `normalize.py`'s glob exactly:
`transactions_<suffix>_<YYYYMM>.json`. See
`.claude/skills/amex-refresh/scripts/dump.sh` (Step 3) and
`.claude/skills/amex-refresh/SKILL.md` ("Per-card transaction files" section).

**Lesson for future sources:** whenever a scraper endpoint list changes,
diff it against the corresponding `normalize.py`'s glob/read list before
declaring the refresh healthy — green dump.sh output proves nothing about
whether the file the normalizer actually reads was written.

### FIX 2 — stub guard now enforced in all seven sources (fixed)

Previously only `amex-refresh/scripts/dump.sh` validated a response
(login-shell HTML / JSON validity) before writing. The other six sources
(discount-account, discount-mortgage, discount-business, leumi, harel, cal)
shared a `parse_and_write()` that wrote unconditionally, only printing a
`<-- non-200` warning — which does nothing against the real failure mode of
HTTP 200 with a few hundred bytes of error JSON.

**Fix:** each of the six `dump.sh` scripts' `parse_and_write()` now requires,
before overwriting an existing file: valid JSON, not login-shell HTML, and no
known auth-error marker (`actionRequired: stepup`, `SME - קלט לא תקין`). A
legitimately small response (`{}`/`[]`) is not rejected — only known failure
signatures are. On failure: no write, a clear error line, previous file
preserved, non-zero exit. Kept each script self-contained (no shared library
was introduced — none existed before, and none of these scripts source a
common file) per the existing project convention. Verified with `bash -n` on
all six scripts plus a functional smoke test (valid-small-JSON /
login-shell-HTML / auth-error-stub / non-JSON, all four behaving correctly)
extracted straight from the real files.

### FIX 3 — refresh-all SKILL.md contradicted its own script (fixed)

`refresh-all/SKILL.md` claimed the session checker "navigates each window to
its bank in order to judge honestly." `check_sessions.sh` explicitly does
**not** navigate, and its own header comment records that an earlier version
did, and that navigation is exactly what destroyed the sessions it was
checking. The script was correct; the doc was stale and invited a future
"fix" that would reintroduce the bug. Corrected the passage in
`refresh-all/SKILL.md` to match the script and spelled out why navigating is
forbidden (SPAs hold auth in sessionStorage/in-memory; cross-origin
navigation or re-entering a bank's gateway URL loses/rebinds the session).

## Top wins still open (not yet done)

## Prioritized table

| # | Problem | Change | File(s) | Effort | Risk | Time saved/run | Status |
|---|---|---|---|---|---|---|---|
| 0 | AMEX `dump.sh` never wrote the per-card files `normalize.py` globs; no size anomaly, all-green false pass | `dump.sh` now fetches `transactions_<suffix>_<month>.json` per active card via `page.request.post()` | `amex-refresh/scripts/dump.sh`, `amex-refresh/SKILL.md` | M | low | prevents the ledger from silently going stale forever | **DONE 2026-09-04** |
| 1 | SKILL.md says the checker navigates; script explicitly does not (and says why) | Rewrite SKILL.md lines 44-47 to match script behavior | `.claude/skills/refresh-all/SKILL.md:44-47` | S | none | prevents future regression, not per-run | **DONE 2026-09-04** |
| 2 | 6/7 `dump.sh` scripts have no stub-content guard | Inlined amex's login-shell/JSON/auth-error-marker check into each script's own `parse_and_write` (no shared library — none of these scripts sourced one before) | `discount-account-refresh/scripts/dump.sh`, `discount-mortgage-refresh/scripts/dump.sh`, `discount-business-refresh/scripts/dump.sh`, `leumi-account-refresh/scripts/dump.sh`, `harel-refresh/scripts/dump.sh`, `cal-refresh/scripts/dump.sh` | M | low (additive, only tightens writes) | avoids re-scrape debugging when a stub silently lands | **DONE 2026-09-04** |
| 3 | `LAUNCH=1` → recheck is two manual invocations, no readiness wait on the *session* (only the port) | After launch, loop re-running the per-source liveness check (not just `/json/version`) until LIVE/DEAD/timeout, then print the final table once | `.claude/skills/refresh-all/scripts/check_sessions.sh:149-176` | S | low | removes 1 manual re-run per cold-start source | open |
| 4 | Discount NEEDS LOGIN discovered only after agents were spawned | Nothing to automate here without navigating (which kills sessions) — but the *reporting* step could be more emphatic: exit code 1 already signals "stop", the caller just has to actually gate on it | `refresh-all` orchestration step (agent behavior, not a script) | S (process, not code) | none | avoids the drip-feed the skill exists to prevent | open |
| 5 | Digest sanity checks (tx count "low thousands", uncategorized "~20%") are prose only, never asserted | Add a `--check` mode to `digest.py` (mirroring `detect_freeze.py --check`) that prints these two numbers and exits non-zero outside expected bands | `data/digest.py` (new function near `main()`, ~line 399) | M | low (read-only over already-written output) | turns a "did anyone eyeball this" step into a pass/fail | open |
| 6 | `mortgage_details.json` ~17K-vs-~350B stub signal is documented (SKILL.md:264-268) but not code-enforced | Covered by #2 — same guard, sized per-endpoint | `discount-mortgage-refresh/scripts/dump.sh` | (subsumed in #2) | — | — | **DONE 2026-09-04** (via #2) |
| 7 | No per-source record-count assertion after digest | `digest.py` already stamps `_source` per record (`load_entities`, digest.py:24-32); log a one-line count-per-source-per-entity table before consolidation so a source that normalized to near-zero is visible immediately, not just inferred from the total | `data/digest.py:24-32` | S | none | surfaces "cal normalized to 3 transactions" instead of "total count looks a bit low" | open |
| 8 | `data/freeze.json` staleness | `detect_freeze.py` already clears a stale freeze file when no discrepancy is detected (`main()`, lines 339-348) — this is **already handled**, not a gap. Worth noting in this memo only so it isn't "fixed" twice. | `data/detect_freeze.py:339-348` | — | — | already done | n/a |
| 9 | Duplicated `parse_and_write` boilerplate across 6 dump.sh scripts (near-identical node -e blocks) | Extract to one shared script (e.g. `.claude/skills/_shared/parse_and_write.sh`) sourced by each dump.sh, folding in the #2 stub guard at the same time | all `*/scripts/dump.sh` except amex | M | medium — touches every scraper, must preserve each source's exact status/label formatting | maintenance win, not per-run time | open — #2's guard was inlined per script instead, to avoid introducing a new cross-skill dependency in this pass |
| 10 | amex has an ad-hoc `check_session.sh` that no other source has | Not proposing to replicate broadly — amex's problem (HTML-vs-expired ambiguity) is real but source-specific (HttpOnly cookies). Note it as a **pattern** worth reaching for if another source hits the same ambiguity, not a blanket requirement. | `amex-refresh/scripts/check_session.sh` | — | — | — | n/a |

## Details

### 1. SKILL.md/script mismatch on navigation (confirmed)

`refresh-all/SKILL.md:46-47`:
> "Read-only: it never logs in and never scrapes. Note it *navigates* each
> window to its bank in order to judge honestly..."

`check_sessions.sh:10-15` (script's own header comment) says the opposite,
explicitly, with history:
> "never NAVIGATES. An earlier version drove each tab to the source's homepage
> 'to judge honestly' and thereby destroyed the very sessions it was checking
> ... It now judges only what is already open, via CDP metadata."

The script is correct and carefully engineered (`app_tab_index.py` finds an
already-open app tab by URL/title pattern, never opens or navigates one). The
SKILL.md prose is a leftover from the earlier, buggy version. This is exactly
the drift the run surfaced: riseup showed "live" because a tab happened to
already be on the app; discount/leumi/cal/amex/harel showed "unknown (no tab
on this app)" — not because sessions were dead, but because no tab was
sitting on the right page, which the script correctly refuses to interpret as
NEEDS LOGIN (`check_sessions.sh:128-136`). The fix is a doc correction, not a
behavior change — the current behavior is the right one.

### 2. Stub-content guard is inconsistent across sources (confirmed by grep)

Checked every `dump.sh`'s write path:

- **amex** (`amex-refresh/scripts/dump.sh:113-127`): explicit guard — skips
  writing on login-shell HTML (`/^\s*<(!doctype|html)/i` test) or invalid
  JSON, logs `<-- LOGIN-SHELL HTML, NOT WRITTEN` / `<-- NOT JSON, NOT WRITTEN`,
  and exits 2 if literally nothing valid was captured.
- **discount-mortgage / discount-account / discount-business / leumi / harel
  / cal** all share the same `parse_and_write()` shape (e.g.
  `discount-mortgage-refresh/scripts/dump.sh:52-67`): it always
  `fs.writeFileSync`s the body, and the only signal is a printed
  `<-- non-200` warning when `status !== "200"`. A stub that comes back **HTTP
  200 with error JSON** (documented explicitly in
  `discount-mortgage-refresh/SKILL.md:264-268`: `actionRequired: stepup` /
  `SME - קלט לא תקין` at ~350B when landed on the wrong Discount app) sails
  through this guard untouched and overwrites the last good dump.

CLAUDE.md's "Never overwrite a good dump with error stubs" rule and the ~17K
vs ~350B signal are real and well-documented, but only amex's script actually
enforces them in code. Everywhere else it's a **human must notice the file
size in `ls -lh` output** rule, which is exactly the kind of thing that gets
missed when six agents are dumping in parallel.

**Concrete fix:** factor amex's guard (size + login-shell-HTML regex + JSON
parse validity) into a small shared helper and call it from every
`parse_and_write`, or at minimum add a same-file size floor per known-good
endpoint (e.g. `mortgage_details.json` must exceed some KB threshold or the
write is skipped and the script exits non-zero with the previous file
untouched).

### 3. LAUNCH→settle→recheck loop

`check_sessions.sh:149-161`'s `launch_one()` polls up to 10x for
`/json/version` to return (Chrome's CDP endpoint being up), then returns.
That only proves the browser process is listening — it says nothing about
whether the page has actually loaded past login. The script's own output at
line 169 (`"launched (re-run to re-check the session)"`) concedes this: the
human has to manually invoke the whole script again. A tighter loop would
call the per-source liveness eval (the same block at lines 76-117) in a
bounded retry after launch, so one invocation with `LAUNCH=1` yields a final
verdict instead of "launched, please run me again."

### 4. Discount NEEDS LOGIN discovered late

This is process, not code: `check_sessions.sh` exits 1 whenever anything is
`needs_login`/`not_running`/`unknown` (`check_sessions.sh:195-196`), so the
signal to stop and collect logins before spawning scrape agents already
exists. If Discount's NEEDS LOGIN was discovered only after agents were
spawned, the orchestration step didn't gate on that exit code / didn't re-run
the checker immediately before the fan-out. No script change needed — the
fix is in how the orchestrating agent sequences step 1 (check) vs step 2
(spawn), matching what `refresh-all/SKILL.md`'s own flow already prescribes
("Wait. Do not proceed source-by-source." — line 53).

### 5. Digest sanity checks are prose-only (confirmed)

`refresh-all/SKILL.md:91-97` lists three checks to do "before reporting
success" — tx count in the low thousands, uncategorized ~20%, freeze.json
presence — but `data/digest.py` has no `--check` mode and prints only
`f"wrote {OUT / 'transactions.json'} ({len(ledger)} deduped txns)"`
(`digest.py:421`) with no threshold logic. `spending_summary()`
(`digest.py:356-396`) already computes `by_category` including an
`"uncategorized"` bucket, so the uncategorized share is one division away
from being computable and assertable — it's just not done anywhere in code
today. `detect_freeze.py --check` (referenced correctly in SKILL.md:97) is
the model to copy: report-only, exit non-zero on a bad signal, no prompts.

### 8. freeze.json staleness — already handled, no action needed

Worth flagging explicitly since it was in the brief to check: `detect_freeze.py:339-348`
already deletes a stale `freeze.json` when the current dump shows no
discrepancy (`FREEZE.unlink()`), specifically so a resolved freeze doesn't
keep depressing the forecast's committed mortgage payment. This is not a gap.

### 9. Boilerplate worth extracting

`parse_and_write()` is reimplemented near-verbatim in discount-account,
discount-mortgage, discount-business, harel, and cal's `dump.sh` (leumi's is
a close variant handling a different response envelope). All five do: parse
double-JSON-encoded `run-code --raw` output, pretty-print, write, print a
status/size/warn line. Consolidating into one sourced file would (a) cut
~15 lines × 5 files of drift risk and (b) be the natural place to land the
stub guard from #2 once, instead of six times.
