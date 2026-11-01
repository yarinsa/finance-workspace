#!/usr/bin/env python3
"""Combine the normalized layer -> data/digested/snapshot.{json,md}

Pipeline:  raw/  --(each source's normalize.py)-->  normalized/  --(this)-->  digested/

By default this runs every <source>/normalize.py first, then combines all
<source>/normalized/*.json envelopes into one consolidated snapshot.
Run `python3 digest.py --no-normalize` to combine existing normalized output only.
With DATABASE_URL set, the ledger goes through Postgres (db/) to apply your edits;
`--no-db` skips that.
"""
import json, datetime, glob, os, re, subprocess, sys
from pathlib import Path

import freshness
import horizons
import runway
from finance import categories, manifest, offsets
from finance.paths import data_root

CODE = Path(__file__).resolve().parent          # .../Finance/data (the scripts)
ROOT = data_root()                              # this tenant's files
OUT = ROOT / "digested"
OUT.mkdir(parents=True, exist_ok=True)


def database_url(env_file=CODE.parent / ".env"):
    """DATABASE_URL from the environment, else from .env (read literally)."""
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip("'\"") or None
    return None


def apply_overrides(ledger):
    """Round-trip the ledger through the transactions database (db/ledger.py).

    It is stored as `scraped_transactions` and comes back as the `transactions`
    view: your category/note edits applied, excluded rows removed. A no-op when
    DATABASE_URL is unset or with --no-db. When the database is configured but
    unreachable we stop rather than publish numbers that silently drop the edits.
    """
    if "--no-db" in sys.argv or not database_url():
        return ledger
    res = subprocess.run([sys.executable, str(CODE.parent / "db" / "ledger.py"), "sync"],
                         input=json.dumps(ledger, ensure_ascii=False),
                         capture_output=True, text=True)
    sys.stderr.write(res.stderr)
    if res.returncode != 0:
        raise SystemExit("db sync failed (is `docker compose up -d` running?); "
                         "rerun with --no-db to digest without the database")
    return json.loads(res.stdout)


def category_merges():
    """{category: the category it was merged into} from the database (`db/ledger.py merges`);
    {} without one. budgets.py folds a merged category's plan into its target with it."""
    if "--no-db" in sys.argv or not database_url():
        return {}
    res = subprocess.run([sys.executable, str(CODE.parent / "db" / "ledger.py"), "merges"],
                         capture_output=True, text=True)
    return json.loads(res.stdout) if res.returncode == 0 and res.stdout.strip() else {}


def run_normalizers():
    for script in sorted(CODE.glob("*/normalize.py")):
        print(f"normalizing {script.parent.name}…")
        subprocess.run([sys.executable, str(script)], check=True)


def load_entities():
    """Group all normalized records by entity across every source."""
    entities = {}
    for fp in sorted(ROOT.glob("*/normalized/*.json")):
        env = json.load(open(fp, encoding="utf-8"))
        for rec in env["records"]:
            rec.setdefault("_source", env["source"])   # stamp origin for dedup/reporting
        entities.setdefault(env["entity"], []).extend(env["records"])
    return entities


# --- Internal-transfer detection -------------------------------------------
# Money moved between the household's OWN accounts is not cashflow — it's the
# same shekels in two ledgers. The dedup key (date, abs amount) already collapses
# the clean same-day both-legs case into one row; what survives is a single leg
# whose counterpart sits in another of our accounts (or an untracked personal
# account, e.g. Bank Hapoalim). The reliable signal is the description naming the
# household member or one of our own account numbers. We TAG these
# (`internal_transfer: true`) rather than drop them — the ledger stays complete
# and auditable; the spending summary and cashflow exclude them.
#
# The other reliable signal is structural: when both legs are in the data, a
# self-transfer collapses into one bucket holding a DEBIT at one bank and a CREDIT
# at another (e.g. the monthly salary forward: Leumi "העברת משכורת_י" -22,500 /
# Discount "בנק לאומי,משכורת" +22,500). RiseUp tags the inbound leg "משכורת", so
# without this it reads as a second salary. See `_is_cross_bank_pair`.
#
# NOTE: tuned to this household. Update OWN_NAMES / OWN_ACCOUNT_HINTS if accounts
# or holders change. Salary ("העברת משכורת", "בנק לאומי משכורת") does NOT name the
# holder, so on its own it is kept as real income — only the paired-legs rule
# above turns a forward into a transfer.
OWN_NAMES = ["ירין ששון", "ששון ירין"]
OWN_ACCOUNT_HINTS = ["806-6719", "806-671963", "10-806", "0034069", "0123444499"]
# Account-sweep descriptions that don't name the holder but are confirmed self-
# transfers between our own accounts. "העברה דיגיטל" always originates from the
# Leumi account and empties it to ~0, matched by a "+X העברה מירין ששון" inbound
# on Discount — i.e. a Leumi→Discount sweep. Treated as internal.
OWN_TRANSFER_DESCRIPTIONS = ["העברה דיגיטל"]

