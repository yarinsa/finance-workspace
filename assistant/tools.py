"""Read-only tools over the digested ledger. The model never sees raw dumps and
never re-derives kind/category: it asks these functions, which read the pipeline's output."""
import json
import os
from collections import defaultdict
from pathlib import Path

from finance.offsets import cashflow_view

DIGESTED = Path(os.environ.get("FINANCE_DIGESTED_DIR", Path(__file__).resolve().parents[1] / "data" / "digested"))


def _load(name):
    return json.loads((DIGESTED / name).read_text())


def _ledger():
    return cashflow_view(_load("transactions.json")["transactions"])


def _counts(t):
    """Real spending/income rows: not own transfers, card settlements or savings."""
    return not (t.get("internal_transfer") or t.get("card_bill_payment") or t.get("savings"))


def spending_by_category(month, ledger=None):
    """Spending per category for `month` (YYYY-MM), in ₪ as positive numbers, largest first."""
    totals = defaultdict(float)
    for t in ledger if ledger is not None else _ledger():
        if t["date"].startswith(month) and _counts(t) and t["amount"] < 0:
            totals[t.get("category") or "uncategorized"] += -t["amount"]
    return [{"category": c, "total": round(v, 2)} for c, v in sorted(totals.items(), key=lambda kv: -kv[1])]


def monthly_totals(months=6, ledger=None):
    """Spent and income per month, most recent `months` months with data."""
    spent, income = defaultdict(float), defaultdict(float)
    for t in ledger if ledger is not None else _ledger():
        if not _counts(t):
            continue
        m = t["date"][:7]
        if t["amount"] < 0:
            spent[m] += -t["amount"]
        else:
            income[m] += t["amount"]
    keys = sorted(set(spent) | set(income))[-months:]
    return [{"month": m, "spent": round(spent[m], 2), "income": round(income[m], 2)} for m in keys]


def search_transactions(text, month=None, limit=20, ledger=None):
    """Transactions whose description/merchant contains `text`, newest first. Money out is negative."""
    needle = text.lower()
    rows = [
        t for t in (ledger if ledger is not None else _ledger())
        if needle in f"{t.get('description') or ''} {t.get('merchant') or ''}".lower()
        and (not month or t["date"].startswith(month))
    ]
    rows.sort(key=lambda t: t["date"], reverse=True)
    return [{k: t.get(k) for k in ("date", "amount", "description", "category", "kind")} for t in rows[:limit]]


def snapshot_totals():
    """Net-worth and debt totals from the snapshot."""
    s = _load("snapshot.json")
    return {"totals": s.get("totals"), "debt_profile": s.get("debt_profile"), "generated_at": s.get("generated_at")}


REGISTRY = {f.__name__: f for f in (spending_by_category, monthly_totals, search_transactions, snapshot_totals)}

SCHEMAS = [
    {"type": "function", "function": {
        "name": "spending_by_category", "description": "Spending per category for one month, in ₪ (positive), largest first.",
        "parameters": {"type": "object", "properties": {"month": {"type": "string", "description": "YYYY-MM"}}, "required": ["month"]}}},
    {"type": "function", "function": {
        "name": "monthly_totals", "description": "Total spent and income for each of the most recent months.",
        "parameters": {"type": "object", "properties": {"months": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "search_transactions", "description": "Find transactions by description/merchant text. Money out is negative.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"}, "month": {"type": "string", "description": "YYYY-MM, optional"}, "limit": {"type": "integer"}},
            "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "snapshot_totals", "description": "Net worth, balances, debt totals and debt profile.",
        "parameters": {"type": "object", "properties": {}}}},
]


def call(name, arguments):
    """Run a tool by name; errors come back as data so the model can recover."""
    try:
        return REGISTRY[name](**(arguments or {}))
    except Exception as e:  # noqa: BLE001 - surfaced to the model, not swallowed
        return {"error": f"{type(e).__name__}: {e}"}
