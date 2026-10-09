#!/usr/bin/env bash
#
# Liveness-check every scrape source, up front, in one pass.
#
# The refresh pain is not typing passwords — Chrome profiles persist logins.
# It is that sessions expire silently, and you only discover it one source at a
# time, mid-refresh. This checks them all first so every needed login can be
# done in a single sitting.
#
# Read-only, and strictly so: never logs in, never types credentials, never
# scrapes — and never NAVIGATES. An earlier version drove each tab to the
# source's homepage "to judge honestly" and thereby destroyed the very sessions
# it was checking (see the comment at the eval step). It now judges only what is
# already open, via CDP metadata. If that is not enough to decide, the answer is
# UNKNOWN, not NEEDS LOGIN.
#
# Usage:
#   .claude/skills/refresh-all/scripts/check_sessions.sh
#   .claude/skills/refresh-all/scripts/check_sessions.sh leumi cal
#
# Exit: 0 = all live, 1 = at least one needs a login.
set -uo pipefail

# source | cdp port | playwright session | logged-in signal (JS -> truthy string)
# The signal differs per bank: a URL fragment, a page title, or a live token.
SOURCES=(
  "riseup|9222|riseup|location.href.includes('/web/') && !location.href.includes('login')"
  "discount|9223|discount|location.href.includes('apollo/retail3')"
  "leumi|9224|leumi|location.href.includes('#/hpsummary')"
  # cal's token is origin-scoped to digital-web.cal-online.co.il — read from any
  # other host sessionStorage is simply empty, which is NOT a logged-out signal.
  # Gate it on the hostname so an off-origin tab falls through to the URL check.
  "cal|9225|cal|location.hostname.includes('cal-online.co.il') && !!(JSON.parse(sessionStorage.getItem('auth-module')||'{}').auth||{}).calConnectToken"
  "amex|9226|amex|document.title.includes('אזור אישי')"
  "harel|9227|harel|location.href.includes('client-view.aspx')"
  "more|9228|more|location.hostname==='my-account.more.co.il' && !!sessionStorage.getItem('accountData')"
)

# Login URL per source — used only to LAUNCH a window for the user, never to log in.
declare -A LOGIN_URL=(
  [riseup]="https://input.riseup.co.il/web/home/current"
  [discount]="https://start.telebank.co.il/apollo/retail3/"
  [leumi]="https://hb2.bankleumi.co.il/"
  [cal]="https://www.cal-online.co.il/"
  [amex]="https://he.americanexpress.co.il/"
  [harel]="https://www.harel-group.co.il/"
  [more]="https://my-account.more.co.il/personalarea/dashboard"
)

