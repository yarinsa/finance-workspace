#!/usr/bin/env python3
"""Normalize More Investment House (מור בית השקעות) raw dumps -> more/normalized/*.json

Common envelope written for every entity:
    {"source", "entity", "generated_at", "records": [...]}

Entities emitted: savings.

More holds the household's study funds (קרן השתלמות, incl. the self-employed
one) and a קופת גמל להשקעה. Like Harel these are long-term SAVINGS ASSETS, not
cashflow: deliberately no `transactions` entity, so deposits never inflate
`total_spent` (the bank-side debit is already captured by the bank source).

Raw input: raw/dashboard-accounts.json — the SPA's cached
getDashboardAccountsData response: a 2-element list, [0] = the user's own
accounts, [1] = accounts the user manages for others (ignored). One record is
emitted per fund (kupaNum) with a non-zero balance.

Self-contained; safe to re-run after each scrape.
"""
import json, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../data/more
RAW = HERE / "raw"
OUT = HERE / "normalized"
OUT.mkdir(exist_ok=True)
SOURCE = "more"
NOW = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
TODAY = datetime.date.today().isoformat()

# More's productType codes (from the dashboard tiles).
PRODUCT_KIND = {
    1: "study_fund",        # קרן השתלמות
    2: "provident_fund",    # גמל לחיסכון
    3: "pension",           # פנסיה
    4: "investment_gemel",  # קופת גמל להשקעה
    5: "child_savings",     # חיסכון לכל ילד
}


def load(name, default=None):
    path = RAW / name
    if not path.exists() or path.stat().st_size == 0:
        return default
    try:
        return json.load(open(path, encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def emit(entity, records):
    path = OUT / f"{entity}.json"
    path.write_text(json.dumps(
        {"source": SOURCE, "entity": entity, "generated_at": NOW, "records": records},
        ensure_ascii=False, indent=2))
    print(f"  {SOURCE}/{path.name}: {len(records)} records")


dump = load("dashboard-accounts.json", []) or []
own = dump[0] if dump and isinstance(dump[0], dict) else {}
as_of = (own.get("lastUpdate") or "")[:10] or None

savings = []
for product in own.get("accountData") or []:
    kind = PRODUCT_KIND.get(product.get("productType"), "savings")
    name = product.get("productName") or kind
    for k in product.get("productsDetails") or []:
        balance = round(float(k.get("balanceData") or 0), 2)
        if balance == 0:
            continue                      # empty/legacy employer funds
        liq = (k.get("liquidityDate") or "")[:10] or None
        employer = (k.get("employerName") or "").strip()
        label = f"More {name} {k.get('kupaNum')} ({k.get('workStateName') or ''}"
        label += f" · {employer})" if employer else ")"
        savings.append({
            "institution": "more",
            "topic_id": str(k.get("kupaNum")),
            "kind": kind,
            "label": label.replace(" ()", ""),
            "section": name,
            "policies_count": None,
            "balance": balance,
            "currency": "ILS",
            "work_state": k.get("workStateName"),
            "liquidity_date": liq,
            # A study fund becomes withdrawable on its liquidity date.
            "liquid": bool(liq and liq <= TODAY),
            "as_of": as_of,
            "management_fee": None,
            "yield_ytd": None,
        })

savings.sort(key=lambda r: -r["balance"])
emit("savings", savings)
