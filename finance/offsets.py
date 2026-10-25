"""Offsets (קיזוז): net a payback against the expense it pays back.

A friend's Bit for their half of dinner, a merchant refund, a roommate's share of the
rent — money in that only cancels money out. Counting both inflates spending *and*
income, so an offset moves the payback's ₪ onto the expense: the expense counts for
what the household really bore (in the expense's month and category), the payback
for whatever is left of it (usually nothing).

Three layers, applied by `resolve`:

    manual_offsets  the user's links (db `transaction_offsets`), on the payback row.
                    Present (even as []) = the user decided; auto is ignored.
    auto_offsets    `suggest`'s links, stored on the payback by the digest:
                    a same-merchant card refund, or a household rule
                    (data/offsets/rules.json, e.g. a roommate's transfers vs the rent).
    offsets         the effective links on both rows, plus `offset_amount`.

Rows are ledger dicts (data/digested/transactions.json shape) keyed by
(date, abs amount), like everywhere else. Offsets never change `amount`: balances,
the runway and validation keep the real money; `cashflow_view` is what the
spending/income figures read. Shared by data/digest.py and the ledger API.
"""
import datetime as dt

from finance.merchants import merchant_name

CARD_ORIGINS = {"cal", "amex", "max"}
REFUND_WINDOW_DAYS = 180     # a refund lands within this long after the purchase
RULE_WINDOW_DAYS = 31        # a rule's payback and its expense are about a month apart at most
_EPS = 0.005


def row_key(t):
    """The ledger key: (ISO date, abs amount to the agora)."""
    return str(t["date"])[:10], round(abs(float(t["amount"])), 2)


def _day(t):
    return dt.date.fromisoformat(str(t["date"])[:10])


def eligible(t):
    """Real money in or out: not a transfer, card-bill settlement or savings move."""
    return not (t.get("internal_transfer") or t.get("card_bill_payment") or t.get("savings")) \
        and abs(float(t.get("amount") or 0)) > _EPS


def is_payback(t):
    return eligible(t) and float(t["amount"]) > 0


def is_expense(t):
    return eligible(t) and float(t["amount"]) < 0


def _link(other, amount, kind):
    d, a = row_key(other)
    return {"date": d, "abs_amount": a, "amount": round(amount, 2), "kind": kind,
            "description": other.get("description") or None}


def _rule_links(p, expenses, left, rules):
    """A rule's payer paid us back: spread the payback over its `against` expenses,
    same calendar month first, then the nearest within RULE_WINDOW_DAYS."""
    desc = p.get("description") or ""
    for rule in rules:
        if not rule.get("payer") or rule["payer"] not in desc:
            continue
        against = rule.get("against") or []
        pd, month = _day(p), str(p["date"])[:7]

        def rank(e):
            prio = next(i for i, pat in enumerate(against) if pat in (e.get("description") or ""))
            return str(e["date"])[:7] != month, prio, abs((_day(e) - pd).days)

        cands = sorted((e for e in expenses
                        if any(pat in (e.get("description") or "") for pat in against)
                        and abs((_day(e) - pd).days) <= RULE_WINDOW_DAYS), key=rank)
        need, links = left[row_key(p)], []
        for e in cands:
            take = min(need, left[row_key(e)])
            if take > _EPS:
                links.append(_link(e, take, "rule"))
                left[row_key(e)] -= take
                need -= take
            if need <= _EPS:
                break
        if links:
            left[row_key(p)] = need
            return links
    return []


def _refund_link(p, expenses, left):
    """A card refund: the latest earlier purchase at the same merchant that can absorb
    it in full (an exact-amount purchase wins), within REFUND_WINDOW_DAYS."""
    if p.get("origin") not in CARD_ORIGINS:
        return []
    m, pd, amt = merchant_name(p.get("description")), _day(p), row_key(p)[1]
    cands = [e for e in expenses
             if merchant_name(e.get("description")) == m
             and 0 <= (pd - _day(e)).days <= REFUND_WINDOW_DAYS
             and left[row_key(e)] + _EPS >= amt]
    if not cands:
        return []
    e = min(cands, key=lambda e: (abs(left[row_key(e)] - amt) > _EPS, (pd - _day(e)).days))
    left[row_key(e)] -= amt
    left[row_key(p)] = 0.0
    return [_link(e, amt, "refund")]