# Withdrawals from our own liquid deposit (פיקדון נזיל) coming back into checking,
# plus the tiny interest/profit credited alongside them. The deposit LEG (money
# going in) is real savings (is_savings_deposit, below); the withdrawal LEG is the
# same money returning and must not be double-counted as income.
DEPOSIT_WITHDRAWAL_PHRASES = ["משיכה מפיקדון", "רווחים ממשיכת הפקדה מפיקדון"]

# Loan ids where BOTH "הקמת הלוואה <id>" (opened) and "פירעון/פרעון הלוואה <id>"
# (repaid) were observed in the ledger — i.e. confirmed round-trips that net to
# ~zero, not real borrowing/debt-service. Populated below from ledger evidence.
# Deliberately an allowlist of specific ids, NOT a blanket rule on the phrase —
# most "פירעון הלוואה" rows are real ongoing loan repayments (leumi, discount
# loans 10800100014 / 15500316168) and must stay counted as spend.
ROUND_TRIP_LOAN_IDS = {"13200898802"}

_LOAN_ID_RE = re.compile(r"(?:הקמת|פירעון|פרעון) הלוואה\s+(\d+)")


def is_internal_transfer(rec):
    """True if the transaction is a move between the household's own accounts.

    Matches on the description referencing an own holder name, own account
    number, a known self-transfer phrase, a liquid-deposit withdrawal (the
    money returning from our own deposit), or one leg of a confirmed
    open+repay loan round-trip. Conservative: only fires on a positive
    signal, so external transfers (real income/expense) are kept.
    """
    desc = rec.get("description") or ""
    if any(n in desc for n in OWN_NAMES):
        return True
    if any(a in desc for a in OWN_ACCOUNT_HINTS):
        return True
    if any(p in desc for p in OWN_TRANSFER_DESCRIPTIONS):
        return True
    if any(p in desc for p in DEPOSIT_WITHDRAWAL_PHRASES):
        return True
    m = _LOAN_ID_RE.search(desc)
    if m and m.group(1) in ROUND_TRIP_LOAN_IDS:
        return True
    return False


# --- Credit-card bill settlement -------------------------------------------
# A card BILL payment (bank account → card issuer) is not spend: the underlying
# purchases are already in the ledger as individual card transactions, so
# counting the monthly settlement too double-counts. These rows are bank-side
# debits whose description is the issuer's clearing name + "חיוב". Tagged
# `card_bill_payment: true` and excluded from cashflow/summary.
#
# Scoped to bank origins so we never catch an actual purchase. Phrase list is the
# clearing names seen in the dumps (CAL/Diners, Amex, Isracard/Mastercard, Max).
CARD_BILL_PHRASES = [
    "דיינרס", "אמריקן אקס", "מאסטרקרד", "מסטרקארד", "ל.מאסטרקרד",
    "ויזה כ.א.ל", "כרטיסי אשראי", "מקס איט", "max", "ישראכרט", "כאל",
]
BANK_ORIGINS = {"discount", "discount-business", "leumi"}


def _mentions_card_issuer(desc, low):
    if any(p in desc for p in CARD_BILL_PHRASES if p.isascii() is False):
        return True
    # ascii issuer names (max) — match on the lowercased description
    if any(p in low for p in CARD_BILL_PHRASES if p.isascii()):
        return True
    return False


def is_card_bill_payment(rec):
    """True if this is a bank-side move against a card-issuer settlement — the
    monthly debit, or a reversal/re-charge credit of one — not real spend or income.

    Keyed on the counterparty being one of our known card issuers on a BANK
    origin, not on the "חיוב" suffix alone: a settlement reversal (issuer credits
    the bank back, e.g. a charge reversed then re-billed days later) carries a
    POSITIVE amount and often lacks "חיוב" in its description, but it is still
    our own money moving between our bank and our card issuer — never counted as
    income. Ordinary debit settlements (negative, "...,חיוב") keep matching as
    before. Scoped to BANK_ORIGINS so a genuine merchant refund on the CARD side
    (origin cal/amex, a specific merchant name) is never caught here.
    """
    if rec.get("origin") not in BANK_ORIGINS:
        return False
    desc = (rec.get("description") or "")
    low = desc.lower()
    amount = float(rec.get("amount") or 0)
    if amount < 0:                                 # ordinary debit settlement
        return "חיוב" in desc and _mentions_card_issuer(desc, low)
    # positive amount: only a settlement reversal/credit from a known issuer
    # counterparty qualifies — never match on amount alone.
    return _mentions_card_issuer(desc, low)


