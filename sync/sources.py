"""Registry of every source the sync can refresh (RiseUp is deliberately absent).

One entry per scraped source. Pure data: no I/O at import, so the workflow can
import it deterministically. The values mirror what the human-run skills use:
ports and login URLs from refresh-all/scripts/check_sessions.sh, app-tab matching
from refresh-all/scripts/app_tab_index.py (matched by `tab_key`, not duplicated here).

Registry order IS the scrape order. The only Discount Chrome app left is business (SME,
port 9223, profile ~/.chrome-cdp-discount, one human login). Discount mortgage and checking
log in headless by themselves (check=SELF, scrapers/discount/), so they need no Chrome and
sit in no login group. Self-login sources run AFTER discount-business because a headless
login may end the human's telebank session that business rides on. Mortgage and checking
come after business and need no ordering between themselves: the old "mortgage before
business" rule existed because the business app rebinds the *Chrome* server session
(`actionRequired: stepup` on the mortgage endpoints); each headless run is its own fresh
login/session, so business's rebinding cannot touch it. Mortgage runs before checking.
If a headless login is refused (INVALID_PASSWORD / CHANGE_PASSWORD) the later self-login
sources are skipped as needs_login (they share the .env credentials, see Source.group).
"""
from dataclasses import dataclass
from pathlib import Path

# Check strategies (see activities.check_session):
#   verdict  - the source's own check_session.sh VERDICT: LIVE|LOGGED_OUT (strongest; AMEX only)
#   sessions - refresh-all/scripts/check_sessions.sh <check_name>: in-page signal, then tab URL
#   tabs     - open-tab URL/title only, read from CDP /json/list (no playwright attach)
#   self     - the dump logs in by itself (credentials in .env); no Chrome to check
#   headless - the dump reuses the human's login in its Chrome profile, headless; `<dump> --check`
#              is the check (VERDICT line), and Chrome is opened only when a human must log in
VERDICT, SESSIONS, TABS, SELF, HEADLESS = "verdict", "sessions", "tabs", "self", "headless"

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Source:
    name: str
    port: int
    login_url: str            # opened for the human (never used to authenticate)
    app_host: str             # substring of the host: any tab here belongs to this bank
    check: str                # VERDICT | SESSIONS | TABS | SELF
    dumps: tuple              # argv tuples under .claude/skills/; {session} / {port} are substituted
    login_group: str = ""     # sources sharing a login are announced and re-checked together
    chrome: str = ""          # Chrome/profile/playwright-session id, shared by a login group's apps
    check_name: str = ""      # check_sessions.sh source name (defaults to chrome)
    tab_key: str = ""         # key into app_tab_index.APP (defaults to name)
    tab_url: str = ""         # page opened when the profile has no tab on the bank (defaults to login_url)
    app_url: str = ""         # page opened at SCRAPE time when no tab is on the app itself (Discount business)
    playwright: bool = True   # False: the dump talks raw CDP (more, analyst), no playwright-cli session
    otp: bool = False         # the dump can log in with a code the human types in the app (`<dump> --login`)

    @property
    def group(self) -> str:
        # Self-login sources never join a Chrome login group (checking "discount" vs the
        # Discount Chrome group), but they all use the same .env credentials: one group per
        # bank host, so a refused login skips the rest instead of retrying bad credentials
        # (repeated failed logins can lock the account).
        if self.check == SELF:
            return f"{self.app_host}-self"
        return self.login_group or self.name

    @property
    def chrome_id(self) -> str:
        return self.chrome or self.name

    @property
    def profile(self) -> Path:
        return Path.home() / f".chrome-cdp-{self.chrome_id}"

    @property
    def pw_session(self) -> str:
        return self.chrome_id

    @property
    def check_key(self) -> str:
        return self.check_name or self.chrome_id

    @property
    def app_tab_key(self) -> str:
        return self.tab_key or self.name

    @property
    def open_url(self) -> str:
        return self.tab_url or self.login_url


_DISCOUNT = dict(port=9223, login_url="https://start.telebank.co.il/apollo/retail3/",
                 app_host="telebank.co.il", login_group="discount", chrome="discount")

