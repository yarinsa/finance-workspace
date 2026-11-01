"""The headline position (snapshot.json): balances, card debt, loans, savings, totals.

Pure functions of the normalized entities; data/digest.py loads them and writes the file.
"""
import datetime
from collections import defaultdict

from finance.origins import RISEUP_ORIGIN
from finance.views.runway import posting_date


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
        if posting_date(day) > as_of:
            due.setdefault(t["card_last4"], {}).setdefault(day.isoformat(), []).append(-t["amount"])
    out = {}
    for last4, by_day in due.items():
        day = min(by_day)
        out[last4] = {"date": day, "owed": round(sum(by_day[day]), 2)}
    return out, covered


def reconcile(e, as_of):
    """The position's entities, one copy each: what the digest stores (accounts, credit_cards,
    loans, savings_holdings) and what `totals` sums. `e` is the normalized entities by name."""
    accounts = e.get("accounts", [])
    cards = e.get("credit_cards", [])
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

    def clean(records):                           # drop internal stamps from output
        return [{k: v for k, v in r.items() if not k.startswith("_")} for r in records]

    return {"bank_accounts": clean(accounts), "credit_cards": clean(cards),
            "loans": clean(e.get("loans", [])), "savings": clean(e.get("savings", []))}


def totals(position, assets=None, income=None):
    """The headline sums over `reconcile`'s entities (or the same rows read back from the
    database). `assets` are the household's hand-typed assets (db/asset_store.py: the apartment),
    None when there is no database; `income` is RiseUp's frozen income entity (D8)."""
    accounts, cards = position["bank_accounts"], position["credit_cards"]
    loans, savings = position["loans"], position["savings"]
    cc_total = round(sum(c["owed"] for c in cards), 2)
    bank_sum = round(sum(a["balance"] for a in accounts), 2)
    mortgage_balance = round(sum(l["balance"] for l in loans if l["category"] == "mortgage"), 2)
    consumer_balance = round(sum(l["balance"] for l in loans if l["category"] == "consumer"), 2)
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
    savings_sum = round(sum(s["balance"] for s in savings), 2)
    liquid_savings_sum = round(sum(s["balance"] for s in savings if s.get("liquid")), 2)
    illiquid_savings_sum = round(savings_sum - liquid_savings_sum, 2)

    # Property (the apartment) is typed in by hand. It joins net worth only in its own
    # figure, so the existing totals keep answering the questions they always did.
    prop = [a for a in assets or [] if a.get("kind") == "property"]
    property_value = round(sum(a["value"] for a in prop), 2) if prop else None

    return {
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
    }


def debt_profile(loans):
    return {
        "mortgage": loan_profile([l for l in loans if l["category"] == "mortgage"]),
        "consumer": loan_profile([l for l in loans if l["category"] == "consumer"]),
        "all_loans": loan_profile(loans),
    }


def build_snapshot(e, as_of, generated_at, assets=None):
    """snapshot.json: `reconcile`'s entities plus `totals` and `debt_profile`."""
    position = reconcile(e, as_of)
    income = [{k: v for k, v in r.items() if not k.startswith("_")} for r in e.get("income", [])]
    return {
        "generated_at": generated_at,
        "currency": "ILS",
        "note": "Combined from the normalized layer. Bank balances, debts and long-term "
                "savings (pension / study funds). Property value and any savings held "
                "outside the scraped sources are still NOT included.",
        **position,
        "assets": assets or [],
        "income": income,
        "transactions_count": len(e.get("transactions", [])),
        "debt_profile": debt_profile(position["loans"]),
        "totals": totals(position, assets, income),
    }


def spending_summary(ledger):
    """Aggregate the deduped ledger -> totals, per-category and per-origin spend."""
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