# --- Savings / investment deposits -----------------------------------------
# Money routed into the household's OWN savings or investment vehicles (a liquid
# deposit, an asset-management standing order). It leaves the checking account
# (so it's a real outflow) but it is *saved*, not *spent* — Plangram models it as
# its own bucket. Tagged `savings: true`; cashflow routes it to a "savings"
# bucket and keeps it out of the spending breakdown.
# NOTE: "ניהול נכסי" (property management) is deliberately NOT here — the
# "עיין ניהול נכסי" standing order is RENT, a real living expense, not savings.
# "ניהול השק" (investment management, e.g. Excellence) stays.
SAVINGS_PHRASES = [
    "פיקדון", "פקדון", "ניהול השק", "קרן השתלמות",
    "אקסלנס", "הראל", "גמל", "השקעות",
]


def is_savings_deposit(rec):
    """True if this is a deposit into our own savings/investment vehicle."""
    if float(rec.get("amount") or 0) >= 0:        # a deposit is an outflow
        return False
    desc = rec.get("description") or ""
    # "הפקדה ל..." / standing order to an investment manager
    if "הפקדה" in desc and ("פיקדון" in desc or "פקדון" in desc):
        return True
    if any(p in desc for p in SAVINGS_PHRASES) and ("הפקדה" in desc or 'הו"ק' in desc or "העברה ל" in desc):
        return True
    return False


# RiseUp tags transactions with its own origin names; map them to our source ids
# so a CAL charge from riseup and the same charge from data/cal/ dedup together.
RISEUP_ORIGIN = {
    "cal": "cal",
    "leumicard": "max",                          # Max (ex-Leumi Card): RiseUp's cards 3819/9613
    "americanexpress": "amex", "isracard": "amex",
    "discount": "discount", "leumiBank": "leumi", "leumi": "leumi",
}


def _canon_tx(r):
    """Map a per-source transaction record to one common shape.

    Sources differ: cal/amex carry card_last4/card_name; riseup carries
    origin/category/is_income; discount/leumi carry account_id. We keep a common
    core plus whatever identifying extras the source provided.
    """
    src = r.get("_source")
    origin = src
    if src == "riseup":
        origin = RISEUP_ORIGIN.get(r.get("origin"), r.get("origin") or "riseup")
    t = {
        "date": r.get("date", ""),
        "amount": round(r.get("amount", 0), 2),
        "description": r.get("description", ""),
        "category": r.get("category"),
        "origin": origin,                         # institution the money actually moved at
        "is_income": r.get("is_income", r.get("amount", 0) > 0),
        "sources": [src],                         # which of our scrapers saw it
        "card_last4": r.get("card_last4"),
        "account_id": r.get("account_id"),
        "budget_type": r.get("budget_type"),
        "budget_category": r.get("budget_category"),
        "_riseup": src == "riseup",
    }
    if is_internal_transfer(t):
        t["internal_transfer"] = True            # excluded from cashflow/summary
    elif is_card_bill_payment(t):
        t["card_bill_payment"] = True            # excluded — purchases already in ledger
    elif is_savings_deposit(t):
        t["savings"] = True                      # real outflow, but saved not spent
    return t


def _is_cross_bank_pair(legs):
    """True if the merged legs include a debit at one of our banks and a credit at
    a DIFFERENT one — the two sides of a move between our own accounts.

    Same-institution opposite signs (a card charge + refund) don't count, and a
    lone leg never does, so a forward whose source side we never scraped stays
    income.
    """
    out = {o for o, sign in legs if sign < 0 and o in BANK_ORIGINS}
    inc = {o for o, sign in legs if sign > 0 and o in BANK_ORIGINS}
    return any(a != b for a in out for b in inc)


