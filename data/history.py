"""History for the home screen's lenses: how the money got to today.

Scraped sources only know *today*, so each series is rebuilt from what the dumps
do carry, and says how much of it is measured:

- ``cash``: end-of-day combined checking balance (the runway's pool: Discount +
  Leumi personal checking) for the last ``CASH_DAYS`` days. Days inside a bank's
  running-balance chain (the same chain ``validate.py`` checks) are measured; days
  before it are walked back from the chain's opening balance through that bank's
  normalized ledger. ``measured_from`` is the first day every account is measured.
- ``debt``: month-start loan balances, ``DEBT_MONTHS_BACK`` months back (reverse
  amortization at today's installment, so estimated) and ``DEBT_MONTHS_AHEAD`` ahead
  (``projection.amortize_loans``, the same schedule as the net-worth projection).
- ``positions``: the daily position recorded in Postgres (``position_snapshots``)
  by every digest; the net-worth and savings lenses read it. Best-effort: no DB, no rows.

Pure functions except ``load_*``/``positions``. Money is ILS; debt is positive.
"""
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
CASH_DAYS = 90
DEBT_MONTHS_BACK = 12
DEBT_MONTHS_AHEAD = 36


def data_dir():
    return Path(os.environ.get("FINANCE_DATA_DIR") or HERE)


# ---- cash ------------------------------------------------------------------

def account_balances(ops, rows, closing, as_of, days=CASH_DAYS):
    """End-of-day balances of one checking account: ``({date: balance}, chain_start)``.

    ``ops`` is the raw running-balance chain (validate.telebank_ops / leumi_ops),
    ``rows`` the account's normalized ledger rows (``date`` ISO, ``amount``),
    ``closing`` today's balance. Days after the chain's last operation carry its
    balance, and ``as_of`` itself is ``closing`` (it may include pending debits).
    Before the chain the balance is walked back through the ledger, as far as the
    ledger reaches. ``chain_start`` is None when there is no chain.
    """
    import validate
    first_day = as_of - timedelta(days=days)
    moves = defaultdict(float)
    for r in rows:
        moves[date.fromisoformat(r["date"][:10])] += r["amount"]
    out = {}
    if ops:
        ops = validate.orient_ops(ops)
        eod = {o["date"]: o["balance_after"] for o in ops}       # oldest first: the day's last op wins
        chain_start = ops[0]["date"]
        anchor = round(ops[0]["balance_after"] - ops[0]["amount"], 2)   # end of the day before
        bal, d = anchor, chain_start
        while d <= as_of:
            bal = eod.get(d, bal)
            out[d] = bal
            d += timedelta(days=1)
        anchor_day = chain_start - timedelta(days=1)
    elif closing is not None:
        chain_start, anchor_day, anchor = None, as_of, closing
    else:
        return {}, None
    if closing is not None:
        out[as_of] = round(closing, 2)
    # Before the anchor: end of (d - 1) = end of d - the ledger's movement on d.
    oldest = (min(moves) if moves else anchor_day) - timedelta(days=1)
    bal, d = anchor, anchor_day
    while d >= max(first_day, oldest):
        out.setdefault(d, round(bal, 2))
        bal -= moves.get(d, 0.0)
        d -= timedelta(days=1)
    return {k: v for k, v in out.items() if k >= first_day}, chain_start


def cash_history(accounts, as_of, days=CASH_DAYS):
    """Combine per-account balances (``[(balances, chain_start)]``) into the pool's series.

    A day is listed only when every account has a balance for it."""
    if not accounts:
        return {"as_of": as_of.isoformat(), "days": [], "measured_from": None}
    common = set.intersection(*(set(b) for b, _ in accounts))
    starts = [s for _, s in accounts]
    measured = max(starts) if all(starts) else None
    return {
        "as_of": as_of.isoformat(),
        "days": [{"date": d.isoformat(), "balance": round(sum(b[d] for b, _ in accounts), 2)}
                 for d in sorted(common)],
        "measured_from": measured.isoformat() if measured else None,
    }