def suggest(ledger, rules=()):
    """Set `auto_offsets` on every payback the rules or a same-merchant refund explain.

    Paybacks are taken oldest first, each consuming what's left of its expenses, so
    two refunds never claim the same ₪. Mutates and returns `ledger`."""
    expenses = [t for t in ledger if is_expense(t)]
    left = {row_key(t): row_key(t)[1] for t in ledger if eligible(t)}
    for p in sorted((t for t in ledger if is_payback(t)), key=lambda t: str(t["date"])):
        p.pop("auto_offsets", None)
        links = _rule_links(p, expenses, left, rules) or _refund_link(p, expenses, left)
        if links:
            p["auto_offsets"] = links
    return ledger


def resolve(ledger):
    """Turn the stored links into effective `offsets` + `offset_amount` on both sides.

    Manual decisions are applied before any auto link, so the user's link always gets
    the ₪ first; every link is clamped to what is left of both rows, and links to a
    row that is gone (re-scraped away, excluded, or now a transfer) are dropped.
    Mutates and returns `ledger`."""
    by_key = {row_key(t): t for t in ledger}
    for t in ledger:
        t.pop("offsets", None)
        t.pop("offset_amount", None)
    left = {k: k[1] for k, t in by_key.items() if eligible(t)}
    paybacks = sorted((t for t in ledger if is_payback(t)), key=lambda t: str(t["date"]))
    manual = [p for p in paybacks if p.get("manual_offsets") is not None]
    auto = [p for p in paybacks if p.get("manual_offsets") is None]
    for p, links, kind in [*((p, p["manual_offsets"], "manual") for p in manual),
                           *((p, p.get("auto_offsets") or [], None) for p in auto)]:
        pk = row_key(p)
        for link in links:
            ek = (str(link["date"])[:10], round(float(link["abs_amount"]), 2))
            e = by_key.get(ek)
            if e is None or not is_expense(e) or ek not in left:
                continue
            take = min(float(link["amount"]), left[pk], left[ek])
            if take <= _EPS:
                continue
            if kind is None and link.get("kind") == "refund" and take < float(link["amount"]) - _EPS:
                continue    # a refund is all or nothing; a manual link took its expense first
            left[pk] -= take
            left[ek] -= take
            k = kind or link.get("kind") or "refund"
            p.setdefault("offsets", []).append(_link(e, take, k))
            e.setdefault("offsets", []).append(_link(p, take, k))
    for t in ledger:
        if t.get("offsets"):
            t["offset_amount"] = round(sum(link["amount"] for link in t["offsets"]), 2)
    return ledger


def net_amount(t):
    """The signed ₪ a row contributes to spending/income once offsets are netted out."""
    a, o = float(t.get("amount") or 0), float(t.get("offset_amount") or 0)
    return round(a + o if a < 0 else a - o, 2)


def cashflow_view(ledger):
    """The ledger as spending/income figures should count it: `amount` is the net,
    `gross_amount` the real money. A payback that is fully netted out is dropped; a
    fully paid-back expense stays at ₪0 so the user can still find (and undo) it."""
    out = []
    for t in ledger:
        if not t.get("offset_amount"):
            out.append(t)
            continue
        net = net_amount(t)
        if float(t["amount"]) > 0 and abs(net) <= _EPS:
            continue
        out.append({**t, "amount": net, "gross_amount": t["amount"]})
    return out


def candidates(ledger, expense, limit=20):
    """Paybacks that could offset `expense`: income from a month before it (a
    roommate pays ahead of the rent) to REFUND_WINDOW_DAYS after, with ₪ still unused;
    same merchant first, then nearest date. Expects `resolve` to have run."""
    ed, m = _day(expense), merchant_name(expense.get("description"))

    def free(t):
        return row_key(t)[1] - float(t.get("offset_amount") or 0)

    cands = [t for t in ledger if is_payback(t) and free(t) > _EPS
             and -RULE_WINDOW_DAYS <= (_day(t) - ed).days <= REFUND_WINDOW_DAYS]
    cands.sort(key=lambda t: (merchant_name(t.get("description")) != m, abs((_day(t) - ed).days)))
    return cands[:limit]
