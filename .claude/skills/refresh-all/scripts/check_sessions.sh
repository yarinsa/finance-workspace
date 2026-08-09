#!/usr/bin/env bash
#
# Liveness-check every scrape source, up front, in one pass.
#
# The refresh pain is not typing passwords — Chrome profiles persist logins.
# It is that sessions expire silently, and you only discover it one source at a
# time, mid-refresh. This checks them all first so every needed login can be
# done in a single sitting.
#
# Read-only: never logs in, never types credentials, never scrapes. It only
# asks "is this session still alive?" and reports.
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
  "cal|9225|cal|!!(JSON.parse(sessionStorage.getItem('auth-module')||'{}').auth||{}).calConnectToken"
  "amex|9226|amex|document.title.includes('אזור אישי')"
  "harel|9227|harel|location.href.includes('client-view.aspx')"
)

# Login URL per source — used only to LAUNCH a window for the user, never to log in.
declare -A LOGIN_URL=(
  [riseup]="https://input.riseup.co.il/web/home/current"
  [discount]="https://start.telebank.co.il/apollo/retail3/"
  [leumi]="https://hb2.bankleumi.co.il/"
  [cal]="https://www.cal-online.co.il/"
  [amex]="https://he.americanexpress.co.il/"
  [harel]="https://www.harel-group.co.il/"
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
  playwright-cli -s="$session" tab-select 0 >/dev/null 2>&1

  #    Navigate to the source's own page before judging. The tab may be sitting
  #    on something unrelated (the user browsed elsewhere), and reading
  #    location.href then would report a perfectly good session as logged out.
  #    Landing on the app and getting bounced to a login page is the real signal.
  if [ "${NO_NAV:-0}" != "1" ]; then
    if ! playwright-cli -s="$session" goto "${LOGIN_URL[$name]}" >/dev/null 2>&1; then
      # playwright-cli unavailable for this session — drive the tab over plain
      # CDP instead (PUT /json/new works without any attach).
      curl -s --max-time 5 -X PUT \
        "http://127.0.0.1:$port/json/new?${LOGIN_URL[$name]}" >/dev/null 2>&1
    fi
    sleep 5
  fi

  result="$(playwright-cli -s="$session" --raw eval "(()=>{try{return ($signal)?'LIVE':'DEAD'}catch(e){return 'DEAD'}})()" 2>/dev/null | tail -1 | tr -d '"')"

  #    Fallback: playwright-cli's attach is flaky (it can report success but
  #    leave the session unusable). CDP's /json/list needs no attach at all, so
  #    fall back to judging by the open tab's URL/title. Coarser than the JS
  #    signal — it cannot read sessionStorage — but enough to tell a logged-in
  #    app page from a login page, which is all this check has to decide.
  if [ "$result" != "LIVE" ] && [ "$result" != "DEAD" ]; then
    result="$(curl -s --max-time 5 "http://127.0.0.1:$port/json/list" | SRC="$name" python3 -c '
import json, os, sys
src = os.environ["SRC"]
# A page counts as logged-in when its url/title matches the app, and does NOT
# look like a login/OTP screen.
APP = {
  "riseup":   (("input.riseup.co.il/web/",), ()),
  "discount": (("apollo/retail3",), ()),
  "leumi":    (("#/hpsummary",), ()),
  "cal":      (("digital-web.cal-online.co.il/dashboard",), ()),
  "amex":     (("web.americanexpress.co.il",), ("אזור אישי",)),
  "harel":    (("client-view.aspx",), ("הראל שלי",)),
}
LOGIN_HINTS = ("login", "signin", "gate-keeper", "otp")
try:
    tabs = [t for t in json.load(sys.stdin) if t.get("type") == "page"]
except Exception:
    print("UNKNOWN"); raise SystemExit
url_pats, title_pats = APP.get(src, ((), ()))
for t in tabs:
    url, title = t.get("url", ""), t.get("title", "")
    if any(h in url.lower() for h in LOGIN_HINTS):
        continue
    if any(p in url for p in url_pats) or any(p in title for p in title_pats):
        print("LIVE"); raise SystemExit
print("DEAD" if tabs else "UNKNOWN")
' 2>/dev/null)"
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
      # Chrome is up but we could not talk to the page (detached session, no
      # tab, playwright-cli error). Not a login problem — report it as such.
      printf '%-12s %-6s %s\n' "$name" "$port" "unknown (attach failed)"
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
  echo "Could not read the page for: ${unknown[*]}"
  echo "Chrome is running, so this is usually a detached playwright-cli session"
  echo "or a closed tab — not an expired login. Open a tab on the source and re-run."
fi

[ ${#needs_login[@]} -eq 0 ] && [ ${#not_running[@]} -eq 0 ] && [ ${#unknown[@]} -eq 0 ] && exit 0
exit 1