def consolidate_transactions(txns):
    """Merge every source's transactions into one deduped ledger.

    Two records are the same purchase when (date, abs(amount)) match. RiseUp is the
    higher-priority copy (it carries the spending category), so on a match the RiseUp
    record's fields win and the direct source is recorded in `sources`.
    Output is sorted newest-first and ready to query.
    """
    buckets = {}                                  # (date, abs_amount) -> merged record
    for raw in txns:
        t = _canon_tx(raw)
        t["_legs"] = {(t["origin"], (t["amount"] > 0) - (t["amount"] < 0))}
        key = (t["date"], round(abs(t["amount"]), 2))
        cur = buckets.get(key)
        if cur is None:
            buckets[key] = t
            continue
        # merge: union the sources, let RiseUp win the descriptive fields
        merged_sources = sorted(set(cur["sources"]) | set(t["sources"]))
        winner = t if (t["_riseup"] and not cur["_riseup"]) else cur
        other = cur if winner is t else t
        winner["sources"] = merged_sources
        winner["_legs"] = cur["_legs"] | t["_legs"]
        # backfill anything the winner is missing from the other copy
        for f in ("category", "card_last4", "account_id", "origin", "budget_type", "budget_category"):
            if not winner.get(f) and other.get(f):
                winner[f] = other[f]
        # Re-evaluate the exclusion flags on the MERGED row rather than OR-ing the
        # legs. Two unrelated charges can collide on (date, abs amount) — a real
        # purchase vs a self-transfer of the same value on the same day — and we
        # must not let one leg's flag taint the other. Trust only the description
        # that actually survives onto the merged row.
        for flag, test in (("internal_transfer", is_internal_transfer),
                           ("card_bill_payment", is_card_bill_payment),
                           ("savings", is_savings_deposit)):
            if test(winner) or (flag == "internal_transfer"
                                and _is_cross_bank_pair(winner["_legs"])):
                winner[flag] = True
            else:
                winner.pop(flag, None)
        if not winner.get("description"):
            winner["description"] = other.get("description", "")
        buckets[key] = winner

    out = []
    for t in buckets.values():
        t.pop("_riseup", None)
        t.pop("_legs", None)
        t["horizon"] = horizons.default_horizon(t)   # a manual override replaces it in the view
        out.append({k: v for k, v in t.items() if v is not None})
    out = merge_shifted_copies(out)
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def merge_shifted_copies(ledger):
    """Merge a RiseUp-only row into the direct source's copy dated one day apart.

    RiseUp occasionally dates a card charge a day after the card does (APPLE.COM/BILL
    ₪59.50: Max 2026-10-14, RiseUp 2026-10-15), so the (date, amount) key misses it.
    Only an unmatched RiseUp row and an unmatched direct row with the same origin,
    sign, amount and merchant, exactly one day apart, merge — two same-price charges
    at different institutions or merchants stay apart. Each row merges at most once.
    The direct source's date is kept (the institution's own record); RiseUp's
    descriptive fields win as in `consolidate_transactions`."""
    from finance.merchants import merchant_name
    direct = {}
    for t in ledger:
        if "riseup" not in t["sources"]:
            k = (t.get("origin"), round(t["amount"], 2), merchant_name(t.get("description")))
            direct.setdefault(k, []).append(t)
    used, dropped = set(), set()
    for r in ledger:
        if r["sources"] != ["riseup"]:
            continue
        k = (r.get("origin"), round(r["amount"], 2), merchant_name(r.get("description")))
        rd = datetime.date.fromisoformat(r["date"][:10])
        for o in direct.get(k, []):
            if id(o) in used or abs((datetime.date.fromisoformat(o["date"][:10]) - rd).days) != 1:
                continue
            for f, v in r.items():
                if f not in ("date", "sources") and v is not None and (f != "description" or v):
                    o[f] = v
            o["sources"] = sorted(set(o["sources"]) | {"riseup"})
            o["horizon"] = horizons.default_horizon(o)
            used.add(id(o))
            dropped.add(id(r))
            break
    return [t for t in ledger if id(t) not in dropped]


# --- PayBox round trips -------------------------------------------------------
# Loading PayBox from a card and cashing it out to a bank account is our own money
# going around: the card leg (`PAYBOX`, −₪1,000 on amex) and the bank leg
# (`מפייבוקס ש…`, +₪1,000 at Discount/Leumi a day or two later) are both
# internal transfers, not a ₪1,000 expense plus ₪1,000 income.
ROUND_TRIP_LEGS = [("PAYBOX", "פייבוקס")]       # (card-side merchant, bank-side credit)
ROUND_TRIP_DAYS = 3


def mark_round_trips(ledger):
    """Flag each card-side load and its same-amount bank-side cash-out (0..3 days
    later, nearest first) as `internal_transfer` + `round_trip`. A load with no
    cash-out (paying someone through PayBox) stays spend. Mutates `ledger`."""
    def day(t):
        return datetime.date.fromisoformat(t["date"][:10])
    used = set()
    for card_pat, bank_pat in ROUND_TRIP_LEGS:
        loads = sorted((t for t in ledger if t["amount"] < 0 and t.get("origin") in offsets.CARD_ORIGINS
                        and card_pat in (t.get("description") or "").upper()), key=lambda t: t["date"])
        outs = [t for t in ledger if t["amount"] > 0 and t.get("origin") in BANK_ORIGINS
                and bank_pat in (t.get("description") or "")]
        for load in loads:
            match = [o for o in outs if id(o) not in used and abs(o["amount"] + load["amount"]) < 0.005
                     and 0 <= (day(o) - day(load)).days <= ROUND_TRIP_DAYS]
            if not match:
                continue
            o = min(match, key=lambda o: (day(o) - day(load)).days)
            used.add(id(o))
            for t in (load, o):
                t["internal_transfer"] = True
                t["round_trip"] = True
    return ledger


# Household offset rules (gitignored; personal names): a payer whose transfers pay
# back a known expense, e.g. [{"payer": "<roommate>", "against": ["<landlord>"]}].
# See finance/offsets.py.
OFFSET_RULES = ROOT / "offsets" / "rules.json"


def load_offset_rules(path=OFFSET_RULES):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def _iso_date(d):
    """Loan end dates arrive as '20530810' (Discount) or '2028-12-02' (Leumi)."""
    d = str(d or "")
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return d[:10] or None


