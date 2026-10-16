"""Balance runway — day-by-day projection of the combined checking balance.

Pool = Discount personal checking + Leumi personal checking (not the business
account). Starting from today's combined balance, replays the *recurring*
bank-side items inferred from the ledger (rent, mortgage, loans, card bills,
salary...) over the next ``horizon_days`` and reports the low point, the first
floor / overdraft-limit breach, and how much is safe to spend until payday.

It is a bills-only projection: no discretionary spend is modelled, so
``safe_to_spend`` is an upper bound on what can leave the account before the
next salary lands without touching the floor.

Pure functions over already-digested data (``transactions.json`` rows and
``snapshot.json`` blocks); reads and writes nothing. Money is ILS, out negative.
"""
from collections import defaultdict
from datetime import date, timedelta
import calendar

POOL_INSTITUTIONS = ("discount", "leumi")
POOL_ORIGINS = POOL_INSTITUTIONS
FLOOR = 0
MIN_PAYDAY = 1000
LOOKBACK_MONTHS = 3
MIN_MONTHS_SEEN = 2
MAX_STALE_DAYS = 40
CASH_MARKERS = ("מזומן", "מזומ")
NOTE = (
    "Bills-only projection (no discretionary spend). Items are inferred from the "
    "last 3 months of ledger rows: card bills = last month's bill, one occurrence "
    "per recurring item per month, internal transfers and cash excluded."
)


def _norm(desc):
    """Collapse whitespace. Digits are kept: two loans differ only by their id."""
    return " ".join((desc or "").split())


def _month_index(d):
    return d.year * 12 + d.month - 1