WANT=("$@")
want_this() {
  [ ${#WANT[@]} -eq 0 ] && return 0
  for w in "${WANT[@]}"; do [ "$w" = "$1" ] && return 0; done
  return 1
}


needs_login=()   # chrome IS up, but the session is dead -> user must log in
unknown=()       # chrome up but page unreachable (detached session / no tab)
not_running=()   # chrome is not up at all -> just needs launching
live=()
printf '%-12s %-6s %s\n' "SOURCE" "PORT" "STATUS"
printf '%s\n' "----------------------------------------------------"

for row in "${SOURCES[@]}"; do
  IFS='|' read -r name port session signal <<< "$row"
  want_this "$name" || continue

  # 1. Is Chrome even up on this port? A closed browser is NOT an expired
  #    session — the profile still holds the cookies, so launching it may well
  #    come back already logged in. Keep the two cases distinct.
  if ! curl -s --max-time 3 "http://127.0.0.1:$port/json/version" | grep -q Browser; then
    printf '%-12s %-6s %s\n' "$name" "$port" "chrome not running"
    not_running+=("$name")
    continue
  fi

  # 2. Attach (idempotent) and evaluate the source's logged-in signal.
  #    127.0.0.1 not localhost — playwright-cli resolves localhost to IPv6.
  #
  #    CRITICAL: distinguish "the signal says logged out" from "the signal never
  #    ran". If attach fails the eval returns nothing, and treating that as DEAD
  #    sends the user hunting for a login they don't need. The signal must
  #    explicitly answer LIVE or DEAD; anything else is UNKNOWN.
  playwright-cli -s="$session" attach --cdp="http://127.0.0.1:$port" >/dev/null 2>&1

  #    NEVER navigate. This check used to `goto` the source's homepage before
  #    judging, and that is what made a "read-only" script cost five logins in
  #    one night: these SPAs hold their auth in sessionStorage / in memory
  #    (cal's calConnectToken, Leumi's live SessionID), so landing on another
  #    origin loses it outright — and for the banks whose URL is the pre-auth
  #    gateway, re-entering it terminates the session server-side (on Discount's
  #    single-session backend a second gateway tab triggers the documented
  #    `actionRequired: stepup` rebind).
  #
  #    So judge the tab that is ALREADY on the app, found by a pure metadata
  #    read of /json/list — no navigation, no new tab, no closed tab. If no such
  #    tab exists we say UNKNOWN ("open one and re-run"), never DEAD.
  idx="$(curl -s --max-time 5 "http://127.0.0.1:$port/json/list" \
          | SRC="$name" python3 "$(dirname "$0")/app_tab_index.py" 2>/dev/null)"
  [ -n "$idx" ] && playwright-cli -s="$session" tab-select "$idx" >/dev/null 2>&1

  #    Evaluate the source's own logged-in signal in the page. A truthy signal is
  #    the strongest evidence we can get; a falsy one only means "not proven
  #    here", because we may be reading the wrong tab (or, for cal, the wrong
  #    origin). So falsy is NOT DEAD — it falls through to the URL check below.
  result="$(playwright-cli -s="$session" --raw eval "(()=>{try{return ($signal)?'LIVE':''}catch(e){return ''}})()" 2>/dev/null | tail -1 | tr -d '"')"

  #    Fallback: playwright-cli's attach is flaky (it can report success but
  #    leave the session unusable), and the signal above is deliberately
  #    inconclusive when falsy. CDP's /json/list needs no attach at all, so fall
  #    back to judging by the open tabs' URL/title — the same matching table,
  #    defined once in app_tab_index.py. Coarser than the JS signal (it cannot
  #    read sessionStorage) but enough to tell an app page from a login page.
  if [ "$result" != "LIVE" ]; then
    result="$(curl -s --max-time 5 "http://127.0.0.1:$port/json/list" \
                | SRC="$name" python3 "$(dirname "$0")/app_tab_index.py" --verdict 2>/dev/null)"
    result="${result:-UNKNOWN}"
  fi

  case "$result" in
    LIVE)
      printf '%-12s %-6s %s\n' "$name" "$port" "live"
      live+=("$name")
      ;;
    DEAD)
      printf '%-12s %-6s %s\n' "$name" "$port" "NEEDS LOGIN"
      needs_login+=("$name")
      ;;
    *)
      # Chrome is up but nothing here proves the session either way: no tab is
      # on this source's app, or the page could not be read. Emphatically NOT a
      # login problem — saying "NEEDS LOGIN" here is the crying-wolf that makes
      # the user re-authenticate for nothing.
      printf '%-12s %-6s %s\n' "$name" "$port" "unknown (no tab on this app)"
      unknown+=("$name")
      ;;
  esac
done

printf '%s\n' "----------------------------------------------------"
echo "live: ${#live[@]}   not running: ${#not_running[@]}   needs login: ${#needs_login[@]}   unknown: ${#unknown[@]}"

port_of() {
  for row in "${SOURCES[@]}"; do
    IFS='|' read -r name port _ _ <<< "$row"
    [ "$name" = "$1" ] && { printf '%s' "$port"; return; }
  done
}

launch_one() {
  local name="$1" port; port="$(port_of "$name")"
  /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --remote-debugging-port="$port" \
    --user-data-dir="$HOME/.chrome-cdp-$name" \
    --no-first-run --no-default-browser-check --new-window \
    "${LOGIN_URL[$name]}" >"/tmp/chrome-cdp-$name.log" 2>&1 &
  for _ in $(seq 1 10); do
    sleep 1
    curl -s --max-time 2 "http://127.0.0.1:$port/json/version" | grep -q Browser && return 0
  done
  return 1
}

if [ ${#not_running[@]} -gt 0 ]; then
  echo
  if [ "${LAUNCH:-0}" = "1" ]; then
    echo "Launching Chrome for: ${not_running[*]}"
    for n in "${not_running[@]}"; do
      printf '  %-10s ' "$n"
      if launch_one "$n"; then echo "launched (re-run to re-check the session)"; else echo "FAILED to bind port"; fi
    done
  else
    echo "Chrome is not running for: ${not_running[*]}"
    echo "The profile still holds the cookies, so these may come back already"
    echo "logged in. Launch them with:  LAUNCH=1 .claude/skills/refresh-all/scripts/check_sessions.sh"
  fi
fi

if [ ${#needs_login[@]} -gt 0 ]; then
  echo
  echo "SESSION EXPIRED — you must log in yourself (never automated):"
  for n in "${needs_login[@]}"; do
    echo "  $n  -> window is open on profile ~/.chrome-cdp-$n (port $(port_of "$n"))"
  done
fi

if [ ${#unknown[@]} -gt 0 ]; then
  echo
  echo "Could not judge the session for: ${unknown[*]}"
  echo "Chrome is running, but no open tab is on the source's app (or the page"
  echo "could not be read). This check never navigates — navigating is what kills"
  echo "these sessions — so it cannot go look for itself."
  echo "This is NOT an expired login. Open a tab on the source yourself and re-run."
fi

[ ${#needs_login[@]} -eq 0 ] && [ ${#not_running[@]} -eq 0 ] && [ ${#unknown[@]} -eq 0 ] && exit 0
exit 1