# Discount marks subsidised tracks (מתווה, לשעורין) with a 0.0001% placeholder.
_ZERO_RATE_EPS = 0.01


def loan_profile(loans):
    """Balance-weighted summary of a set of loans (e.g. the mortgage's tracks).

    ``avg_rate_pct`` is weighted by outstanding balance, so a small 8% loan barely
    moves it and the large tracks dominate — which is what "what does my debt
    cost" means. It is the *nominal* rate the banks report: a refund that offsets
    interest (see MEMORY.md) is invisible here. ``rate_mix`` gives the share of
    balance that is fixed / variable / CPI-linked (linked overlaps the other two).
    Returns None for an empty set.
    """
    loans = [l for l in loans if (l.get("balance") or 0) > 0]
    if not loans:
        return None
    total = sum(l["balance"] for l in loans)

    def rate(l):
        r = float(l.get("rate_pct") or 0)
        return 0.0 if r < _ZERO_RATE_EPS else r

    def share(pred):
        return round(sum(l["balance"] for l in loans if pred(l)) / total, 4)

    ends = [d for d in (_iso_date(l.get("final_date")) for l in loans) if d]
    return {
        "balance": round(total, 2),
        "monthly_payment": round(sum(l.get("monthly_payment") or 0 for l in loans), 2),
        "avg_rate_pct": round(sum(l["balance"] * rate(l) for l in loans) / total, 2),
        "rate_mix": {
            "fixed": share(lambda l: l.get("rate_type") == "fixed"),
            "variable": share(lambda l: l.get("rate_type") == "variable"),
            "index_linked": share(lambda l: bool(l.get("index_linked"))),
            "zero_rate": share(lambda l: rate(l) == 0),
        },
        "tracks": len(loans),
        "final_date": max(ends) if ends else None,
        "payments_remaining": max((l.get("payments_remaining") or 0) for l in loans),
    }


CARD_SOURCES = {"cal", "amex", "max"}           # the issuers we scrape directly


def next_card_charges(txns, as_of):
    """What each card will charge next, from the issuers' own rows: ``({last4: {date, owed}}, covered)``.

    Every direct card row carries the day its card is charged (``billing_date``). A card's next
    charge is the earliest such day that has not posted yet, summed (refunds subtract). A charge
    posts on its billing day, rolled to Sunday when that is a Friday or Saturday, so on the day
    itself it is already in the bank balance and no longer owed. ``covered`` is every last4 the
    direct sources know, so a card with nothing due is distinguishable from one they never saw."""
    due, covered = {}, set()
    for t in txns:
        if t.get("_source") not in CARD_SOURCES or not t.get("card_last4"):
            continue
        covered.add(t["card_last4"])
        bd = t.get("billing_date")
        if not bd:
            continue
        day = datetime.date.fromisoformat(str(bd)[:10])
        if runway.posting_date(day) > as_of:
            due.setdefault(t["card_last4"], {}).setdefault(day.isoformat(), []).append(-t["amount"])
    out = {}
    for last4, by_day in due.items():
        day = min(by_day)
        out[last4] = {"date": day, "owed": round(sum(by_day[day]), 2)}
    return out, covered


