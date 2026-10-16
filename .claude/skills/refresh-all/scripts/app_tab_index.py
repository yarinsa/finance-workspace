#!/usr/bin/env python3
"""Find the open tab that is already sitting on a source's authenticated app.

check_sessions.sh must never navigate: these banking SPAs keep their auth in
sessionStorage / in memory (cal's calConnectToken, Leumi's live SessionID), and
the banks treat a return to the login gateway as a brand-new session — which
kills the old one. So instead of driving the tab somewhere we can judge, we look
for the tab that is ALREADY somewhere judgeable.

Reads Chrome's /json/list on stdin, takes the source name from $SRC, and:

  --index (default) prints the INDEX of the first page target that looks like
      the source's app, for `playwright-cli tab-select`.
  --verdict prints LIVE / DEAD / UNKNOWN, the coarse URL+title fallback used
      when the in-page JS signal could not run.

Prints nothing (index mode) when no app tab is open — the caller must treat
that as UNKNOWN ("open a tab on this source and re-run"), never as DEAD.
"""
import json
import os
import sys

# source -> (url substrings, title substrings) that mean "on the app, past login"
APP = {
    "riseup":   (("input.riseup.co.il/web/",), ()),
    "discount": (("apollo/retail3",), ()),
    # Same Chrome/login as "discount" but the SME app; only sync/ looks for it.
    "discount-business": (("apollo/business2",), ()),
    "leumi":    (("#/hpsummary",), ()),
    "cal":      (("digital-web.cal-online.co.il/dashboard",), ()),
    "amex":     (("web.americanexpress.co.il",), ("אזור אישי",)),
    "max":      (("www.max.co.il/homepage",), ()),
    "harel":    (("client-view.aspx",), ("הראל שלי",)),
    "more":     (("my-account.more.co.il/personalarea",), ()),
    "analyst":  (("amitim.analyst.co.il/lobby",), ("מבט כללי",)),
}
LOGIN_HINTS = ("login", "signin", "gate-keeper", "otp")


def app_tab_index(tabs, src):
    """Index into `tabs` of the first tab on src's app, or None."""
    url_pats, title_pats = APP.get(src, ((), ()))
    for i, t in enumerate(tabs):
        url, title = t.get("url", ""), t.get("title", "")
        if any(h in url.lower() for h in LOGIN_HINTS):
            continue
        if any(p in url for p in url_pats) or any(p in title for p in title_pats):
            return i
    return None


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--index"
    src = os.environ.get("SRC", "")
    try:
        tabs = [t for t in json.load(sys.stdin) if t.get("type") == "page"]
    except Exception:
        if mode == "--verdict":
            print("UNKNOWN")
        return

    idx = app_tab_index(tabs, src)
    if mode == "--verdict":
        # No app tab is not proof of a dead session — it may just be a tab the
        # user closed. Only a tab that IS on the app proves LIVE; anything else
        # here is unknown, and the caller says so rather than crying login.
        print("LIVE" if idx is not None else "UNKNOWN")
    elif idx is not None:
        print(idx)


if __name__ == "__main__":
    main()
