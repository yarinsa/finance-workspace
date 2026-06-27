#!/usr/bin/env python3
"""Combine the normalized layer -> data/digested/snapshot.{json,md}

Pipeline:  raw/  --(each source's normalize.py)-->  normalized/  --(this)-->  digested/

By default this runs every <source>/normalize.py first, then combines all
<source>/normalized/*.json envelopes into one consolidated snapshot.
Run `python3 digest.py --no-normalize` to combine existing normalized output only.
"""
import json, datetime, glob, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent          # .../Finance/data
OUT = ROOT / "digested"
OUT.mkdir(exist_ok=True)


def run_normalizers():
    for script in sorted(ROOT.glob("*/normalize.py")):
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
# NOTE: tuned to this household. Update OWN_NAMES / OWN_ACCOUNT_HINTS if accounts
# or holders change. External salary ("העברת משכורת", "בנק לאומי משכורת") does NOT
# name the holder, so it is correctly kept as real income.
OWN_NAMES = ["ירין ששון", "ששון ירין"]
OWN_ACCOUNT_HINTS = ["806-6719", "806-671963", "10-806", "0034069", "0123444499"]
# Account-sweep descriptions that don't name the holder but are confirmed self-
# transfers between our own accounts. "העברה דיגיטל" always originates from the
# Leumi account and empties it to ~0, matched by a "+X העברה מירין ששון" inbound
# on Discount — i.e. a Leumi→Discount sweep. Treated as internal.
OWN_TRANSFER_DESCRIPTIONS = ["העברה דיגיטל"]


def is_internal_transfer(rec):
    """True if the transaction is a move between the household's own accounts.

    Matches on the description referencing an own holder name, own account
    number, or a known self-transfer phrase. Conservative: only fires on a
    positive signal, so external transfers (real income/expense) are kept.
    """
    desc = rec.get("description") or ""
    if any(n in desc for n in OWN_NAMES):
        return True
    if any(a in desc for a in OWN_ACCOUNT_HINTS):
        return True
    if any(p in desc for p in OWN_TRANSFER_DESCRIPTIONS):
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


def is_card_bill_payment(rec):
    """True if this is a bank→card-issuer monthly settlement (not real spend)."""
    if rec.get("origin") not in BANK_ORIGINS:
        return False
    if float(rec.get("amount") or 0) >= 0:        # settlements are debits
        return False
    desc = (rec.get("description") or "")
    low = desc.lower()
    if "חיוב" in desc and any(p in desc for p in CARD_BILL_PHRASES if p.isascii() is False):
        return True
    # ascii issuer names (max) — match on the lowercased description
    if "חיוב" in desc and any(p in low for p in CARD_BILL_PHRASES if p.isascii()):
        return True
    return False


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
    "cal": "cal", "leumicard": "cal",            # both are CAL-cleared cards in RiseUp
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
        "_riseup": src == "riseup",
    }
    if is_internal_transfer(t):
        t["internal_transfer"] = True            # excluded from cashflow/summary
    elif is_card_bill_payment(t):
        t["card_bill_payment"] = True            # excluded — purchases already in ledger
    elif is_savings_deposit(t):
        t["savings"] = True                      # real outflow, but saved not spent
    return t


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
        # backfill anything the winner is missing from the other copy
        for f in ("category", "card_last4", "account_id", "origin"):
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
            if test(winner):
                winner[flag] = True
            else:
                winner.pop(flag, None)
        if not winner.get("description"):
            winner["description"] = other.get("description", "")
        buckets[key] = winner

    out = []
    for t in buckets.values():
        t.pop("_riseup", None)
        out.append({k: v for k, v in t.items() if v is not None})
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def build_snapshot(e):
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
    cards = debt_cards
    cc_total = round(sum(c["owed"] for c in cards), 2)
    bank_sum = round(sum(a["balance"] for a in accounts), 2)
    mortgage = [l for l in loans if l["category"] == "mortgage"]
    consumer = [l for l in loans if l["category"] == "consumer"]
    mortgage_balance = round(sum(l["balance"] for l in mortgage), 2)
    consumer_balance = round(sum(l["balance"] for l in consumer), 2)
    loan_monthly = round(sum(l["monthly_payment"] for l in loans), 2)
    salary = income[0]["monthly_amount"] if income else None

    tracked_net = round(bank_sum - cc_total - mortgage_balance - consumer_balance, 2)

    def clean(records):                           # drop internal stamps from output
        return [{k: v for k, v in r.items() if not k.startswith("_")} for r in records]

    return {
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "currency": "ILS",
        "note": "Combined from the normalized layer. Tracked accounts only — property value "
                "and external savings/investments are NOT in these sources, so totals reflect "
                "bank balances and debts, not full net worth.",
        "bank_accounts": clean(accounts),
        "credit_cards": clean(cards),
        "loans": clean(loans),
        "income": clean(income),
        "transactions_count": len(txns),
        "totals": {
            "bank_balances_sum": bank_sum,
            "credit_card_debt": cc_total,
            "mortgage_balance": mortgage_balance,
            "consumer_loan_balance": consumer_balance,
            "total_debt": round(cc_total + mortgage_balance + consumer_balance, 2),
            "tracked_net_position": tracked_net,
            "monthly_loan_service": loan_monthly,
            "detected_monthly_salary": salary,
        },
    }


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
    md.append("| Card | Owed |")
    md.append("|---|--:|")
    for c in s["credit_cards"]:
        md.append(f"| {c['issuer']} ····{c['last4']} | {ils(c['owed'])} |")
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


def main():
    if "--no-normalize" not in sys.argv:
        run_normalizers()
    entities = load_entities()

    # one deduped, queryable transaction ledger across every source
    ledger = consolidate_transactions(entities.get("transactions", []))
    summary = spending_summary(ledger)
    (OUT / "transactions.json").write_text(json.dumps(
        {"generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
         "currency": "ILS",
         "note": "Deduped across all sources on (date, abs amount); RiseUp's copy wins on "
                 "conflict and carries the spending category. `sources` lists every scraper "
                 "that saw the transaction.",
         "summary": summary,
         "transactions": ledger},
        ensure_ascii=False, indent=2))

    snapshot = build_snapshot(entities)
    snapshot["spending"] = summary
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
