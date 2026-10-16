from activities import parse_verdict

# Real output format of .claude/skills/amex-refresh/scripts/check_session.sh
LIVE = """cookie authentication_shared: 561 chars
cookie JSESSIONID: 36 chars
IsLoggedIn status: 200
IsLoggedIn body: {"isLoggedIn":true}
VERDICT: LIVE

Session is LIVE. If a scrape still returns login-shell HTML, the ENDPOINT
HAS MOVED — do NOT ask the user to log in again. See SKILL.md triage table.
"""

LOGGED_OUT = """cookie authentication_shared: MISSING
cookie JSESSIONID: MISSING
IsLoggedIn status: 200
IsLoggedIn body: <!DOCTYPE html><html>
VERDICT: LOGGED_OUT

Session looks LOGGED OUT. Ask the USER to log in in the visible window.
"""


def test_live():
    assert parse_verdict(LIVE) is True


def test_logged_out():
    assert parse_verdict(LOGGED_OUT) is False


def test_no_verdict_is_not_logged_out():
    # playwright-cli not attached: check_session.sh swallows it and exits 1 with
    # no VERDICT. That is an infra error, not a reason to page the human.
    assert parse_verdict("Error: session 'amex' not found\n\nSession looks LOGGED OUT.") is None


def test_help_text_mentioning_verdict_midline_is_ignored():
    assert parse_verdict("see VERDICT: LIVE in docs") is None