def build_snapshot(e, assets=None, as_of=None):
    """The headline position. `assets` are the household's hand-typed assets
    (db/asset_store.py: the apartment), None when there is no database."""
    as_of = as_of or datetime.date.today()
    accounts = e.get("accounts", [])
    cards = e.get("credit_cards", [])
    loans = e.get("loans", [])
    income = e.get("income", [])
    txns = e.get("transactions", [])

    # De-dupe bank accounts that appear in more than one source. The same
    # checking account shows up both from its direct scrape and from RiseUp's
    # aggregation, but under *different* account_ids (branch id vs RiseUp's id),
    # so we key on the normalized institution instead. Direct sources are
    # authoritative for balances (per CLAUDE.md), so a row carrying overdraft/
    # available detail — which only the direct scrapes emit — wins over RiseUp's
    # copy; otherwise prefer the larger-magnitude balance.
    def inst_key(a):
        return RISEUP_ORIGIN.get(a.get("institution"), a.get("institution"))

    def is_direct(a):
        # RiseUp's copy can be stale or mislabelled (it reports Leumi checking as a
        # 'loan_account'), so any direct scrape beats it.
        if a.get("_source"):
            return a["_source"] != "riseup"
        return "available_balance" in a or "overdraft_limit" in a

    by_inst = {}
    for a in accounts:
        k = inst_key(a)
        cur = by_inst.get(k)
        if (cur is None
                or (is_direct(a) and not is_direct(cur))
                or (is_direct(a) == is_direct(cur)
                    and abs(a["balance"]) > abs(cur["balance"]))):
            by_inst[k] = a
    accounts = list(by_inst.values())

    # Cards arrive from two kinds of source: RiseUp emits debt-bearing cards (owed),
    # while amex/cal emit a fuller roster (last4, name, active) without a balance.
    # Use the debt-bearing cards for totals; enrich them with roster names by last4.
    roster = {c["last4"]: c for c in cards if "owed" not in c and c.get("last4")}
    debt_cards = [c for c in cards if "owed" in c]
    for c in debt_cards:
        info = roster.get(c.get("last4"))
        if info and not c.get("name"):
            c["name"] = info.get("name")
    # What each card owes is the issuer's own next charge. RiseUp's figure is only a fallback for a
    # card no direct source has seen (it can be days stale, and missed whole cards).
    charges, covered = next_card_charges(txns, as_of)
    cards = [{**c, "owed": charges[c["last4"]]["owed"], "next_charge_date": charges[c["last4"]]["date"]}
             for c in debt_cards if c.get("last4") in charges]
    cards += [c for c in debt_cards if c.get("last4") not in covered]            # not scraped directly
    known = {c.get("last4") for c in debt_cards}
    for last4, ch in charges.items():            # a card RiseUp does not list at all
        if last4 not in known:
            r = roster.get(last4, {})
            cards.append({"issuer": r.get("issuer", "amex"), "last4": last4, "name": r.get("name"),
                          "holder": r.get("holder"), "owed": ch["owed"], "next_charge_date": ch["date"],
                          "currency": "ILS"})
    cards = [c for c in cards if c["owed"]]
    cc_total = round(sum(c["owed"] for c in cards), 2)
    bank_sum = round(sum(a["balance"] for a in accounts), 2)
    mortgage = [l for l in loans if l["category"] == "mortgage"]
    consumer = [l for l in loans if l["category"] == "consumer"]
    mortgage_balance = round(sum(l["balance"] for l in mortgage), 2)
    consumer_balance = round(sum(l["balance"] for l in consumer), 2)
    loan_monthly = round(sum(l["monthly_payment"] for l in loans), 2)
    salary = income[0]["monthly_amount"] if income else None

    tracked_net = round(bank_sum - cc_total - mortgage_balance - consumer_balance, 2)

    # Savings (pension / study funds / bank deposits). Assets, not cashflow — they
    # carry no transactions, so they never touch the ledger. Kept OUT of
    # tracked_net_position (which stays a liquid-position-vs-debt figure) and
    # surfaced separately in net_position_with_savings.
    #
    # Not all savings are equal: Harel pension/study funds are locked for years
    # (illiquid), while a Discount נזיל deposit can be exited same-day (liquid).
    # Lumping them into one number would misleadingly suggest money is available
    # that isn't. Each record carries `liquid: true/false` (default False —
    # unmarked/legacy records like Harel's are conservatively illiquid) so the
    # totals below can be reported split, while net_position_with_savings keeps
    # its existing meaning (all savings, liquid or not, added to the tracked net).
    savings = e.get("savings", [])
    savings_sum = round(sum(s["balance"] for s in savings), 2)
    liquid_savings_sum = round(sum(s["balance"] for s in savings if s.get("liquid")), 2)
    illiquid_savings_sum = round(savings_sum - liquid_savings_sum, 2)

    # Property (the apartment) is typed in by hand. It joins net worth only in its own
    # figure, so the existing totals keep answering the questions they always did.
    assets = assets or []
    prop = [a for a in assets if a.get("kind") == "property"]
    property_value = round(sum(a["value"] for a in prop), 2) if prop else None

    def clean(records):                           # drop internal stamps from output
        return [{k: v for k, v in r.items() if not k.startswith("_")} for r in records]

    return {
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "currency": "ILS",
        "note": "Combined from the normalized layer. Bank balances, debts and long-term "
                "savings (pension / study funds). Property value and any savings held "
                "outside the scraped sources are still NOT included.",
        "bank_accounts": clean(accounts),
        "credit_cards": clean(cards),
        "loans": clean(loans),
        "savings": clean(savings),
        "assets": assets,
        "income": clean(income),
        "transactions_count": len(txns),
        "debt_profile": {
            "mortgage": loan_profile(mortgage),
            "consumer": loan_profile(consumer),
            "all_loans": loan_profile(loans),
        },
        "totals": {
            "bank_balances_sum": bank_sum,
            "credit_card_debt": cc_total,
            "mortgage_balance": mortgage_balance,
            "consumer_loan_balance": consumer_balance,
            "total_debt": round(cc_total + mortgage_balance + consumer_balance, 2),
            "tracked_net_position": tracked_net,
            "long_term_savings": savings_sum,
            "liquid_savings": liquid_savings_sum,
            "illiquid_savings": illiquid_savings_sum,
            "net_position_with_savings": round(tracked_net + savings_sum, 2),
            "property_value": property_value,
            "net_worth_with_property": (round(tracked_net + savings_sum + property_value, 2)
                                        if property_value is not None else None),
            "monthly_loan_service": loan_monthly,
            "detected_monthly_salary": salary,
        },
    }


