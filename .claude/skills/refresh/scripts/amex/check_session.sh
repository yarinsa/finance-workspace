#!/usr/bin/env bash
#
# Is the AMEX session actually live?
#
# THIS EXISTS BECAUSE "I got HTML instead of JSON" IS NOT A LIVENESS TEST.
# A stale/moved endpoint and an expired session produce byte-identical symptoms:
# HTTP 200 + ~3.6KB of login-shell HTML. On 2026-08-09 that ambiguity cost the
# user three unnecessary logins while the session was live the whole time.
#
# Two independent signals, neither of which can be faked by a wrong URL:
#   1. GET /IsLoggedIn  -> 200 + real JSON when the session is live.
#   2. The Playwright context cookie jar contains the HttpOnly auth cookies
#      `authentication_shared` (~560 chars) + `JSESSIONID` (36 chars) on
#      domain .americanexpress.co.il. These are HttpOnly, so they are INVISIBLE
#      to document.cookie and are NOT sent by a fetch() inside page.evaluate.
#
# Exit 0 = session live. Exit 1 = genuinely logged out (ask the USER to log in).
#
# Usage: check_session.sh [SESSION]
set -euo pipefail

SESSION="${1:-amex}"
TMP_JS="$(mktemp /tmp/amex-live-XXXX.js)"
trap 'rm -f "$TMP_JS"' EXIT

# NOTE: the snippet must be a BARE async function expression. No module.exports
# wrapper, no top-level statements, no require(). console.log does not reliably
# surface — RETURN a string instead.
cat > "$TMP_JS" <<'EOF'
async (page) => {
  const out = [];

  // Signal 1: the HttpOnly auth cookies, read from the context jar (NOT document.cookie).
  const jar = await page.context().cookies();
  const auth = jar.find(c => c.name === 'authentication_shared');
  const jsid = jar.find(c => c.name === 'JSESSIONID');
  out.push('cookie authentication_shared: ' + (auth ? auth.value.length + ' chars' : 'MISSING'));
  out.push('cookie JSESSIONID: ' + (jsid ? jsid.value.length + ' chars' : 'MISSING'));

  // Signal 2: the dedicated liveness endpoint.
  let status = 0, body = '';
  try {
    const r = await page.request.get('https://web.americanexpress.co.il/IsLoggedIn');
    status = r.status();
    body = (await r.text()).slice(0, 200);
  } catch (e) {
    body = 'request failed: ' + e.message;
  }
  const isHtml = /^\s*<(!doctype|html)/i.test(body);
  out.push('IsLoggedIn status: ' + status);
  out.push('IsLoggedIn body: ' + body.replace(/\s+/g, ' '));

  const live = !!(auth && jsid) && status === 200 && !isHtml;
  out.push('VERDICT: ' + (live ? 'LIVE' : 'LOGGED_OUT'));
  return out.join('\n');
}
EOF

RESULT="$(playwright-cli -s="$SESSION" --raw run-code --filename="$TMP_JS" 2>&1 || true)"
echo "$RESULT"

if grep -q 'VERDICT: LIVE' <<<"$RESULT"; then
  echo
  echo "Session is LIVE. If a scrape still returns login-shell HTML, the ENDPOINT"
  echo "HAS MOVED — do NOT ask the user to log in again. See SKILL.md triage table."
  exit 0
fi

echo
echo "Session looks LOGGED OUT. Ask the USER to log in in the visible window."
exit 1
