"""Read-only tools over a `Ledger` (assistant/ledger.py). The model never sees raw dumps and
never re-derives kind/category: it asks these functions, which read the pipeline's output.
Inputs come from the model, so they are validated and results are capped."""
import json
import re
from collections import defaultdict

MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MAX_SEARCH = 50
MAX_MONTHS = 24


def _counts(t):
    """Real spending/income rows: not own transfers, card settlements or savings."""
    return not (t.get("internal_transfer") or t.get("card_bill_payment") or t.get("savings"))


def _month(value, required=False):
    if value in (None, "") and not required:
        return None
    if not isinstance(value, str) or not MONTH.match(value):
        raise ValueError("month must look like YYYY-MM, e.g. 2026-10")
    return value


def _count(value, default, cap):
    return max(1, min(int(value if value is not None else default), cap))


SCHEMAS = {
    "spending_by_category": {
        "description": "Spending per category for one month, in ₪ (positive), largest first.",
        "parameters": {"type": "object", "properties": {"month": {"type": "string", "description": "YYYY-MM"}}, "required": ["month"]}},
    "monthly_totals": {
        "description": "Total spent and income for each of the most recent months.",
        "parameters": {"type": "object", "properties": {"months": {"type": "integer"}}}},
    "search_transactions": {
        "description": "Find transactions by description/merchant text. Money out is negative.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"}, "month": {"type": "string", "description": "YYYY-MM, optional"}, "limit": {"type": "integer"}},
            "required": ["text"]}},
    "snapshot_totals": {
        "description": "Net worth, balances, debt totals and debt profile.",
        "parameters": {"type": "object", "properties": {}}},
}


class Toolbox:
    """The tools bound to one ledger. Tools the ledger cannot back are not offered to the model."""

    def __init__(self, ledger):
        self.ledger = ledger
        self._rows = None

    def rows(self):
        if self._rows is None:   # one load per question, not per tool call
            self._rows = self.ledger.rows()
        return self._rows

    def names(self):
        has_snapshot = self.ledger.snapshot() is not None
        return [n for n in SCHEMAS if n != "snapshot_totals" or has_snapshot]

    def schemas(self):
        return [{"type": "function", "function": {"name": n, **SCHEMAS[n]}} for n in self.names()]

    def spending_by_category(self, month):
        month = _month(month, required=True)
        totals = defaultdict(float)
        for t in self.rows():
            if t["date"].startswith(month) and _counts(t) and t["amount"] < 0:
                totals[t.get("category") or "uncategorized"] += -t["amount"]
        return [{"category": c, "total": round(v, 2)} for c, v in sorted(totals.items(), key=lambda kv: -kv[1])]

    def monthly_totals(self, months=6):
        months = _count(months, 6, MAX_MONTHS)
        spent, income = defaultdict(float), defaultdict(float)
        for t in self.rows():
            if not _counts(t):
                continue
            (spent if t["amount"] < 0 else income)[t["date"][:7]] += abs(t["amount"])
        keys = sorted(set(spent) | set(income))[-months:]
        return [{"month": m, "spent": round(spent[m], 2), "income": round(income[m], 2)} for m in keys]

    def search_transactions(self, text, month=None, limit=20):
        month, limit = _month(month), _count(limit, 20, MAX_SEARCH)
        needle = str(text).lower()
        rows = [t for t in self.rows()
                if needle in f"{t.get('description') or ''} {t.get('merchant') or ''}".lower()
                and (not month or t["date"].startswith(month))]
        rows.sort(key=lambda t: t["date"], reverse=True)
        return [{k: t.get(k) for k in ("date", "amount", "description", "category", "kind")} for t in rows[:limit]]

    def snapshot_totals(self):
        s = self.ledger.snapshot()
        return {"totals": s.get("totals"), "debt_profile": s.get("debt_profile"), "generated_at": s.get("generated_at")}

    def call(self, name, arguments):
        """Run an offered tool by name; errors come back as data so the model can recover."""
        try:
            if name not in self.names():
                raise ValueError(f"unknown tool {name!r}")
            return getattr(self, name)(**(arguments or {}))
        except Exception as e:  # noqa: BLE001 - surfaced to the model, not swallowed
            return {"error": f"{type(e).__name__}: {e}"}

    def call_json(self, name, arguments):
        return json.dumps(self.call(name, arguments), ensure_ascii=False)