def load_assets():
    """The hand-typed assets from Postgres (db/asset_store.py), or None with no database.

    Best-effort: an unreachable database prints to stderr and the digest carries on."""
    url = database_url()
    if not url or "--no-db" in sys.argv:
        return None
    db = str(CODE.parent / "db")
    sys.path.insert(0, db)
    try:
        import asset_store
        from ledger import connect
        with connect(url) as conn:
            return asset_store.all_assets(conn)
    except Exception as e:   # noqa: BLE001 — a dead DB must not stop the digest
        print(f"assets: database unavailable ({e})", file=sys.stderr)
        return None
    finally:
        sys.path.remove(db)


def load_holding_assignments():
    """Where the user placed savings holdings by hand (db/holding_store.py): `{holding_id: {horizon, goal_id}}`,
    or None with no database. The ids are the app's (`institution:topic_id`), so this only passes them through."""
    url = database_url()
    if not url or "--no-db" in sys.argv:
        return None
    db = str(CODE.parent / "db")
    sys.path.insert(0, db)
    try:
        import holding_store
        from ledger import connect
        with connect(url) as conn:
            return holding_store.all_assignments(conn)
    except Exception as e:   # noqa: BLE001 — a dead DB must not stop the digest
        print(f"holding assignments: database unavailable ({e})", file=sys.stderr)
        return None
    finally:
        sys.path.remove(db)


def write_markdown(s):
    def ils(x): return f"₪{x:,.0f}"
    t = s["totals"]
    mortgage = [l for l in s["loans"] if l["category"] == "mortgage"]
    consumer = [l for l in s["loans"] if l["category"] == "consumer"]
    md = [f"# Financial snapshot — {s['generated_at'][:10]}\n",
          "*Auto-generated: `python3 digest.py` (runs every source's normalize.py, then combines).*\n",
          "## Headlines\n",
          f"- **Total debt:** {ils(t['total_debt'])} "
          f"(mortgage {ils(t['mortgage_balance'])} · consumer loans {ils(t['consumer_loan_balance'])} · cards {ils(t['credit_card_debt'])}).",
          f"- **Monthly loan service:** {ils(t['monthly_loan_service'])}.",
          f"- **Bank balances:** {ils(t['bank_balances_sum'])}.",
          f"- **Transactions normalized:** {s['transactions_count']}."]
    if t.get("long_term_savings"):
        md.append(f"- **Total savings:** {ils(t['long_term_savings'])} "
                  f"(liquid {ils(t.get('liquid_savings', 0))} — deposits you can exit "
                  f"same-day · illiquid {ils(t.get('illiquid_savings', 0))} — pension / "
                  f"study funds) → net with savings {ils(t['net_position_with_savings'])}.")
    if t["detected_monthly_salary"]:
        md.append(f"- **Detected monthly salary:** {ils(t['detected_monthly_salary'])} "
                  f"({t['monthly_loan_service']/t['detected_monthly_salary']*100:.0f}% goes to loans).")
    md.append("\n## Loans\n")
    md.append("| Loan | Cat. | Balance | Rate | Type | Linked | Left | ₪/mo |")
    md.append("|---|---|--:|--:|---|:--:|--:|--:|")
    for l in mortgage + consumer:
        md.append(f"| {l['name']} | {l['category']} | {ils(l['balance'])} | {l['rate_pct']}% | "
                  f"{l['rate_type']} | {'yes' if l['index_linked'] else 'no'} | "
                  f"{l['payments_remaining']} | {ils(l['monthly_payment'])} |")
    md.append("\n## Credit cards\n")
    md.append("| Card | Next charge | Owed |")
    md.append("|---|---|--:|")
    for c in s["credit_cards"]:
        md.append(f"| {c['issuer']} ····{c['last4']} | {c.get('next_charge_date') or '—'} | {ils(c['owed'])} |")
    if s.get("savings"):
        md.append("\n## Long-term savings\n")
        md.append("| Fund | Kind | Policies | Balance |")
        md.append("|---|---|--:|--:|")
        for v in s["savings"]:
            md.append(f"| {v['label']} | {v['kind']} | {v.get('policies_count') or '—'} | "
                      f"{ils(v['balance'])} |")
    md.append(f"\n> {s['note']}\n")
    (OUT / "snapshot.md").write_text("\n".join(md) + "\n")