_ALL = [
    # All three Discount sources log in headless by themselves with the same .env credentials
    # (scrapers/discount/): business through the SME login page (scrape-business.mjs), mortgage
    # and checking through the personal one. Each run is its own session, so the old
    # "business rebinds the Chrome session" ordering no longer applies; they share one
    # self-login group, so a refused login skips the other two.
    Source(name="discount-business", port=0, login_url="https://start.telebank.co.il/login/#/LOGIN_PAGE_SME",
           app_host="telebank.co.il", check=SELF, playwright=False,
           dumps=((str(REPO_ROOT / "scrapers" / "discount" / "scrape-business.mjs"),),)),
    Source(name="discount-mortgage", port=0, login_url="https://start.telebank.co.il/login/",
           app_host="telebank.co.il", check=SELF, playwright=False,
           dumps=((str(REPO_ROOT / "scrapers" / "discount" / "scrape-mortgage.mjs"),),)),
    Source(name="discount", port=0, login_url="https://start.telebank.co.il/login/",
           app_host="telebank.co.il", check=SELF, playwright=False,
           dumps=((str(REPO_ROOT / "scrapers" / "discount" / "scrape.mjs"),),)),
    # dump.sh first (it needs the live SessionID); dump-loans.sh navigates the tab.
    # Leumi logs in headless by itself (scrapers/leumi/scrape.mjs, LEUMI_USERNAME/LEUMI_PASSWORD in
    # .env) and makes the dump.sh + dump-loans.sh calls in one run.
    Source(name="leumi", port=0, login_url="https://hb2.bankleumi.co.il/", app_host="bankleumi.co.il",
           check=SELF, playwright=False, dumps=((str(REPO_ROOT / "scrapers" / "leumi" / "scrape.mjs"),),)),
    # CAL logs in headless by itself (scrapers/cal/scrape.mjs, CAL_USERNAME/CAL_PASSWORD in .env).
    Source(name="cal", port=0, login_url="https://www.cal-online.co.il/", app_host="cal-online.co.il",
           check=SELF, playwright=False, dumps=((str(REPO_ROOT / "scrapers" / "cal" / "scrape.mjs"),),)),
    # AMEX logs in headless by itself (scrapers/amex/scrape.mjs, AMEX_ID / AMEX_CARD6_DIGITS /
    # AMEX_PASSWORD from .env) and writes the same files as amex-refresh/scripts/dump.sh.
    Source(name="amex", port=0, login_url="https://web.americanexpress.co.il/", app_host="americanexpress.co.il",
           check=SELF, playwright=False, dumps=((str(REPO_ROOT / "scrapers" / "amex" / "scrape.mjs"),),)),
    # Max (ex-Leumi Card) logs in headless by itself (scrapers/max/scrape.mjs, MAX_USERNAME /
    # MAX_PASSWORD from .env): no Chrome, and a refused login is needs_login, never retried.
    Source(name="max", port=0, login_url="https://www.max.co.il/", app_host="max.co.il",
           check=SELF, playwright=False,
           dumps=((str(REPO_ROOT / "scrapers" / "max" / "scrape.mjs"),),)),
    # Harel's only login is ID + phone + a one-time code, which is never automated: the human logs
    # in once in ~/.chrome-cdp-harel and scrapers/harel/scrape.mjs reuses that session headless.
    Source(name="harel", port=9227, login_url="https://www.harel-group.co.il/personal-info/my-harel/Pages/client-view.aspx",
           app_host="harel-group.co.il", check=HEADLESS, playwright=False, otp=True,
           dumps=((str(REPO_ROOT / "scrapers" / "harel" / "scrape.mjs"),),)),
    Source(name="more", port=9228, login_url="https://my-account.more.co.il/personalarea/dashboard",
           app_host="more.co.il", check=SESSIONS, playwright=False,
           dumps=(("more-refresh/scripts/dump.sh", "{port}"),)),
    Source(name="analyst", port=9229, login_url="https://amitim.analyst.co.il/lobby",
           app_host="analyst.co.il", check=SESSIONS, playwright=False,
           dumps=(("analyst-refresh/scripts/dump.sh", "{port}"),)),
]

# Codes the human types in the app are handed to the waiting dump through one file per source here
# (0600, read once and deleted by the dump).
OTP_DIR = Path.home() / ".finance-otp"

# Hebrew names for the dashboard (the same labels app/src/routes/Syncs.tsx uses).
LABEL_HE = {
    "discount": "דיסקונט — עו״ש",
    "discount-mortgage": "דיסקונט — משכנתא",
    "discount-business": "דיסקונט — עסקי",
    "leumi": "לאומי",
    "cal": "כאל",
    "amex": "אמריקן אקספרס",
    "max": "מקס",
    "harel": "הראל",
    "more": "מור",
    "analyst": "אנליסט",
}

SOURCES = {s.name: s for s in _ALL}
SYNC_ORDER = tuple(SOURCES)


def get(name: str) -> Source:
    try:
        return SOURCES[name]
    except KeyError:
        raise ValueError(f"unknown source {name!r}; known: {', '.join(SOURCES)}") from None


def ordered(names=None) -> list:
    """Requested names (default: all) de-duplicated and in registry order, so the
    Discount chain is always business -> mortgage -> checking whatever the caller passed."""
    if names is None:
        return list(SYNC_ORDER)
    wanted = {get(n).name for n in names}
    return [n for n in SYNC_ORDER if n in wanted]


def resolve(tokens) -> set:
    """Source names for resume.py tokens, each a source name or a login group
    ("discount" means all three Discount apps)."""
    out = set()
    for t in tokens:
        hit = {s.name for s in SOURCES.values() if t in (s.name, s.group)}
        if not hit:
            raise ValueError(f"unknown source or login group {t!r}")
        out |= hit
    return out


def login_groups(names) -> dict:
    """{login_group: [source, ...]} in registry order, for one grouped notification."""
    groups: dict = {}
    for n in ordered(names):
        groups.setdefault(get(n).group, []).append(n)
    return groups