def _month_start(idx):
    return date(idx // 12, idx % 12 + 1, 1)


def _parse(s):
    return date.fromisoformat(s[:10])


def posting_date(d):
    """Israeli banks do not post Fri/Sat; those roll to the next Sunday."""
    wd = d.weekday()  # Mon=0 .. Fri=4, Sat=5, Sun=6
    if wd == 4:
        return d + timedelta(days=2)
    if wd == 5:
        return d + timedelta(days=1)
    return d


def item_kind(amount, category, description, card_bill=False):
    """Map a recurring item to the UI kind."""
    description = description or ""
    if amount > 0:
        return "income"
    if category in ("הלוואה", "משכנתא") or "משכנתא" in description or "הלוואה" in description:
        return "loan"
    if card_bill or "מאסטרקארד" in description:
        return "card"
    if "ניהול נכסי" in description:
        return "housing"
    return "bill"


def candidate_rows(transactions):
    """Bank-side rows that can recur: pool origins, not internal, not cash."""
    out = []
    for t in transactions:
        if t.get("origin") not in POOL_ORIGINS or t.get("internal_transfer"):
            continue
        desc = t.get("description") or ""
        if any(m in desc for m in CASH_MARKERS):
            continue
        # Sub-shekel rows (e.g. "תשלום מס על רווח" on a deposit) render as ₪0 noise.
        if abs(float(t.get("amount") or 0)) < 1:
            continue
        out.append(t)
    return out


def infer_recurring(transactions, as_of):
    """Recurring items: key -> {amount, day, name, category, kind}.

    Recurring = seen in >= 2 of the last 3 calendar months and last seen within
    40 days of ``as_of``. Amount comes from the largest-|amount| row of the
    latest month; the day-of-month is that row's day, corrected for a Sunday
    posting that was really a Fri/Sat due date (e.g. mortgage Thu 10th, Sun 11th
    -> day 10).
    """
    first = _month_index(as_of) - (LOOKBACK_MONTHS - 1)
    by_key = defaultdict(lambda: defaultdict(list))
    for t in candidate_rows(transactions):
        d = _parse(t["date"])
        if d > as_of or _month_index(d) < first:
            continue
        by_key[(t["origin"], _norm(t["description"]))][_month_index(d)].append((d, t))

    items = {}
    for key, months in by_key.items():
        if len(months) < MIN_MONTHS_SEEN:
            continue
        latest = max(months)
        anchor_d, anchor = max(months[latest], key=lambda p: abs(p[1]["amount"]))
        if (as_of - max(d for rows in months.values() for d, _ in rows)).days > MAX_STALE_DAYS:
            continue
        day = anchor_d.day
        if anchor_d.weekday() == 6:
            for m in sorted((m for m in months if m != latest), reverse=True):
                for d, _ in months[m]:
                    if d.day in (anchor_d.day - 1, anchor_d.day - 2):
                        day = d.day
                        break
                else:
                    continue
                break
        amount = round(anchor["amount"], 2)
        # An income that was due earlier this month but has not posted has most
        # likely stopped (e.g. the partner's 3,400 standing order): drop it.
        # Missing outflows are kept, which errs on the cautious side.
        if amount > 0 and day <= as_of.day and _month_index(as_of) not in months:
            continue
        items[key] = {
            "name": key[1], "amount": amount, "day": day,
            "category": anchor.get("category"),
            "kind": item_kind(amount, anchor.get("category"), key[1],
                              bool(anchor.get("card_bill_payment"))),
            "posted_months": set(months),
        }
    return items


def project_events(items, transactions, as_of, horizon_end):
    """One dated occurrence per item per month inside (as_of, horizon_end].

    A month is skipped when the same key already has a ledger row in it.
    """
    posted = defaultdict(set)
    for t in candidate_rows(transactions):
        posted[(t["origin"], _norm(t["description"]))].add(_month_index(_parse(t["date"])))
    events = []
    for key, it in items.items():
        for m in range(_month_index(as_of), _month_index(horizon_end) + 1):
            if m in posted[key]:
                continue
            ms = _month_start(m)
            due = ms.replace(day=min(it["day"], calendar.monthrange(ms.year, ms.month)[1]))
            when = posting_date(due)
            if as_of < when <= horizon_end:
                events.append({
                    "date": when.isoformat(), "name": it["name"], "amount": it["amount"],
                    "kind": it["kind"], "category": it["category"], "confidence": "inferred",
                })
    # Same day: outflows first (conservative), larger outflow first.
    events.sort(key=lambda e: (e["date"], e["amount"] > 0, e["amount"]))
    return events


def _pool_accounts(bank_accounts):
    return [
        {"institution": a["institution"], "balance": round(a["balance"], 2),
         "overdraft_limit": a.get("overdraft_limit") or 0}
        for a in bank_accounts
        if a.get("institution") in POOL_INSTITUTIONS and a.get("kind") == "checking"
    ]


def _is_salary(e):
    """Payday = salary-tagged inflow of at least ``MIN_PAYDAY`` (RiseUp tags small
    bank-fee refunds as 'משכורת' too)."""
    return e["amount"] >= MIN_PAYDAY and (e.get("category") == "משכורת" or "משכורת" in e["name"])


def build_runway(transactions, bank_accounts, savings, as_of, horizon_days=45):
    """Build the runway block (schema consumed by the dashboard)."""
    horizon_end = as_of + timedelta(days=horizon_days)
    accounts = _pool_accounts(bank_accounts)
    start = round(sum(a["balance"] for a in accounts), 2)
    limit = round(sum(a["overdraft_limit"] for a in accounts), 2)

    events = project_events(infer_recurring(transactions, as_of), transactions, as_of, horizon_end)
    bal = start
    for e in events:
        bal = round(bal + e["amount"], 2)
        e["balance_after"] = bal

    by_day = defaultdict(float)
    for e in events:
        by_day[e["date"]] += e["amount"]
    days, bal = [], start
    for i in range((horizon_end - as_of).days + 1):
        d = (as_of + timedelta(days=i)).isoformat()
        bal = round(bal + by_day.get(d, 0), 2)
        days.append({"date": d, "balance": bal})

    payday_ev = next((e for e in events if _is_salary(e)), None)
    payday = ({"date": payday_ev["date"], "amount": payday_ev["amount"], "name": payday_ev["name"]}
              if payday_ev else None)

    low = min(days, key=lambda x: x["balance"])
    low_pre = days_to = safe = per_day = headroom = None
    if payday:
        pre = [x for x in days if x["date"] < payday["date"]]
        if pre:
            low_pre = min(pre, key=lambda x: x["balance"])
            days_to = (_parse(payday["date"]) - as_of).days
            safe = round(low_pre["balance"] - FLOOR, 2)
            headroom = round(low_pre["balance"] + limit, 2)
            per_day = round(safe / days_to, 2) if safe > 0 and days_to > 0 else None

    return {
        "as_of": as_of.isoformat(),
        "horizon_end": horizon_end.isoformat(),
        "currency": "ILS",
        "start_balance": start,
        "overdraft_limit": limit,
        "floor": FLOOR,
        "accounts": accounts,
        "liquid_buffer": [{"label": s["label"], "balance": round(s["balance"], 2)}
                          for s in savings if s.get("liquid")],
        "next_payday": payday,
        "events": events,
        "days": days,
        "low_point": low,
        "low_before_payday": low_pre,
        "first_floor_breach": next((x["date"] for x in days if x["balance"] < FLOOR), None),
        "first_limit_breach": next((x["date"] for x in days if x["balance"] < -limit), None),
        "days_to_payday": days_to,
        "safe_to_spend": safe,
        "safe_per_day": per_day,
        "headroom_to_limit": headroom,
        "note": NOTE,
    }