def load_cash(snapshot, as_of, root=None):
    """The pool accounts' chains and ledgers from ``root``'s dumps -> ``cash_history``."""
    import runway
    import validate
    root = Path(root or data_dir())

    def read(*parts):
        p = root.joinpath(*parts)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    accounts = []
    for a in snapshot.get("bank_accounts", []):
        inst = a.get("institution")
        if inst not in runway.POOL_INSTITUTIONS or a.get("kind") != "checking":
            continue
        raw = read(inst, "raw", "transactions.json")
        ops = (validate.leumi_ops if inst == "leumi" else validate.telebank_ops)(raw) if raw else []
        rows = (read(inst, "normalized", "transactions.json") or {}).get("records", [])
        # One checking account per pool bank; its ledger ids differ by scraper (Discount's
        # MCP rows say 0123444499, the snapshot 0034), so take the bank's whole ledger.
        rows = [r for r in rows if r.get("date")]
        accounts.append(account_balances(ops, rows, a.get("balance"), as_of))
    return cash_history([x for x in accounts if x[0]], as_of)


# ---- debt ------------------------------------------------------------------

def _month_add(d, n):
    i = d.year * 12 + d.month - 1 + n
    return date(i // 12, i % 12 + 1, 1)


def debt_series(loans, as_of, back=DEBT_MONTHS_BACK, ahead=DEBT_MONTHS_AHEAD):
    """Month-start loan balances from ``back`` months ago to ``ahead`` months on.

    Each point: ``{month, mortgage, consumer, total, kind}`` where kind is
    ``estimated`` (reverse-amortized at today's installment, zero before the loan's
    first payment), ``actual`` (this month: today's balances) or ``projected``."""
    import projection
    seen, unique = set(), []
    for ln in loans:
        key = (ln.get("lender"), ln.get("loan_id"))
        if key not in seen:
            seen.add(key)
            unique.append(ln)
    sched = projection.amortize_loans(unique)
    made = {(ln.get("name") or ln.get("loan_id")): max(int(ln.get("payments_total") or 0)
                                                        - int(ln.get("payments_remaining") or 0), 0)
            for ln in unique}
    this_month = date(as_of.year, as_of.month, 1)
    points = defaultdict(lambda: {"mortgage": 0.0, "consumer": 0.0})
    for s in sched:
        cat = "mortgage" if s["category"] == "mortgage" else "consumer"
        r, bal = s["rate_m"], s["balance"]
        points[0][cat] += bal
        b = bal                                          # back: b_prev = (b + payment) / (1 + r)
        n_made = made.get(s["name"], 0) or back          # 0 = the bank gave no history: unknown
        for k in range(1, back + 1):
            b = 0.0 if k > n_made else (b + s["base_payment"]) / (1 + r)
            points[-k][cat] += b
        b = bal                                          # ahead: b_next = b (1 + r) - payment
        for k in range(1, ahead + 1):
            b = max(b * (1 + r) - s["payment"], 0.0)
            points[k][cat] += b
    out = []
    for k in range(-back, ahead + 1):
        p = points[k]
        out.append({"month": _month_add(this_month, k).isoformat()[:7],
                    "mortgage": round(p["mortgage"], 2), "consumer": round(p["consumer"], 2),
                    "total": round(p["mortgage"] + p["consumer"], 2),
                    "kind": "actual" if k == 0 else ("estimated" if k < 0 else "projected")})
    return out


# ---- positions (Postgres) -------------------------------------------------

def position_of(snapshot):
    """Today's position from ``snapshot.totals`` (the columns of position_snapshots)."""
    t = snapshot["totals"]
    prop = t.get("property_value")
    return {"cash": t["bank_balances_sum"], "card_debt": t["credit_card_debt"],
            "consumer_loans": t["consumer_loan_balance"], "mortgage": t["mortgage_balance"],
            "savings": t.get("long_term_savings") or 0.0, "property": prop,
            "net_worth": (t["net_worth_with_property"] if t.get("net_worth_with_property") is not None
                          else t["net_position_with_savings"])}


# Card debt switched from RiseUp's balance to the issuers' own next charge on this day (about
# ₪7k more on the day it did). Rows recorded before are kept, but their card debt and net worth
# are not comparable, so they are read back as unknown rather than drawn as money that moved.
CARD_DEBT_COMPARABLE_FROM = "2026-10-28"


def comparable(rows):
    """``position_snapshots`` rows as the lenses should see them (see CARD_DEBT_COMPARABLE_FROM)."""
    return [{**r, "card_debt": None, "net_worth": None} if r["date"] < CARD_DEBT_COMPARABLE_FROM else r
            for r in rows]


def positions(snapshot, as_of):
    """Record today's position, return every recorded day (oldest first).

    Best-effort: with no database configured, or an unreachable one, this prints
    to stderr and returns [] so the digest carries on."""
    import goals
    url = goals.database_url()
    if not url:
        return []
    db = str(HERE.parent / "db")
    sys.path.insert(0, db)
    try:
        import position_store
        from ledger import connect
        with connect(url) as conn:
            position_store.record(conn, as_of, **position_of(snapshot))
            return comparable(position_store.series(conn))
    except Exception as e:   # noqa: BLE001 — a dead DB must not stop the digest
        print(f"history: database unavailable ({e})", file=sys.stderr)
        return []
    finally:
        sys.path.remove(db)


LOCAL_TZ = ZoneInfo("Asia/Jerusalem")


def coverage(snapshot):
    """What a snapshot's totals are made of: its bank accounts, loans and savings accounts.

    Two positions are comparable only when their coverage matches; otherwise a source joining
    or a loan being read for the first time would show as money moving."""
    from digest import RISEUP_ORIGIN

    def account(a):   # RiseUp's copy of an account and the direct scrape are the same account
        inst = a.get("institution") or a.get("source")
        return RISEUP_ORIGIN.get(inst, inst), "".join(c for c in str(a.get("account_id") or a.get("label")) if c.isalnum())

    return (
        frozenset(account(a) for a in snapshot.get("bank_accounts", [])),
        frozenset((l.get("lender") or l.get("source"), l.get("loan_id") or l.get("id")) for l in snapshot.get("loans", [])),
        frozenset((s.get("institution"), s.get("topic_id"), s.get("label")) for s in snapshot.get("savings", [])),
    )


def snapshot_day(snapshot):
    """The local date a snapshot was generated on (``generated_at`` carries its offset)."""
    return datetime.fromisoformat(snapshot["generated_at"]).astimezone(LOCAL_TZ).date()


def backfill_days(snapshots, reference):
    """``{date: position}`` for the published snapshots whose coverage matches ``reference``.

    The last snapshot of a day wins. Used once to seed position_snapshots from the site
    bucket's object versions, which predate the daily recording."""
    want = coverage(reference)
    out = {}
    for snap in sorted(snapshots, key=lambda s: s["generated_at"]):
        if coverage(snap) == want:
            out[snapshot_day(snap)] = position_of(snap)
    return out


def backfill(paths, reference_path=None):
    """Record the comparable days among ``paths`` that position_snapshots does not have yet."""
    import goals
    url = goals.database_url()
    if not url:
        sys.exit("history backfill: DATABASE_URL is not set")
    ref = Path(reference_path) if reference_path else data_dir() / "digested" / "snapshot.json"
    snaps = [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]
    days = backfill_days(snaps, json.loads(ref.read_text(encoding="utf-8")))
    sys.path.insert(0, str(HERE.parent / "db"))
    import position_store
    from ledger import connect
    with connect(url) as conn:
        have = {p["date"] for p in position_store.series(conn)}
        for day, pos in sorted(days.items()):
            if day.isoformat() in have:
                print(f"  {day}  kept (already recorded)")
                continue
            position_store.record(conn, day, **pos)
            print(f"  {day}  net worth {pos['net_worth']:>14,.2f}  savings {pos['savings']:>12,.2f}")
    print(f"{len(days)} of {len(snaps)} snapshots comparable with {ref.name}")


def build(snapshot, as_of, root=None, record=True):
    """The ``cashflow.json`` -> ``history`` block."""
    return {
        "cash": load_cash(snapshot, as_of, root),
        "debt": debt_series(snapshot.get("loans", []), as_of),
        "positions": positions(snapshot, as_of) if record else [],
    }


if __name__ == "__main__":
    if sys.argv[1:2] == ["backfill"]:
        # poetry run python data/history.py backfill SNAPSHOT.json ...  (see the docstring of backfill)
        backfill(sys.argv[2:])
        sys.exit(0)
    snap = json.loads((data_dir() / "digested" / "snapshot.json").read_text(encoding="utf-8"))
    h = build(snap, date.today(), record=False)
    c = h["cash"]
    print(f"cash: {len(c['days'])} days, measured from {c['measured_from']}")
    for p in c["days"][::7]:
        print(f"  {p['date']}  {p['balance']:>12,.2f}")
    print("debt:")
    for p in h["debt"][::6]:
        print(f"  {p['month']}  {p['total']:>14,.2f}  {p['kind']}")