def spending_summary(ledger):
    """Aggregate the deduped ledger -> totals, per-category and per-origin spend."""
    from collections import defaultdict
    spent = defaultdict(float)        # category -> ₪ out (positive)
    by_origin = defaultdict(float)
    income = 0.0
    out = 0.0
    saved = 0.0                       # money routed to our own savings/investments
    internal_count = 0               # moves between our own accounts
    bill_count = 0                   # card settlements (purchases already counted)
    savings_count = 0
    counted = 0
    for t in ledger:
        if t.get("internal_transfer") or t.get("card_bill_payment"):
            internal_count += t.get("internal_transfer", 0) and 1
            bill_count += t.get("card_bill_payment", 0) and 1
            continue
        if t.get("savings"):          # real outflow, but saved — out of the spend total
            saved += -t["amount"]
            savings_count += 1
            continue
        counted += 1
        amt = t["amount"]
        if t.get("is_income") or amt > 0:
            income += amt
        else:
            out += -amt
            spent[t.get("category") or "uncategorized"] += -amt
            by_origin[t.get("origin") or "unknown"] += -amt
    top = sorted(spent.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "transactions": counted,
        "internal_transfers_excluded": internal_count,
        "card_bill_payments_excluded": bill_count,
        "total_spent": round(out, 2),
        "total_income": round(income, 2),
        "total_saved": round(saved, 2),
        "savings_deposits": savings_count,
        "by_category": {k: round(v, 2) for k, v in top},
        "by_origin": {k: round(v, 2) for k, v in sorted(by_origin.items(), key=lambda kv: kv[1], reverse=True)},
    }


def _manifest_fields(name):
    """The source's self-declared label, account types and capabilities (empty if it has no manifest)."""
    try:
        m = manifest.load(name)
    except OSError:
        return {}
    return {"label": m.label, "account_types": list(m.account_types), "capabilities": list(m.capabilities)}


def source_syncs(root=ROOT):
    """Per-source data freshness for the dashboard's Syncs page.

    `last_synced` is the newest raw-dump mtime — when the scraper last wrote, not
    when normalize/digest re-ran (those touch every source on each run and would
    make a week-old dump look fresh). `latest_txn_date` is the newest transaction
    the source actually carries, which can lag the scrape (e.g. a card that
    posts with delay).
    """
    out = []
    for raw in sorted(root.glob("*/raw")):
        files = [f for f in raw.rglob("*") if f.is_file() and not f.name.startswith(".")]
        newest = freshness.raw_mtime(raw)
        if newest is None:
            continue
        entities, latest_txn = {}, None
        for fp in sorted((raw.parent / "normalized").glob("*.json")):
            env = json.load(open(fp, encoding="utf-8"))
            entities[env["entity"]] = len(env["records"])
            if env["entity"] == "transactions":
                dates = [r["date"][:10] for r in env["records"] if r.get("date")]
                if dates:
                    latest_txn = max([latest_txn or "", *dates])
        out.append({
            "source": raw.parent.name,
            **_manifest_fields(raw.parent.name),
            "last_synced": datetime.datetime.fromtimestamp(newest).astimezone().isoformat(timespec="seconds"),
            "raw_files": len(files),
            "entities": entities,
            "latest_txn_date": latest_txn,
        })
    return out


def main():
    from finance.tenancy import use_cli_tenant
    use_cli_tenant()
    if "--no-normalize" not in sys.argv:
        run_normalizers()
    entities = load_entities()

    # one deduped, queryable transaction ledger across every source
    ledger = consolidate_transactions(entities.get("transactions", []))
    mark_round_trips(ledger)
    unmapped = categories.stamp(ledger)           # category + kind defaults; the DB layers edits on top
    if unmapped:
        print(f"categories: source labels not in finance/categories.py: {sorted(unmapped)}", file=sys.stderr)
    offsets.suggest(ledger, load_offset_rules())  # auto קיזוז, stored with the scraped row
    ledger = apply_overrides(ledger)              # human edits from Postgres, if configured
    offsets.resolve(ledger)                       # manual links (from the DB) win over auto
    summary = spending_summary(offsets.cashflow_view(ledger))
    (OUT / "transactions.json").write_text(json.dumps(
        {"generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
         "currency": "ILS",
         "note": "Deduped across all sources on (date, abs amount); RiseUp's copy wins on "
                 "conflict and carries the spending category. `sources` lists every scraper "
                 "that saw the transaction.",
         "summary": summary,
         "category_merges": category_merges(),
         "transactions": ledger},
        ensure_ascii=False, indent=2))

    snapshot = build_snapshot(entities, load_assets())
    snapshot["holding_assignments"] = load_holding_assignments() or {}
    snapshot["spending"] = summary
    snapshot["syncs"] = source_syncs()
    snapshot["source_manifests"] = {n: m.model_dump(mode="json") for n, m in manifest.load_all().items()}
    snapshot["freshness"] = freshness.status()
    (OUT / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    write_markdown(snapshot)
    print(f"wrote {OUT / 'transactions.json'} ({len(ledger)} deduped txns)")
    print("wrote", OUT / "snapshot.json")
    print("wrote", OUT / "snapshot.md")

    # cashflow dashboard model (reads the two files just written)
    import cashflow
    cf = cashflow.build()
    print(f"wrote {OUT / 'cashflow.json'} (current month {cf['current_month']})")
    print("wrote", OUT / "cashflow.md")
    print("wrote", OUT / "cashflow.html")


if __name__ == "__main__":
    main()
